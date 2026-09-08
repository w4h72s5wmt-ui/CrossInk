#include "RssNewsActivity.h"

#include <Arduino.h>
#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <Logging.h>
#include <Memory.h>
#include <WiFi.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>

#include "MappedInputManager.h"
#include "SdCardFontSystem.h"
#include "SilentRestart.h"
#include "activities/network/WifiSelectionActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UIScale.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "network/HttpDownloader.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;
constexpr size_t HTTP_BUFFER_SIZE = 4096;
constexpr size_t ARTICLE_PAGE_LINES = 8;
constexpr int SORT_TOUCH_WIDTH = 72;

struct CacheHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t count;
};

HeapByteBuffer allocateRssBuffer(const size_t bytes) {
  auto buffer = makePsramByteBufferNoThrow(bytes);
  if (!buffer) buffer = makeHeapByteBufferNoThrow(bytes);
  return buffer;
}

bool sameRssItem(const RssItem& left, const RssItem& right) {
  if (left.link[0] && right.link[0]) return std::strcmp(left.link, right.link) == 0;
  if (std::strcmp(left.title, right.title) != 0) return false;
  if (left.published[0] || right.published[0]) return std::strcmp(left.published, right.published) == 0;
  return true;
}

int monthNumber(const char* month) {
  static constexpr const char* MONTHS[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  if (!month) return 0;
  for (int i = 0; i < 12; ++i) {
    if (std::tolower(static_cast<unsigned char>(month[0])) == std::tolower(static_cast<unsigned char>(MONTHS[i][0])) &&
        std::tolower(static_cast<unsigned char>(month[1])) == std::tolower(static_cast<unsigned char>(MONTHS[i][1])) &&
        std::tolower(static_cast<unsigned char>(month[2])) == std::tolower(static_cast<unsigned char>(MONTHS[i][2]))) {
      return i + 1;
    }
  }
  return 0;
}

int64_t daysFromCivil(int year, unsigned month, unsigned day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(year - era * 400);
  const unsigned doy = (153 * (month + (month > 2 ? static_cast<unsigned>(-3) : 9)) + 2) / 5 + day - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return static_cast<int64_t>(era) * 146097 + static_cast<int64_t>(doe) - 719468;
}

int parseTimezoneOffsetSeconds(const char* zone) {
  if (!zone || !zone[0] || std::strcmp(zone, "GMT") == 0 || std::strcmp(zone, "UTC") == 0 || zone[0] == 'Z') return 0;
  if (zone[0] != '+' && zone[0] != '-') return 0;
  int hours = 0;
  int minutes = 0;
  if (std::sscanf(zone + 1, "%2d:%2d", &hours, &minutes) < 1 && std::sscanf(zone + 1, "%2d%2d", &hours, &minutes) < 1) {
    return 0;
  }
  const int seconds = hours * 3600 + minutes * 60;
  return zone[0] == '-' ? -seconds : seconds;
}

int64_t makeDateKey(int year, int month, int day, int hour, int minute, int second, int zoneOffsetSeconds) {
  if (year < 1970 || month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 || minute < 0 ||
      minute > 59 || second < 0 || second > 60) {
    return 0;
  }
  return daysFromCivil(year, static_cast<unsigned>(month), static_cast<unsigned>(day)) * 86400LL + hour * 3600LL +
         minute * 60LL + second - zoneOffsetSeconds;
}

int64_t publishedDateKey(const char* value) {
  if (!value || !value[0]) return 0;

  int year = 0;
  int month = 0;
  int day = 0;
  int hour = 0;
  int minute = 0;
  int second = 0;
  char zone[8] = {};

  // ISO 8601 / RFC 3339, as commonly used by Atom feeds.
  if (std::sscanf(value, "%4d-%2d-%2dT%2d:%2d:%2d%7s", &year, &month, &day, &hour, &minute, &second, zone) >= 6 ||
      std::sscanf(value, "%4d-%2d-%2d %2d:%2d:%2d%7s", &year, &month, &day, &hour, &minute, &second, zone) >= 6) {
    return makeDateKey(year, month, day, hour, minute, second, parseTimezoneOffsetSeconds(zone));
  }

  // RFC 822 / RFC 1123, with or without a weekday prefix.
  char monthText[4] = {};
  zone[0] = '\0';
  int matched = std::sscanf(value, "%*3s, %2d %3s %4d %2d:%2d:%2d %7s", &day, monthText, &year, &hour, &minute,
                            &second, zone);
  if (matched < 6) {
    zone[0] = '\0';
    matched = std::sscanf(value, "%2d %3s %4d %2d:%2d:%2d %7s", &day, monthText, &year, &hour, &minute, &second,
                          zone);
  }
  if (matched >= 6) {
    month = monthNumber(monthText);
    return makeDateKey(year, month, day, hour, minute, second, parseTimezoneOffsetSeconds(zone));
  }
  return 0;
}

Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {
  const Rect header = TouchHeaderBackButton::headerRect(renderer, input);
  return Rect{header.x + header.width - SORT_TOUCH_WIDTH, header.y, SORT_TOUCH_WIDTH, header.height};
}
}  // namespace

RssNewsActivity::RssNewsActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("RssNews", renderer, mappedInput),
      uiTarget(makeUiTarget(renderer)),
      app(uiTarget, uiTarget.deviceContext()) {}

void RssNewsActivity::onEnter() {
  Activity::onEnter();
  sdFontSystem.releaseLoadedFont(renderer);

  state = State::LIST;
  sortMode = SortMode::DATE_DESC;
  selectorIndex = 0;
  topIndex = 0;
  visibleRows = 1;
  articleCount = 0;
  articleLineOffset = 0;
  openArticleIndex = MAX_ARTICLES;
  refreshHadError = false;
  usedNetwork = false;
  goHomeAfterRefreshCancel = false;
  statusMessage.clear();
  articleTitleLines.clear();
  articleSummaryLines.clear();

  applySharedUiTheme(app, uiTarget);
  app.on(ACTION_ROW, &RssNewsActivity::onRowEvent, this);
  app.setScreen(&RssNewsActivity::rootScreen, this);

  if (!ensureBuffers()) {
    statusMessage = tr(STR_MEMORY_ERROR);
  } else {
    loadCache();
    rebuildDisplayOrder();
  }
  requestUpdate();
}

void RssNewsActivity::onExit() {
  Activity::onExit();
  uiReady = false;
  articleTitleLines.clear();
  articleSummaryLines.clear();
  displayOrder = nullptr;
  listItems = nullptr;
  feedItems = nullptr;
  articles = nullptr;
  displayOrderStorage.reset();
  listItemStorage.reset();
  feedStorage.reset();
  articleStorage.reset();

#ifndef SIMULATOR
  if (usedNetwork || WiFi.getMode() != WIFI_MODE_NULL) {
    if (WiFi.getMode() != WIFI_MODE_NULL) {
      WiFi.disconnect(false);
      delay(30);
    }
    silentRestartAfterNetwork();
  }
#endif
}

bool RssNewsActivity::ensureBuffers() {
  if (!articleStorage) {
    articleStorage = allocateRssBuffer(sizeof(CachedArticle) * MAX_ARTICLES);
    if (!articleStorage) {
      LOG_ERR("RSS", "OOM allocating article cache (%zu records)", MAX_ARTICLES);
      return false;
    }
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
    std::memset(articles, 0, sizeof(CachedArticle) * MAX_ARTICLES);
  } else if (!articles) {
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
  }

  if (!feedStorage) {
    feedStorage = allocateRssBuffer(sizeof(RssItem) * FEED_ITEM_CAPACITY);
    if (!feedStorage) {
      LOG_ERR("RSS", "OOM allocating feed scratch (%zu records)", FEED_ITEM_CAPACITY);
      return false;
    }
    feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
    std::memset(feedItems, 0, sizeof(RssItem) * FEED_ITEM_CAPACITY);
  } else if (!feedItems) {
    feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
  }

  if (!listItemStorage) {
    listItemStorage = allocateRssBuffer(sizeof(fui::ListItem) * (MAX_ARTICLES + 1));
    if (!listItemStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list items");
      return false;
    }
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
    std::memset(listItems, 0, sizeof(fui::ListItem) * (MAX_ARTICLES + 1));
  } else if (!listItems) {
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
  }

  if (!displayOrderStorage) {
    displayOrderStorage = allocateRssBuffer(sizeof(uint16_t) * MAX_ARTICLES);
    if (!displayOrderStorage) {
      LOG_ERR("RSS", "OOM allocating RSS sort index");
      return false;
    }
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
    std::memset(displayOrder, 0, sizeof(uint16_t) * MAX_ARTICLES);
  } else if (!displayOrder) {
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
  }

  return true;
}

bool RssNewsActivity::loadCache() {
  articleCount = 0;
  if (!articles || !Storage.exists(CACHE_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", CACHE_PATH, file)) return false;

  CacheHeader header{};
  const bool headerOk = file.read(&header, sizeof(header)) == static_cast<int>(sizeof(header));
  if (!headerOk || header.magic != CACHE_MAGIC || header.version != CACHE_VERSION || header.count > MAX_ARTICLES) {
    LOG_ERR("RSS", "Ignoring incompatible RSS cache; refresh will rebuild it");
    file.close();
    return false;
  }

  for (uint16_t i = 0; i < header.count; ++i) {
    CachedArticle article{};
    if (file.read(&article, sizeof(article)) != static_cast<int>(sizeof(article)) || article.sourceIndex >= SOURCE_COUNT) {
      LOG_ERR("RSS", "RSS cache truncated or invalid at record %u", static_cast<unsigned>(i));
      articleCount = 0;
      file.close();
      return false;
    }
    articles[articleCount++] = article;
  }
  file.close();
  LOG_DBG("RSS", "Loaded %zu cached articles", articleCount);
  return true;
}

bool RssNewsActivity::saveCache() const {
  if (!articles) return false;
  Storage.ensureDirectoryExists("/.crosspoint");
  Storage.remove(CACHE_TMP_PATH);

  FsFile file;
  if (!Storage.openFileForWrite("RSS", CACHE_TMP_PATH, file)) return false;
  const CacheHeader header{CACHE_MAGIC, CACHE_VERSION, static_cast<uint16_t>(articleCount)};
  if (file.write(&header, sizeof(header)) != sizeof(header)) {
    file.close();
    Storage.remove(CACHE_TMP_PATH);
    return false;
  }
  for (size_t i = 0; i < articleCount; ++i) {
    if (file.write(&articles[i], sizeof(CachedArticle)) != sizeof(CachedArticle)) {
      file.close();
      Storage.remove(CACHE_TMP_PATH);
      return false;
    }
  }
  const bool synced = file.sync();
  file.close();
  if (!synced) {
    Storage.remove(CACHE_TMP_PATH);
    return false;
  }

  Storage.remove(CACHE_PATH);
  if (!Storage.rename(CACHE_TMP_PATH, CACHE_PATH)) {
    LOG_ERR("RSS", "Could not promote RSS cache file");
    return false;
  }
  return true;
}

void RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {
  if (!articles || !items || sourceIndex >= SOURCE_COUNT) return;

  size_t mergedCount = 0;
  const size_t incomingCount = std::min(count, ITEMS_PER_SOURCE);
  for (size_t i = 0; i < incomingCount; ++i) {
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (sameRssItem(items[i], items[j])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) {
      if (mergedCount != i) items[mergedCount] = items[i];
      ++mergedCount;
    }
  }

  for (size_t i = 0; i < articleCount && mergedCount < ITEMS_PER_SOURCE; ++i) {
    if (articles[i].sourceIndex != sourceIndex) continue;
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (sameRssItem(articles[i].item, items[j])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) items[mergedCount++] = articles[i].item;
  }

  size_t writeIndex = 0;
  for (size_t readIndex = 0; readIndex < articleCount; ++readIndex) {
    if (articles[readIndex].sourceIndex == sourceIndex) continue;
    if (writeIndex != readIndex) articles[writeIndex] = articles[readIndex];
    ++writeIndex;
  }
  articleCount = writeIndex;

  const size_t addCount = std::min(mergedCount, MAX_ARTICLES - articleCount);
  for (size_t i = 0; i < addCount; ++i) {
    CachedArticle& article = articles[articleCount++];
    article = CachedArticle{};
    article.sourceIndex = sourceIndex;
    article.item = items[i];
  }
}

void RssNewsActivity::rebuildDisplayOrder() {
  if (!displayOrder || !articles) return;
  for (size_t i = 0; i < articleCount; ++i) displayOrder[i] = static_cast<uint16_t>(i);

  std::stable_sort(displayOrder, displayOrder + articleCount, [this](const uint16_t leftIndex, const uint16_t rightIndex) {
    const CachedArticle& left = articles[leftIndex];
    const CachedArticle& right = articles[rightIndex];
    if (sortMode == SortMode::SOURCE && left.sourceIndex != right.sourceIndex) return left.sourceIndex < right.sourceIndex;

    const int64_t leftDate = publishedDateKey(left.item.published);
    const int64_t rightDate = publishedDateKey(right.item.published);
    if (leftDate != rightDate) return leftDate > rightDate;
    if (sortMode == SortMode::DATE_DESC && left.sourceIndex != right.sourceIndex) return left.sourceIndex < right.sourceIndex;
    return leftIndex < rightIndex;
  });
}

void RssNewsActivity::toggleSortMode() {
  if (state != State::LIST) return;
  sortMode = sortMode == SortMode::DATE_DESC ? SortMode::SOURCE : SortMode::DATE_DESC;
  rebuildDisplayOrder();
  selectorIndex = 0;
  topIndex = 0;
  requestUpdate();
}

size_t RssNewsActivity::articleIndexForDisplayRow(const size_t displayRow) const {
  if (!displayOrder || displayRow >= articleCount) return MAX_ARTICLES;
  return static_cast<size_t>(displayOrder[displayRow]);
}

void RssNewsActivity::rootScreen(UiApp::ScreenType& screen, void* user) {
  auto* self = static_cast<RssNewsActivity*>(user);
  switch (self->state) {
    case State::LIST:
      self->buildListScreen(screen);
      break;
    case State::ARTICLE:
      self->buildArticleScreen(screen);
      break;
    case State::WIFI_SELECTION:
    case State::REFRESHING:
      self->buildStatusScreen(screen);
      break;
  }
}

void RssNewsActivity::screenHeader(UiApp::ScreenType& screen) {
  screen.takeBottom(static_cast<int16_t>(UITheme::getInstance().getMetrics().buttonHintsHeight));
  if (mappedInput.hasTouchHardware()) {
    const Rect headerRect = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const int rightReserve = state == State::LIST ? SORT_TOUCH_WIDTH : 0;
    TouchHeaderBackButton::draw(renderer, uiTarget, headerRect, "RSS", false, rightReserve);
    if (state == State::LIST) {
      fui::TextStyle sortStyle = screen.theme().smallText;
      sortStyle.align = fui::TextAlign::Center;
      sortStyle.maxLines = 1;
      const Rect touch = sortTouchRect(renderer, mappedInput);
      screen.target().text(fui::Rect{static_cast<int16_t>(touch.x), static_cast<int16_t>(touch.y),
                                     static_cast<int16_t>(touch.width), static_cast<int16_t>(touch.height)},
                           sortMode == SortMode::DATE_DESC ? "D v" : "SRC", sortStyle);
    }
    screen.takeTop(static_cast<int16_t>(headerRect.height));
  } else {
    fui::HeaderProps header;
    header.title = sortMode == SortMode::DATE_DESC ? "RSS - date" : "RSS - source";
    header.borderEdges = fui::EdgeBottom;
    screen.header(header);
  }
  screen.spacer(static_cast<int16_t>(UITheme::getInstance().getMetrics().verticalSpacing));
}

void RssNewsActivity::buildListScreen(UiApp::ScreenType& screen) {
  screenHeader(screen);
  if (!listItems || !displayOrder) {
    screen.centeredText(tr(STR_MEMORY_ERROR), screen.theme().bodyText);
    return;
  }

  listItems[0] = fui::ListItem{};
  listItems[0].label = tr(STR_UPDATE);
  listItems[0].value = "RSS";
  listItems[0].actionValue = 0;

  for (size_t i = 0; i < articleCount; ++i) {
    const size_t articleIndex = articleIndexForDisplayRow(i);
    if (articleIndex >= articleCount) continue;
    const CachedArticle& article = articles[articleIndex];
    fui::ListItem& item = listItems[i + 1];
    item = fui::ListItem{};
    item.label = article.item.title;
    item.subtitle = article.item.published[0] ? article.item.published : nullptr;
    item.value = SOURCES[article.sourceIndex].name;
    item.actionValue = static_cast<int16_t>(i + 1);
  }

  fui::ListProps props;
  props.items = listItems;
  props.count = static_cast<uint16_t>(articleCount + 1);
  props.selectedIndex = static_cast<int16_t>(selectorIndex);
  props.action = ACTION_ROW;
  props.inputMask = fui::InputTouch;
  props.valueInset = 8;
  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);
  visibleRows = rows > 0 ? rows : 1;
  topIndex = scrollListBy(topIndex, 0, visibleRows, static_cast<int>(articleCount + 1));
  props.topIndex = static_cast<uint16_t>(topIndex);
  screen.list(props);
}

void RssNewsActivity::buildArticleScreen(UiApp::ScreenType& screen) {
  screenHeader(screen);
  if (openArticleIndex >= articleCount) {
    screen.centeredText(tr(STR_NO_ENTRIES), screen.theme().bodyText);
    return;
  }

  const CachedArticle& article = articles[openArticleIndex];
  const auto& theme = screen.theme();
  fui::TextStyle titleStyle = theme.bodyText;
  fui::TextStyle bodyStyle = theme.bodyText;
  fui::TextStyle metaStyle = theme.smallText;
  const int16_t titleHeight = screen.target().lineHeight(titleStyle.font);
  const int16_t bodyHeight = screen.target().lineHeight(bodyStyle.font);
  const int16_t metaHeight = screen.target().lineHeight(metaStyle.font);

  for (const auto& line : articleTitleLines) {
    if (screen.body().height < titleHeight) break;
    screen.target().text(screen.takeTop(titleHeight, theme.spaceXs), line.c_str(), titleStyle);
  }
  screen.spacer(theme.spaceSm);
  if (screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceSm), SOURCES[article.sourceIndex].name, metaStyle);
  }
  if (article.item.published[0] && screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceMd), article.item.published, metaStyle);
  }

  if (articleSummaryLines.empty()) {
    screen.centeredText(tr(STR_NO_ENTRIES), bodyStyle);
    return;
  }

  for (size_t i = articleLineOffset; i < articleSummaryLines.size(); ++i) {
    if (screen.body().height < bodyHeight) break;
    screen.target().text(screen.takeTop(bodyHeight, theme.spaceXs), articleSummaryLines[i].c_str(), bodyStyle);
  }
}

void RssNewsActivity::buildStatusScreen(UiApp::ScreenType& screen) {
  screenHeader(screen);
  fui::TextStyle centered = screen.theme().bodyText;
  centered.align = fui::TextAlign::Center;
  const int16_t lineHeight = screen.target().lineHeight(centered.font);
  const fui::Rect body = screen.body();
  if (body.height > lineHeight * 2 + screen.theme().spaceMd) {
    screen.spacer(static_cast<int16_t>((body.height - lineHeight * 2 - screen.theme().spaceMd) / 2));
  }
  screen.target().text(screen.takeTop(lineHeight, screen.theme().spaceMd), tr(STR_LOADING), centered);
  if (!statusMessage.empty()) screen.target().text(screen.takeTop(lineHeight), statusMessage.c_str(), centered);
}

void RssNewsActivity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<RssNewsActivity*>(user);
  if (self->state != State::LIST) return;
  if (event.value < 0 || event.value > static_cast<int16_t>(self->articleCount)) return;
  self->selectorIndex = event.value;
  self->app.clearTapFlash();
  self->activateSelected();
}

void RssNewsActivity::activateSelected() {
  if (selectorIndex == 0) {
    requestManualRefresh();
    return;
  }
  const size_t displayRow = static_cast<size_t>(selectorIndex - 1);
  const size_t articleIndex = articleIndexForDisplayRow(displayRow);
  if (articleIndex < articleCount) openArticle(articleIndex);
}

void RssNewsActivity::openArticle(const size_t articleIndex) {
  if (!articles || articleIndex >= articleCount) return;
  openArticleIndex = articleIndex;
  const CachedArticle& article = articles[articleIndex];

  const int margin = UITheme::getInstance().getMetrics().contentSidePadding;
  const int maxWidth = std::max(80, renderer.getScreenWidth() - margin * 2);
  const auto scale = uiScaleSpec();
  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);
  articleSummaryLines = renderer.wrappedText(scale.bodyFontId, article.item.summary, maxWidth, 320);
  articleLineOffset = 0;
  state = State::ARTICLE;
  requestUpdate();
}

void RssNewsActivity::closeArticle() {
  articleTitleLines.clear();
  articleSummaryLines.clear();
  articleLineOffset = 0;
  openArticleIndex = MAX_ARTICLES;
  state = State::LIST;
  requestUpdate();
}

void RssNewsActivity::scrollArticle(const int deltaLines) {
  if (articleSummaryLines.empty()) return;
  const size_t oldOffset = articleLineOffset;
  if (deltaLines > 0) {
    articleLineOffset = std::min(articleSummaryLines.size() - 1, articleLineOffset + static_cast<size_t>(deltaLines));
  } else if (deltaLines < 0) {
    const size_t amount = static_cast<size_t>(-deltaLines);
    articleLineOffset = amount > articleLineOffset ? 0 : articleLineOffset - amount;
  }
  if (articleLineOffset != oldOffset) requestUpdate();
}

void RssNewsActivity::requestManualRefresh() {
  if (!ensureBuffers()) {
    statusMessage = tr(STR_MEMORY_ERROR);
    requestUpdate();
    return;
  }

#ifdef SIMULATOR
  seedSimulatorArticles();
  rebuildDisplayOrder();
  saveCache();
  selectorIndex = 0;
  topIndex = 0;
  state = State::LIST;
  requestUpdate();
  return;
#else
  if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0)) {
    refreshFeeds();
  } else {
    launchWifiSelection();
  }
#endif
}

void RssNewsActivity::launchWifiSelection() {
  state = State::WIFI_SELECTION;
  statusMessage = tr(STR_CHECKING_WIFI);
  requestUpdate();
  startActivityForResult(std::make_unique<WifiSelectionActivity>(renderer, mappedInput),
                         [this](const ActivityResult& result) { onWifiSelectionComplete(!result.isCancelled); });
}

void RssNewsActivity::onWifiSelectionComplete(const bool connected) {
  if (connected) {
    refreshFeeds();
  } else {
    state = State::LIST;
    refreshHadError = true;
    requestUpdate();
  }
}

bool RssNewsActivity::fetchSource(const uint8_t sourceIndex, size_t& outCount, bool& cancelled) {
  outCount = 0;
  if (!feedItems || sourceIndex >= SOURCE_COUNT) return false;
  std::memset(feedItems, 0, sizeof(RssItem) * FEED_ITEM_CAPACITY);

  RssParser parser(feedItems, FEED_ITEM_CAPACITY);
  HttpDownloader::DownloadOptions options;
  options.bufferSize = HTTP_BUFFER_SIZE;
  options.transport = HttpDownloader::Transport::WOLFSSL;
  options.shouldCancel = [this, &cancelled]() {
    mappedInput.update();
    if (mappedInput.wasHomeGesture()) {
      goHomeAfterRefreshCancel = true;
      cancelled = true;
    }
    if (mappedInput.isPressed(MappedInputManager::Button::Back) ||
        mappedInput.wasPressed(MappedInputManager::Button::Back) ||
        mappedInput.wasReleased(MappedInputManager::Button::Back)) {
      cancelled = true;
    }
    return cancelled;
  };

  const auto result = HttpDownloader::streamUrl(
      SOURCES[sourceIndex].url,
      [&parser](const uint8_t* data, const size_t len) { return parser.write(data, len) == len; }, nullptr, "", "",
      std::move(options));
  if (result == HttpDownloader::ABORTED) {
    cancelled = true;
    return false;
  }
  if (result != HttpDownloader::OK) {
    LOG_ERR("RSS", "Fetch failed for %s", SOURCES[sourceIndex].name);
    return false;
  }
  parser.flush();
  if (!parser) {
    LOG_ERR("RSS", "Parse failed for %s", SOURCES[sourceIndex].name);
    return false;
  }
  outCount = parser.getItemCount();
  if (parser.wasTruncated()) LOG_DBG("RSS", "%s feed truncated to %zu items", SOURCES[sourceIndex].name, outCount);
  return outCount > 0;
}

void RssNewsActivity::refreshFeeds() {
  usedNetwork = true;
  refreshHadError = false;
  goHomeAfterRefreshCancel = false;
  state = State::REFRESHING;
  statusMessage = SOURCES[0].name;
  if (requestUpdateAndWait() != RequestUpdateResult::Rendered) requestUpdate(true);

  size_t successfulSources = 0;
  bool cancelled = false;
  for (uint8_t sourceIndex = 0; sourceIndex < SOURCE_COUNT; ++sourceIndex) {
    statusMessage = SOURCES[sourceIndex].name;
    requestUpdate(true);

    size_t fetchedCount = 0;
    if (fetchSource(sourceIndex, fetchedCount, cancelled)) {
      mergeSourceArticles(sourceIndex, feedItems, fetchedCount);
      ++successfulSources;
    } else if (!cancelled) {
      refreshHadError = true;
    }
    if (cancelled) break;
  }

  if (cancelled) {
    if (goHomeAfterRefreshCancel) {
      onGoHome();
      return;
    }
    mappedInput.suppressNextBackRelease();
    rebuildDisplayOrder();
    state = State::LIST;
    requestUpdate();
    return;
  }

  rebuildDisplayOrder();
  if (successfulSources > 0 && !saveCache()) {
    LOG_ERR("RSS", "Could not persist refreshed cache");
    refreshHadError = true;
  }
  selectorIndex = 0;
  topIndex = 0;
  state = State::LIST;
  requestUpdate();
}

void RssNewsActivity::seedSimulatorArticles() {
  if (!articles) return;
  articleCount = 0;
  for (uint8_t sourceIndex = 0; sourceIndex < SOURCE_COUNT; ++sourceIndex) {
    for (size_t sample = 0; sample < 3; ++sample) {
      CachedArticle& article = articles[articleCount++];
      article = CachedArticle{};
      article.sourceIndex = sourceIndex;
      snprintf(article.item.title, sizeof(article.item.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),
               SOURCES[sourceIndex].name);
      snprintf(article.item.summary, sizeof(article.item.summary),
               "Contenu hors ligne de demonstration pour verifier le cache SD, le tactile et la pagination de lecture.");
      snprintf(article.item.published, sizeof(article.item.published), "2026-09-%02uT12:00:00Z",
               static_cast<unsigned>(8 - sample));
    }
  }
}

void RssNewsActivity::loop() {
  if (state == State::WIFI_SELECTION || state == State::REFRESHING) return;

  if (TouchHeaderBackButton::wasTapped(mappedInput, renderer)) {
    state == State::ARTICLE ? closeArticle() : onGoHome();
    return;
  }

  if (state == State::LIST && mappedInput.hasTouchHardware()) {
    const Rect sortRect = sortTouchRect(renderer, mappedInput);
    if (mappedInput.wasTapInRect(sortRect.x, sortRect.y, sortRect.width, sortRect.height)) {
      toggleSortMode();
      return;
    }
  }

  if (state == State::ARTICLE) {
    if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
      closeArticle();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Down) ||
        mappedInput.wasReleased(MappedInputManager::Button::Right)) {
      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Up) ||
        mappedInput.wasReleased(MappedInputManager::Button::Left)) {
      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));
      return;
    }
    const auto swipe = mappedInput.wasSwipe();
    if (swipe == MappedInputManager::SwipeDir::Up) {
      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));
    } else if (swipe == MappedInputManager::SwipeDir::Down) {
      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));
    }
    return;
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    activateSelected();
    return;
  }
  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
    onGoHome();
    return;
  }
  if (mappedInput.wasReleased(MappedInputManager::Button::Left)) {
    requestManualRefresh();
    return;
  }

  if (uiReady) {
    const fui::InputSnapshot snap = touchSnapshotFrom(mappedInput);
    if (snap.touchPressed || snap.touchReleased) {
      const auto event = app.route(snap);
      if (app.invalidated()) requestUpdate();
      if (event || state != State::LIST) return;
    }
  }

  const int itemCount = static_cast<int>(articleCount + 1);
  if (itemCount <= 0) return;

  const auto swipe = mappedInput.wasSwipe();
  if (swipe == MappedInputManager::SwipeDir::Up || swipe == MappedInputManager::SwipeDir::Down) {
    const int delta = swipe == MappedInputManager::SwipeDir::Up ? visibleRows : -visibleRows;
    const int next = scrollListBy(topIndex, delta, visibleRows, itemCount);
    if (next != topIndex) {
      topIndex = next;
      requestUpdate();
    }
    return;
  }

  const auto moveSelection = [this, itemCount](const int index) {
    selectorIndex = index;
    topIndex = followListSelection(selectorIndex, topIndex, visibleRows, itemCount);
    requestUpdate();
  };
  buttonNavigator.onNextRelease([this, itemCount, &moveSelection] {
    moveSelection(ButtonNavigator::nextIndex(selectorIndex, itemCount));
  });
  buttonNavigator.onPreviousRelease([this, itemCount, &moveSelection] {
    moveSelection(ButtonNavigator::previousIndex(selectorIndex, itemCount));
  });
  buttonNavigator.onNextContinuous([this, itemCount, &moveSelection] {
    moveSelection(ButtonNavigator::nextPageIndex(selectorIndex, itemCount, visibleRows));
  });
  buttonNavigator.onPreviousContinuous([this, itemCount, &moveSelection] {
    moveSelection(ButtonNavigator::previousPageIndex(selectorIndex, itemCount, visibleRows));
  });
}

bool RssNewsActivity::preventAutoSleep() {
  return state == State::WIFI_SELECTION || state == State::REFRESHING;
}

void RssNewsActivity::render(RenderLock&&) {
  renderer.clearScreen();

  MappedInputManager::Labels labels;
  switch (state) {
    case State::LIST:
      labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_OPEN), tr(STR_UPDATE), tr(STR_DIR_DOWN));
      break;
    case State::ARTICLE:
      labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", tr(STR_DIR_UP), tr(STR_DIR_DOWN));
      break;
    case State::WIFI_SELECTION:
    case State::REFRESHING:
      labels = mappedInput.mapLabels(tr(STR_CANCEL), "", "", "");
      break;
  }
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);

  uiReady = false;
  app.render();
  uiReady = true;
  renderer.displayBuffer(screenTransitionRefresh.modeFor(static_cast<uint8_t>(state)));
}
