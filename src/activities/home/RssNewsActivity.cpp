#include "RssNewsActivity.h"

#include <Arduino.h>
#include <FontCacheManager.h>
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

#include "CrossPointSettings.h"
#include "MappedInputManager.h"
#include "RssArticleCache.h"
#include "RssArticleRichText.h"
#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"
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
constexpr int SORT_TOUCH_WIDTH = 72;

struct CacheHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t count;
  uint32_t sourceHash;
};

HeapByteBuffer allocateRssBuffer(const size_t bytes) {
  auto buffer = makePsramByteBufferNoThrow(bytes);
  if (!buffer) buffer = makeHeapByteBufferNoThrow(bytes);
  return buffer;
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

std::string trimFeedField(std::string value) {
  const auto notSpace = [](const unsigned char c) { return !std::isspace(c); };
  const auto first = std::find_if(value.begin(), value.end(), notSpace);
  if (first == value.end()) return {};
  const auto last = std::find_if(value.rbegin(), value.rend(), notSpace).base();
  return std::string(first, last);
}

uint16_t parseFeedLimit(const std::string& value, const uint16_t fallback, const uint16_t maximum) {
  unsigned parsed = 0;
  char extra = '\0';
  if (std::sscanf(value.c_str(), "%u%c", &parsed, &extra) != 1 || parsed < 1 || parsed > maximum) return fallback;
  return static_cast<uint16_t>(parsed);
}

bool formatPublishedDate(const char* value, char* out, const size_t outSize) {
  if (!out || outSize == 0) return false;
  out[0] = '\0';
  if (!value || !value[0]) return false;

  int year = 0;
  int month = 0;
  int day = 0;
  if (std::sscanf(value, "%4d-%2d-%2d", &year, &month, &day) == 3) {
    if (year >= 1970 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      std::snprintf(out, outSize, "%02d/%02d/%04d", day, month, year);
      return true;
    }
  }

  char monthText[4] = {};
  int matched = std::sscanf(value, "%*3s, %2d %3s %4d", &day, monthText, &year);
  if (matched < 3) matched = std::sscanf(value, "%2d %3s %4d", &day, monthText, &year);
  if (matched >= 3) {
    month = monthNumber(monthText);
    if (year >= 1970 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      std::snprintf(out, outSize, "%02d/%02d/%04d", day, month, year);
      return true;
    }
  }
  return false;
}

Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {
  const Rect header = TouchHeaderBackButton::headerRect(renderer, input);
  return Rect{header.x + header.width - SORT_TOUCH_WIDTH, header.y, SORT_TOUCH_WIDTH, header.height};
}

uint8_t estimateReadingMinutes(const RssItem& item) {
  std::string cachedText;
  const auto result = RssArticleCache::load(item, cachedText);
  if (result != RssArticleCache::CacheResult::READY &&
      result != RssArticleCache::CacheResult::FALLBACK_READY) {
    return 0;
  }
  const std::string visibleText = RssArticleRichText::visibleText(cachedText);
  return RssArticleMetadata::readingMinutesForText(visibleText.c_str(), visibleText.size());
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
  articlePageLines = 8;
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

  loadSources();
  if (!ensureBuffers()) {
    statusMessage = tr(STR_MEMORY_ERROR);
  } else {
    loadCache();
    rebuildDisplayOrder();
  }
  requestUpdate();
}

void RssNewsActivity::onExit() {
  // The first RSS article render can lazily allocate FontDecompressor's
  // grow-only compressed-font hot-group buffer. It is fully rebuildable but,
  // if left resident after RSS exits, a ~12 KB allocation can split the large
  // contiguous PSRAM arena. On this branch FontCacheManager::clearCache()
  // clears FontDecompressor first and then the registered SD-font caches.
  if (auto* fcm = renderer.getFontCacheManager()) {
    fcm->clearCache();
  }
  sdFontSystem.releaseRegistry();

  Activity::onExit();
  uiReady = false;
  articleTitleLines.clear();
  articleSummaryLines.clear();
  displayOrder = nullptr;
  listMetaText = nullptr;
  listItems = nullptr;
  feedItems = nullptr;
  articles = nullptr;
  displayOrderStorage.reset();
  listMetaStorage.reset();
  listItemStorage.reset();
  feedStorage.reset();
  articleStorage.reset();

#ifndef SIMULATOR
  if (usedNetwork || WiFi.getMode() != WIFI_MODE_NULL) {
    if (WiFi.getMode() != WIFI_MODE_NULL) {
      WiFi.disconnect(false);
      delay(30);
    }
    // Keep the post-WiFi reboot that defragments the ESP network heap and
    // resume at the normal Home screen, like native applications.
    silentRestartAfterNetwork();
  }
#endif
}

bool RssNewsActivity::ensureBuffers() {
  size_t requestedArticleCapacity = 0;
  size_t requestedFeedCapacity = 1;
  for (size_t i = 0; i < sourceCount; ++i) {
    requestedArticleCapacity += std::clamp<size_t>(sources[i].historyLimit, 1, ITEMS_PER_SOURCE);
    requestedFeedCapacity = std::max(
        requestedFeedCapacity, std::clamp<size_t>(sources[i].syncLimit, 1, FEED_ITEM_CAPACITY));
  }
  articleCapacity = std::clamp<size_t>(requestedArticleCapacity, 1, MAX_ARTICLES);
  feedItemCapacity = std::clamp<size_t>(requestedFeedCapacity, 1, FEED_ITEM_CAPACITY);

  if (!articleStorage) {
    articleStorage = allocateRssBuffer(sizeof(CachedArticle) * articleCapacity);
    if (!articleStorage) {
      LOG_ERR("RSS", "OOM allocating article metadata (%zu records)", articleCapacity);
      return false;
    }
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
    std::memset(articles, 0, sizeof(CachedArticle) * articleCapacity);
  } else if (!articles) {
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
  }

  if (!listItemStorage) {
    listItemStorage = allocateRssBuffer(sizeof(fui::ListItem) * (articleCapacity + 1));
    if (!listItemStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list items");
      return false;
    }
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
    std::memset(listItems, 0, sizeof(fui::ListItem) * (articleCapacity + 1));
  } else if (!listItems) {
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
  }

  if (!listMetaStorage) {
    listMetaStorage = allocateRssBuffer(articleCapacity * LIST_META_CAPACITY);
    if (!listMetaStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list metadata");
      return false;
    }
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
    std::memset(listMetaText, 0, articleCapacity * LIST_META_CAPACITY);
  } else if (!listMetaText) {
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
  }

  if (!displayOrderStorage) {
    displayOrderStorage = allocateRssBuffer(sizeof(uint16_t) * articleCapacity);
    if (!displayOrderStorage) {
      LOG_ERR("RSS", "OOM allocating RSS sort index");
      return false;
    }
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
    std::memset(displayOrder, 0, sizeof(uint16_t) * articleCapacity);
  } else if (!displayOrder) {
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
  }

  const size_t residentBytes = sizeof(CachedArticle) * articleCapacity +
                               sizeof(fui::ListItem) * (articleCapacity + 1) +
                               articleCapacity * LIST_META_CAPACITY +
                               sizeof(uint16_t) * articleCapacity;
  LOG_DBG("RSS", "Memory model: RssItem=%zu history=%zu ListItem=%zu resident=%zu feedScratch=%zu",
          sizeof(RssItem), sizeof(CachedArticle), sizeof(fui::ListItem), residentBytes,
          sizeof(RssItem) * feedItemCapacity);
  return true;
}

bool RssNewsActivity::ensureFeedBuffer() {
  if (feedStorage) {
    if (!feedItems) feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
    return feedItems != nullptr;
  }
  feedStorage = allocateRssBuffer(sizeof(RssItem) * feedItemCapacity);
  if (!feedStorage) {
    LOG_ERR("RSS", "OOM allocating transient feed scratch (%zu records)", feedItemCapacity);
    return false;
  }
  feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
  std::memset(feedItems, 0, sizeof(RssItem) * feedItemCapacity);
  return true;
}

void RssNewsActivity::releaseFeedBuffer() {
  feedItems = nullptr;
  feedStorage.reset();
}

void RssNewsActivity::loadSources() {
  sourceCount = 0;
  for (const auto& source : DEFAULT_SOURCES) {
    if (sourceCount >= MAX_SOURCES) break;
    sources[sourceCount++] = Source{source.name, source.url, source.syncLimit, source.historyLimit, {}, {}, {}};
  }

  if (!ensureFeedConfigFile()) {
    LOG_ERR("RSS", "Could not create/open %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  FsFile file;
  if (!Storage.openFileForRead("RSS", FEEDS_PATH, file)) {
    LOG_ERR("RSS", "Could not read %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  const size_t bytes = std::min(static_cast<size_t>(file.size()), FEED_CONFIG_MAX_BYTES);
  std::array<char, FEED_CONFIG_MAX_BYTES + 1> buffer{};
  const int read = bytes > 0 ? file.read(buffer.data(), bytes) : 0;
  file.close();
  if (read <= 0) {
    LOG_ERR("RSS", "Empty RSS feed configuration; using built-in feeds");
    return;
  }

  const char* const configBegin = buffer.data();
  const char* const configEnd = configBegin + static_cast<size_t>(read);

  const auto trimRange = [](const char*& begin, const char*& end) {
    while (begin < end && std::isspace(static_cast<unsigned char>(*begin))) ++begin;
    while (end > begin && std::isspace(static_cast<unsigned char>(end[-1]))) --end;
  };
  const auto rangeEquals = [](const char* begin, const char* end, const char* literal) {
    const size_t length = static_cast<size_t>(end - begin);
    const size_t literalLength = std::strlen(literal);
    return length == literalLength && std::memcmp(begin, literal, length) == 0;
  };
  const auto rangeStartsWith = [](const char* begin, const char* end, const char* literal) {
    const size_t length = static_cast<size_t>(end - begin);
    const size_t literalLength = std::strlen(literal);
    return length >= literalLength && std::memcmp(begin, literal, literalLength) == 0;
  };
  const auto parseLimit = [](const char* begin, const char* end, const uint16_t fallback,
                             const uint16_t maximum) {
    if (begin >= end) return fallback;
    if (*begin == '+') ++begin;
    if (begin >= end) return fallback;
    unsigned value = 0;
    for (const char* cursor = begin; cursor < end; ++cursor) {
      if (*cursor < '0' || *cursor > '9') return fallback;
      value = value * 10U + static_cast<unsigned>(*cursor - '0');
      if (value > maximum) return fallback;
    }
    return value >= 1U ? static_cast<uint16_t>(value) : fallback;
  };

  size_t parsedCount = 0;
  const char* lineBegin = configBegin;
  while (lineBegin < configEnd && parsedCount < MAX_SOURCES) {
    const char* lineEnd = lineBegin;
    while (lineEnd < configEnd && *lineEnd != '\n') ++lineEnd;

    const char* begin = lineBegin;
    const char* end = lineEnd;
    trimRange(begin, end);
    if (begin < end && *begin != '#') {
      const char* firstSeparator = begin;
      while (firstSeparator < end && *firstSeparator != '|') ++firstSeparator;
      if (firstSeparator < end) {
        const char* secondSeparator = firstSeparator + 1;
        while (secondSeparator < end && *secondSeparator != '|') ++secondSeparator;

        const char* nameBegin = begin;
        const char* nameEnd = firstSeparator;
        const char* urlBegin = firstSeparator + 1;
        const char* urlEnd = secondSeparator;
        trimRange(nameBegin, nameEnd);
        trimRange(urlBegin, urlEnd);

        uint16_t syncLimit = DEFAULT_SYNC_LIMIT;
        uint16_t historyLimit = DEFAULT_HISTORY_LIMIT;
        const char* dropBegin = nullptr;
        const char* dropEnd = nullptr;
        const char* dropStartBegin = nullptr;
        const char* dropStartEnd = nullptr;
        const char* stopBegin = nullptr;
        const char* stopEnd = nullptr;

        const char* parameterBegin = secondSeparator < end ? secondSeparator + 1 : end;
        while (parameterBegin < end) {
          const char* parameterEnd = parameterBegin;
          while (parameterEnd < end && *parameterEnd != '|') ++parameterEnd;
          const char* fieldBegin = parameterBegin;
          const char* fieldEnd = parameterEnd;
          trimRange(fieldBegin, fieldEnd);
          const char* equals = fieldBegin;
          while (equals < fieldEnd && *equals != '=') ++equals;
          if (equals < fieldEnd) {
            const char* keyBegin = fieldBegin;
            const char* keyEnd = equals;
            const char* valueBegin = equals + 1;
            const char* valueEnd = fieldEnd;
            trimRange(keyBegin, keyEnd);
            trimRange(valueBegin, valueEnd);

            if (rangeEquals(keyBegin, keyEnd, "sync")) {
              syncLimit = parseLimit(valueBegin, valueEnd, DEFAULT_SYNC_LIMIT,
                                     static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (rangeEquals(keyBegin, keyEnd, "history")) {
              historyLimit = parseLimit(valueBegin, valueEnd, DEFAULT_HISTORY_LIMIT,
                                        static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (rangeEquals(keyBegin, keyEnd, "drop")) {
              dropBegin = valueBegin;
              dropEnd = valueEnd;
            } else if (rangeEquals(keyBegin, keyEnd, "dropstart")) {
              dropStartBegin = valueBegin;
              dropStartEnd = valueEnd;
            } else if (rangeEquals(keyBegin, keyEnd, "stop")) {
              stopBegin = valueBegin;
              stopEnd = valueEnd;
            }
          }
          parameterBegin = parameterEnd < end ? parameterEnd + 1 : end;
        }

        const bool supportedUrl = rangeStartsWith(urlBegin, urlEnd, "https://") ||
                                  rangeStartsWith(urlBegin, urlEnd, "http://");
        if (nameBegin < nameEnd && supportedUrl) {
          Source& target = sources[parsedCount++];
          target.name.assign(nameBegin, static_cast<size_t>(nameEnd - nameBegin));
          target.url.assign(urlBegin, static_cast<size_t>(urlEnd - urlBegin));
          target.syncLimit = syncLimit;
          target.historyLimit = historyLimit;
          if (dropBegin) target.dropRules.assign(dropBegin, static_cast<size_t>(dropEnd - dropBegin));
          else target.dropRules.clear();
          if (dropStartBegin) target.dropStartRules.assign(dropStartBegin, static_cast<size_t>(dropStartEnd - dropStartBegin));
          else target.dropStartRules.clear();
          if (stopBegin) target.stopRules.assign(stopBegin, static_cast<size_t>(stopEnd - stopBegin));
          else target.stopRules.clear();
        } else {
          LOG_ERR("RSS", "Ignoring invalid feed line");
        }
      } else {
        LOG_ERR("RSS", "Ignoring feed line without '|'");
      }
    }
    lineBegin = lineEnd < configEnd ? lineEnd + 1 : configEnd;
  }

  if (parsedCount == 0) {
    LOG_ERR("RSS", "No valid feeds in %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  for (size_t i = parsedCount; i < MAX_SOURCES; ++i) sources[i] = Source{};
  sourceCount = parsedCount;
  LOG_DBG("RSS", "Loaded %zu feeds from %s", sourceCount, FEEDS_PATH);
}

bool RssNewsActivity::ensureFeedConfigFile() {
  Storage.ensureDirectoryExists(FEEDS_DIR);
  if (Storage.exists(FEEDS_PATH)) return true;

  std::string content;
  content.reserve(768);
  content += "# CrossInk RSS feeds\n";
  content += "# Name|URL|sync=30|history=100|drop=...|dropstart=...|stop=...\n";
  content += "# Rules are optional and separated with ';'. Maximum: 8 feeds.\n";
  for (const auto& source : DEFAULT_SOURCES) {
    content += source.name;
    content += '|';
    content += source.url;
    content += "|sync=";
    content += std::to_string(source.syncLimit);
    content += "|history=";
    content += std::to_string(source.historyLimit);
    content += '\n';
  }

  FsFile file;
  if (!Storage.openFileForWrite("RSS", FEEDS_PATH, file)) return false;
  const size_t written = file.write(reinterpret_cast<const uint8_t*>(content.data()), content.size());
  const bool synced = written == content.size() && file.sync();
  file.close();
  if (!synced) {
    Storage.remove(FEEDS_PATH);
    return false;
  }
  return true;
}

uint32_t RssNewsActivity::sourceConfigHash() const {
  uint32_t hash = UINT32_C(2166136261);
  const auto mix = [&hash](const char c) {
    hash ^= static_cast<uint8_t>(c);
    hash *= UINT32_C(16777619);
  };
  const auto mixLimit = [&mix](const uint16_t value) {
    mix(static_cast<char>(value & 0xffU));
    mix(static_cast<char>((value >> 8U) & 0xffU));
  };
  for (size_t i = 0; i < sourceCount; ++i) {
    for (const char c : sources[i].name) mix(c);
    mix('|');
    for (const char c : sources[i].url) mix(c);
    mix('|');
    mixLimit(sources[i].syncLimit);
    mix('|');
    mixLimit(sources[i].historyLimit);
    mix('|');
    for (const char c : sources[i].dropRules) mix(c);
    mix('|');
    for (const char c : sources[i].dropStartRules) mix(c);
    mix('|');
    for (const char c : sources[i].stopRules) mix(c);
    mix('\n');
  }
  return hash;
}

bool RssNewsActivity::loadCache() {
  articleCount = 0;
  if (!articles || !Storage.exists(CACHE_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", CACHE_PATH, file)) return false;

  CacheHeader header{};
  const bool headerOk = file.read(&header, sizeof(header)) == static_cast<int>(sizeof(header));
  const bool layoutOk = headerOk && header.magic == CACHE_MAGIC && header.version == CACHE_VERSION &&
                        header.count <= MAX_ARTICLES;
  if (!layoutOk) {
    LOG_ERR("RSS", "Ignoring incompatible RSS cache; refresh will rebuild it");
    file.close();
    return false;
  }

  if (header.sourceHash != sourceConfigHash()) {
    // The source indexes in this cache belong to the previous feeds.txt. Purge
    // their dedicated bodies before discarding metadata so removed/reordered
    // sources cannot leave permanent SD orphans.
    for (uint16_t i = 0; i < header.count; ++i) {
      CachedArticle stale{};
      if (file.read(&stale, sizeof(stale)) != static_cast<int>(sizeof(stale))) break;
      RssArticleCache::remove({stale.link, stale.title, stale.published});
    }
    file.close();
    Storage.remove(CACHE_PATH);
    LOG_DBG("RSS", "Purged article bodies for obsolete feed configuration");
    return false;
  }

  if (header.count > articleCapacity) {
    LOG_ERR("RSS", "RSS cache exceeds configured capacity (%u > %zu)",
            static_cast<unsigned>(header.count), articleCapacity);
    file.close();
    Storage.remove(CACHE_PATH);
    return false;
  }

  for (uint16_t i = 0; i < header.count; ++i) {
    CachedArticle article{};
    if (file.read(&article, sizeof(article)) != static_cast<int>(sizeof(article)) || article.sourceIndex >= sourceCount) {
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
  const CacheHeader header{CACHE_MAGIC, CACHE_VERSION, static_cast<uint16_t>(articleCount), sourceConfigHash()};
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

bool RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {
  if (!articles || !items || sourceIndex >= sourceCount) return false;

  const size_t historyLimit = std::clamp<size_t>(sources[sourceIndex].historyLimit, 1, ITEMS_PER_SOURCE);
  auto mergeStorage = allocateRssBuffer(sizeof(CachedArticle) * historyLimit);
  if (!mergeStorage) {
    LOG_ERR("RSS", "OOM allocating lightweight merge scratch (%zu records)", historyLimit);
    return false;
  }
  auto* merged = reinterpret_cast<CachedArticle*>(mergeStorage.get());
  std::memset(merged, 0, sizeof(CachedArticle) * historyLimit);

  const auto identity = [](const CachedArticle& article) {
    return RssArticleCache::ArticleIdentity{article.link, article.title, article.published};
  };

  size_t mergedCount = 0;
  const size_t incomingCount = std::min(count, historyLimit);
  for (size_t i = 0; i < incomingCount; ++i) {
    if (!RssArticleCache::hasReadableBody(items[i])) continue;
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (RssArticleMetadata::same(merged[j], items[i])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) {
      merged[mergedCount++] =
          RssArticleMetadata::fromItem(sourceIndex, items[i], estimateReadingMinutes(items[i]));
    }
  }

  for (size_t i = 0; i < articleCount && mergedCount < historyLimit; ++i) {
    if (articles[i].sourceIndex != sourceIndex || !RssArticleCache::hasReadableBody(identity(articles[i]))) continue;
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (RssArticleMetadata::same(articles[i], merged[j])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) merged[mergedCount++] = articles[i];
  }

  // Delete body/fallback files that just fell out of this source's configured
  // history. A shared URL is kept while another source still references it.
  for (size_t i = 0; i < articleCount; ++i) {
    if (articles[i].sourceIndex != sourceIndex) continue;
    bool retained = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (RssArticleMetadata::same(articles[i], merged[j])) {
        retained = true;
        break;
      }
    }
    if (retained) continue;

    bool referencedElsewhere = false;
    for (size_t j = 0; j < articleCount; ++j) {
      if (j == i || articles[j].sourceIndex == sourceIndex) continue;
      if (RssArticleMetadata::same(articles[i], articles[j])) {
        referencedElsewhere = true;
        break;
      }
    }
    if (!referencedElsewhere) RssArticleCache::remove(identity(articles[i]));
  }

  size_t writeIndex = 0;
  for (size_t readIndex = 0; readIndex < articleCount; ++readIndex) {
    if (articles[readIndex].sourceIndex == sourceIndex) continue;
    if (writeIndex != readIndex) articles[writeIndex] = articles[readIndex];
    ++writeIndex;
  }
  articleCount = writeIndex;

  const size_t addCount = articleCount < articleCapacity
                              ? std::min(mergedCount, articleCapacity - articleCount)
                              : 0;
  for (size_t i = 0; i < addCount; ++i) articles[articleCount++] = merged[i];
  return true;
}

void RssNewsActivity::rebuildDisplayOrder() {
  if (!displayOrder || !articles) return;
  for (size_t i = 0; i < articleCount; ++i) displayOrder[i] = static_cast<uint16_t>(i);

  std::stable_sort(displayOrder, displayOrder + articleCount, [this](const uint16_t leftIndex, const uint16_t rightIndex) {
    const CachedArticle& left = articles[leftIndex];
    const CachedArticle& right = articles[rightIndex];
    if (sortMode == SortMode::SOURCE && left.sourceIndex != right.sourceIndex) return left.sourceIndex < right.sourceIndex;

    const int64_t leftDate = publishedDateKey(left.published);
    const int64_t rightDate = publishedDateKey(right.published);
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
      const auto headerLayout = TouchHeaderBackButton::layout(headerRect);
      const int iconBottom = headerLayout.iconRect.y +
                             (headerLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2;
      const int availableOffset = std::max(0, headerRect.y + headerRect.height - iconBottom);
      const int titleOffset = std::clamp(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET, 0, availableOffset);
      const auto scale = uiScaleSpec();
      const int titleBaselineY =
          headerLayout.iconRect.y + titleOffset +
          std::max(0, (headerLayout.iconRect.height - renderer.getLineHeight(scale.titleFontId)) / 2) +
          renderer.getFontAscenderSize(scale.titleFontId);
      const int sortLineHeight = renderer.getLineHeight(scale.smallFontId);
      const int sortTop = titleBaselineY - renderer.getFontAscenderSize(scale.smallFontId);
      screen.target().text(fui::Rect{static_cast<int16_t>(touch.x), static_cast<int16_t>(sortTop),
                                     static_cast<int16_t>(touch.width), static_cast<int16_t>(sortLineHeight)},
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
  listItems[0].subtitle = nullptr;
  listItems[0].value = nullptr;
  listItems[0].actionValue = 0;

  for (size_t i = 0; i < articleCount; ++i) {
    const size_t articleIndex = articleIndexForDisplayRow(i);
    if (articleIndex >= articleCount) continue;
    const CachedArticle& article = articles[articleIndex];
    fui::ListItem& item = listItems[i + 1];
    item = fui::ListItem{};
    item.label = article.title;
    char* meta = listMetaText + i * LIST_META_CAPACITY;
    char* value = meta + LIST_SUBTITLE_CAPACITY;
    char dateText[16] = {};
    if (formatPublishedDate(article.published, dateText, sizeof(dateText))) {
      std::snprintf(meta, LIST_SUBTITLE_CAPACITY, "%s - %s", sources[article.sourceIndex].name.c_str(), dateText);
    } else {
      std::snprintf(meta, LIST_SUBTITLE_CAPACITY, "%s", sources[article.sourceIndex].name.c_str());
    }
    item.subtitle = meta;
    value[0] = '\0';
    if (article.readingMinutes > 0) {
      std::snprintf(value, LIST_VALUE_CAPACITY, "[%u min]", static_cast<unsigned>(article.readingMinutes));
    }
    item.value = value[0] ? value : nullptr;
    item.actionValue = static_cast<int16_t>(i + 1);
  }

  fui::ListProps props;
  props.items = listItems;
  props.count = static_cast<uint16_t>(articleCount + 1);
  props.selectedIndex = static_cast<int16_t>(selectorIndex);
  props.action = ACTION_ROW;
  props.inputMask = fui::InputTouch;
  props.valueInset = 2;
  props.valueText = screen.theme().smallText;
  props.valueText.bold = true;
  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);
  // Strong title / quiet metadata. Keep one title line for deterministic row
  // height and button navigation; the compact trailing value is reserved for
  // the reading-time cartouche and does not affect subtitle width.
  props.labelText.bold = true;
  props.labelText.maxLines = 1;
  props.subtitleText.maxLines = 1;
  props.balanceWrappedLabelWithValue = false;
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
  fui::TextStyle titleStyle = theme.titleText;
  titleStyle.bold = true;
  fui::TextStyle bodyStyle = theme.bodyText;
  fui::TextStyle metaStyle = theme.smallText;
  const int readerFontId = SETTINGS.getReaderFontId();
  const int16_t titleHeight = screen.target().lineHeight(titleStyle.font);
  const int16_t bodyHeight = static_cast<int16_t>(std::max(
      1, static_cast<int>(renderer.getLineHeight(readerFontId) * SETTINGS.getReaderLineCompression() + 0.5f)));
  const int16_t metaHeight = screen.target().lineHeight(metaStyle.font);
  const int readerMargin = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));
  const int readerWidth = std::max(1, renderer.getScreenWidth() - readerMargin * 2);

  for (const auto& line : articleTitleLines) {
    if (screen.body().height < titleHeight) break;
    screen.target().text(screen.takeTop(titleHeight, theme.spaceXs), line.c_str(), titleStyle);
  }
  screen.spacer(theme.spaceXs);
  char articleDate[16] = {};
  char metaLine[96] = {};
  if (formatPublishedDate(article.published, articleDate, sizeof(articleDate))) {
    std::snprintf(metaLine, sizeof(metaLine), "%s - %s", sources[article.sourceIndex].name.c_str(), articleDate);
  } else {
    std::snprintf(metaLine, sizeof(metaLine), "%s", sources[article.sourceIndex].name.c_str());
  }
  if (screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceSm), metaLine, metaStyle);
  }
  if (screen.body().height >= 1) {
    const fui::Rect divider = screen.takeTop(1, theme.spaceMd);
    screen.target().fill(divider, fui::Paint::solid(fui::Color::Black));
  }

  if (articleSummaryLines.empty()) {
    screen.centeredText(tr(STR_NO_ENTRIES), bodyStyle);
    return;
  }

  size_t displayedLines = 0;
  for (size_t i = articleLineOffset; i < articleSummaryLines.size(); ++i) {
    if (screen.body().height < bodyHeight) break;
    fui::Rect lineRect = screen.takeTop(bodyHeight);
    lineRect.x = static_cast<int16_t>(readerMargin);
    lineRect.width = static_cast<int16_t>(readerWidth);
    RssArticleRichText::drawLine(renderer, readerFontId, lineRect.x, lineRect.y, articleSummaryLines[i], true);
    ++displayedLines;
  }
  articlePageLines = std::max<size_t>(1, displayedLines);
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

  sdFontSystem.ensureLoaded(renderer);
  const int readerFontId = SETTINGS.getReaderFontId();
  const int margin = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));
  const int maxWidth = std::max(80, renderer.getScreenWidth() - margin * 2);
  const auto scale = uiScaleSpec();

  std::string offlineBody;
  const auto bodyResult = RssArticleCache::load(
      {article.link, article.title, article.published}, offlineBody);
  if (bodyResult == RssArticleCache::CacheResult::FALLBACK_READY) {
    offlineBody.insert(0, "Résumé du flux uniquement.\nActualise RSS pour réessayer l'article.\n\n");
  } else if (bodyResult != RssArticleCache::CacheResult::READY) {
    offlineBody = "Article indisponible hors ligne.\nActualise RSS pour réessayer.";
  }
  const std::string visibleBody = RssArticleRichText::visibleText(offlineBody);
  if (renderer.isSdCardFont(readerFontId) && !visibleBody.empty()) {
    renderer.ensureSdCardFontReady(readerFontId, visibleBody.c_str(), /*styleMask=*/0x01);
  }

  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.title, maxWidth, 3);
  articleSummaryLines = renderer.wrappedText(readerFontId, visibleBody.c_str(), maxWidth, 2000);
  RssArticleRichText::decorateWrappedLines(offlineBody, articleSummaryLines);
  articleLineOffset = 0;
  articlePageLines = 8;
  state = State::ARTICLE;
  requestUpdate();
}

void RssNewsActivity::closeArticle() {
  articleTitleLines.clear();
  articleSummaryLines.clear();
  articleLineOffset = 0;
  articlePageLines = 8;
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
  if (!feedItems || sourceIndex >= sourceCount) return false;
  std::memset(feedItems, 0, sizeof(RssItem) * feedItemCapacity);

  const size_t syncLimit = std::clamp<size_t>(sources[sourceIndex].syncLimit, 1, feedItemCapacity);
  RssParser parser(feedItems, syncLimit);
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
      sources[sourceIndex].url.c_str(),
      [&parser](const uint8_t* data, const size_t len) { return parser.write(data, len) == len; }, nullptr, "", "",
      std::move(options));
  if (result == HttpDownloader::ABORTED) {
    cancelled = true;
    return false;
  }
  if (result != HttpDownloader::OK) {
    LOG_ERR("RSS", "Fetch failed for %s", sources[sourceIndex].name.c_str());
    return false;
  }
  parser.flush();
  if (!parser) {
    LOG_ERR("RSS", "Parse failed for %s", sources[sourceIndex].name.c_str());
    return false;
  }
  outCount = parser.getItemCount();
  if (parser.wasTruncated()) LOG_DBG("RSS", "%s feed truncated to %zu items", sources[sourceIndex].name.c_str(), outCount);
  return outCount > 0;
}

void RssNewsActivity::refreshFeeds() {
  RssFetchDiagnostics::begin();
  RssFigaroAuth::resetSession();
  struct FigaroSessionScope {
    ~FigaroSessionScope() {
      RssFigaroAuth::resetSession();
      RssFetchDiagnostics::end();
    }
  } figaroSessionScope;
  if (sourceCount == 0) {
    refreshHadError = true;
    state = State::LIST;
    statusMessage = "Aucun flux RSS";
    requestUpdate();
    return;
  }
  if (!ensureFeedBuffer()) {
    refreshHadError = true;
    state = State::LIST;
    statusMessage = tr(STR_MEMORY_ERROR);
    requestUpdate();
    return;
  }
  usedNetwork = true;
  refreshHadError = false;
  goHomeAfterRefreshCancel = false;
  state = State::REFRESHING;
  statusMessage = sources[0].name.c_str();
  if (requestUpdateAndWait() != RequestUpdateResult::Rendered) requestUpdate(true);

  size_t successfulSources = 0;
  bool cancelled = false;
  for (uint8_t sourceIndex = 0; sourceIndex < sourceCount; ++sourceIndex) {
    statusMessage = sources[sourceIndex].name.c_str();
    requestUpdate(true);

    size_t fetchedCount = 0;
    if (fetchSource(sourceIndex, fetchedCount, cancelled)) {
      size_t processedBodies = 0;
      for (size_t itemIndex = 0; itemIndex < fetchedCount; ++itemIndex) {
        statusMessage = sources[sourceIndex].name + " " + std::to_string(itemIndex + 1) + "/" +
                        std::to_string(fetchedCount);
        requestUpdate(true);
        const auto cacheResult = RssArticleCache::ensureCached(
            feedItems[itemIndex], sources[sourceIndex].name.c_str(), sources[sourceIndex].dropRules.c_str(),
            sources[sourceIndex].dropStartRules.c_str(), sources[sourceIndex].stopRules.c_str(),
            [this, &cancelled]() {
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
        });
        processedBodies = itemIndex + 1;
        if (cacheResult == RssArticleCache::CacheResult::CANCELLED) {
          cancelled = true;
          break;
        }
        if (cacheResult == RssArticleCache::CacheResult::FAILED ||
            cacheResult == RssArticleCache::CacheResult::FALLBACK_READY) refreshHadError = true;
      }
      if (!cancelled) {
        if (mergeSourceArticles(sourceIndex, feedItems, fetchedCount)) {
          ++successfulSources;
        } else {
          refreshHadError = true;
        }
      } else {
        // This source was not merged into metadata. Remove any newly-created
        // body that is not already referenced by the current history.
        for (size_t i = 0; i < processedBodies; ++i) {
          bool referenced = false;
          for (size_t j = 0; j < articleCount; ++j) {
            if (RssArticleMetadata::same(articles[j], feedItems[i])) {
              referenced = true;
              break;
            }
          }
          if (!referenced) RssArticleCache::remove(feedItems[i]);
        }
      }
    } else if (!cancelled) {
      refreshHadError = true;
    }
    if (cancelled) break;
  }

  if (cancelled) {
    releaseFeedBuffer();
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

  releaseFeedBuffer();
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
  for (uint8_t sourceIndex = 0; sourceIndex < sourceCount && articleCount < articleCapacity; ++sourceIndex) {
    for (size_t sample = 0; sample < 3 && articleCount < articleCapacity; ++sample) {
      CachedArticle& article = articles[articleCount++];
      article = CachedArticle{};
      article.sourceIndex = sourceIndex;
      article.readingMinutes = static_cast<uint8_t>(sample + 1);
      snprintf(article.title, sizeof(article.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),
               sources[sourceIndex].name.c_str());
      snprintf(article.published, sizeof(article.published), "2026-09-%02uT12:00:00Z",
               static_cast<unsigned>(8 - sample));
    }
  }
}

void RssNewsActivity::loop() {
  if (state == State::WIFI_SELECTION || state == State::REFRESHING) return;

  if (TouchHeaderBackButton::wasTapped(mappedInput, renderer)) {
    if (state == State::ARTICLE) {
      closeArticle();
    } else {
      mappedInput.suppressNextBackRelease();
      onGoHome();
    }
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
      scrollArticle(static_cast<int>(articlePageLines));
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Up) ||
        mappedInput.wasReleased(MappedInputManager::Button::Left)) {
      scrollArticle(-static_cast<int>(articlePageLines));
      return;
    }
    const auto swipe = mappedInput.wasSwipe();
    if (swipe == MappedInputManager::SwipeDir::Up) {
      scrollArticle(static_cast<int>(articlePageLines));
    } else if (swipe == MappedInputManager::SwipeDir::Down) {
      scrollArticle(-static_cast<int>(articlePageLines));
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
