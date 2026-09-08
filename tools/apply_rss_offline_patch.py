from pathlib import Path

HEADER = Path("src/activities/home/RssNewsActivity.h")
CPP = Path("src/activities/home/RssNewsActivity.cpp")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Expected block not found: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one block for {label}, found {text.count(old)}")
    return text.replace(old, new, 1)


header = HEADER.read_text()
header = replace_once(
    header,
    "  size_t articleLineOffset = 0;\n  size_t openArticleIndex = MAX_ARTICLES;",
    "  size_t articleLineOffset = 0;\n  size_t articlePageLines = 8;\n  size_t openArticleIndex = MAX_ARTICLES;",
    "article page size state",
)
HEADER.write_text(header)

cpp = CPP.read_text()
cpp = replace_once(
    cpp,
    '#include "MappedInputManager.h"\n#include "SdCardFontSystem.h"',
    '#include "CrossPointSettings.h"\n#include "MappedInputManager.h"\n#include "RssArticleCache.h"\n#include "SdCardFontSystem.h"',
    "RSS includes",
)
cpp = replace_once(
    cpp,
    "constexpr size_t ARTICLE_PAGE_LINES = 8;\n",
    "",
    "fixed article page size",
)
cpp = replace_once(
    cpp,
    "  articleLineOffset = 0;\n  openArticleIndex = MAX_ARTICLES;",
    "  articleLineOffset = 0;\n  articlePageLines = 8;\n  openArticleIndex = MAX_ARTICLES;",
    "article page size reset",
)

old_build = '''void RssNewsActivity::buildArticleScreen(UiApp::ScreenType& screen) {
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
'''
new_build = '''void RssNewsActivity::buildArticleScreen(UiApp::ScreenType& screen) {
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
  const int readerFontId = SETTINGS.getReaderFontId();
  bodyStyle.font = readerFontId;
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

  size_t displayedLines = 0;
  for (size_t i = articleLineOffset; i < articleSummaryLines.size(); ++i) {
    if (screen.body().height < bodyHeight) break;
    fui::Rect lineRect = screen.takeTop(bodyHeight);
    lineRect.x = static_cast<int16_t>(readerMargin);
    lineRect.width = static_cast<int16_t>(readerWidth);
    screen.target().text(lineRect, articleSummaryLines[i].c_str(), bodyStyle);
    ++displayedLines;
  }
  articlePageLines = std::max<size_t>(1, displayedLines);
}
'''
cpp = replace_once(cpp, old_build, new_build, "article rendering")

old_open = '''void RssNewsActivity::openArticle(const size_t articleIndex) {
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
'''
new_open = '''void RssNewsActivity::openArticle(const size_t articleIndex) {
  if (!articles || articleIndex >= articleCount) return;
  openArticleIndex = articleIndex;
  const CachedArticle& article = articles[articleIndex];

  sdFontSystem.ensureLoaded(renderer);
  const int readerFontId = SETTINGS.getReaderFontId();
  const int margin = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));
  const int maxWidth = std::max(80, renderer.getScreenWidth() - margin * 2);
  const auto scale = uiScaleSpec();

  std::string offlineBody;
  if (!RssArticleCache::load(article.item, offlineBody)) offlineBody = article.item.summary;
  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {
    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);
  }

  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);
  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);
  articleLineOffset = 0;
  articlePageLines = 8;
  state = State::ARTICLE;
  requestUpdate();
}
'''
cpp = replace_once(cpp, old_open, new_open, "offline article open")

cpp = replace_once(
    cpp,
    "      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(static_cast<int>(articlePageLines));",
    "button next page",
)
cpp = replace_once(
    cpp,
    "      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(-static_cast<int>(articlePageLines));",
    "button previous page",
)
cpp = replace_once(
    cpp,
    "      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));\n    } else if (swipe == MappedInputManager::SwipeDir::Down) {\n      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(static_cast<int>(articlePageLines));\n    } else if (swipe == MappedInputManager::SwipeDir::Down) {\n      scrollArticle(-static_cast<int>(articlePageLines));",
    "swipe article paging",
)

old_refresh = '''    size_t fetchedCount = 0;
    if (fetchSource(sourceIndex, fetchedCount, cancelled)) {
      mergeSourceArticles(sourceIndex, feedItems, fetchedCount);
      ++successfulSources;
    } else if (!cancelled) {
      refreshHadError = true;
    }
    if (cancelled) break;
'''
new_refresh = '''    size_t fetchedCount = 0;
    if (fetchSource(sourceIndex, fetchedCount, cancelled)) {
      for (size_t itemIndex = 0; itemIndex < fetchedCount; ++itemIndex) {
        statusMessage = std::string(SOURCES[sourceIndex].name) + " " + std::to_string(itemIndex + 1) + "/" +
                        std::to_string(fetchedCount);
        requestUpdate(true);
        const auto cacheResult = RssArticleCache::ensureCached(feedItems[itemIndex], [this, &cancelled]() {
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
        if (cacheResult == RssArticleCache::CacheResult::CANCELLED) {
          cancelled = true;
          break;
        }
        if (cacheResult == RssArticleCache::CacheResult::FAILED) refreshHadError = true;
      }
      if (!cancelled) {
        mergeSourceArticles(sourceIndex, feedItems, fetchedCount);
        ++successfulSources;
      }
    } else if (!cancelled) {
      refreshHadError = true;
    }
    if (cancelled) break;
'''
cpp = replace_once(cpp, old_refresh, new_refresh, "article cache sync")

CPP.write_text(cpp)
print("RSS offline article cache and reader typography patch applied")
