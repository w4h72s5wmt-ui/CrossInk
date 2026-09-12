from pathlib import Path


def replace_once(path, old, new, label):
    path = Path(path)
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1))


# Lightweight persistent metadata: one extra byte per article. No legacy cache
# migration is retained; RssNewsActivity bumps the cache version below.
replace_once(
    "src/activities/home/RssArticleMetadata.h",
    '''#include <cstddef>\n#include <cstdint>\n#include <cstring>\n''',
    '''#include <cctype>\n#include <cstddef>\n#include <cstdint>\n#include <cstring>\n''',
    "metadata includes")
replace_once(
    "src/activities/home/RssArticleMetadata.h",
    '''struct Record {\n  uint8_t sourceIndex = 0;\n  char title[RSS_TITLE_CAPACITY + 1] = {};\n''',
    '''struct Record {\n  uint8_t sourceIndex = 0;\n  uint8_t readingMinutes = 0;\n  char title[RSS_TITLE_CAPACITY + 1] = {};\n''',
    "metadata reading byte")
replace_once(
    "src/activities/home/RssArticleMetadata.h",
    '''constexpr size_t RECORD_BYTES = 1 + (RSS_TITLE_CAPACITY + 1) + (RSS_LINK_CAPACITY + 1) +\n                                (RSS_PUBLISHED_CAPACITY + 1);\n''',
    '''constexpr size_t RECORD_BYTES = 2 + (RSS_TITLE_CAPACITY + 1) + (RSS_LINK_CAPACITY + 1) +\n                                (RSS_PUBLISHED_CAPACITY + 1);\n''',
    "metadata packed size")
replace_once(
    "src/activities/home/RssArticleMetadata.h",
    '''inline Record fromItem(const uint8_t sourceIndex, const RssItem& item) {\n  Record record{};\n  record.sourceIndex = sourceIndex;\n''',
    '''inline uint8_t readingMinutesForText(const char* text, const size_t length, const uint16_t wordsPerMinute = 220) {\n  if (!text || length == 0 || wordsPerMinute == 0) return 0;\n  size_t words = 0;\n  bool inWord = false;\n  for (size_t i = 0; i < length && text[i]; ++i) {\n    const bool separator = std::isspace(static_cast<unsigned char>(text[i]));\n    if (!separator && !inWord) ++words;\n    inWord = !separator;\n  }\n  if (words == 0) return 0;\n  const size_t minutes = (words + wordsPerMinute - 1U) / wordsPerMinute;\n  return static_cast<uint8_t>(minutes > 99U ? 99U : minutes);\n}\n\ninline Record fromItem(const uint8_t sourceIndex, const RssItem& item, const uint8_t readingMinutes = 0) {\n  Record record{};\n  record.sourceIndex = sourceIndex;\n  record.readingMinutes = readingMinutes;\n''',
    "metadata constructor")

# Cache V6 intentionally invalidates V5 metadata. The article body files remain
# XRSS11/XRSSF1 and are reused/refreshed normally; no compatibility shim exists.
replace_once(
    "src/activities/home/RssNewsActivity.h",
    '''  static constexpr size_t LIST_META_CAPACITY = 64;\n  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2\n  // V5 stores lightweight history metadata; old development caches are\n  // intentionally invalidated rather than migrated.\n  static constexpr uint16_t CACHE_VERSION = 5;\n''',
    '''  static constexpr size_t LIST_SUBTITLE_CAPACITY = 64;\n  static constexpr size_t LIST_VALUE_CAPACITY = 8;\n  static constexpr size_t LIST_META_CAPACITY = LIST_SUBTITLE_CAPACITY + LIST_VALUE_CAPACITY;\n  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2\n  // V6 adds the one-byte reading-time estimate to lightweight history metadata.\n  // Old development metadata is intentionally invalidated rather than migrated.\n  static constexpr uint16_t CACHE_VERSION = 6;\n''',
    "cache version and list value storage")

# App-local calculation: load each freshly cached article once during merge,
# strip rich-text control markers, then retain only the rounded minute count.
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {\n  const Rect header = TouchHeaderBackButton::headerRect(renderer, input);\n  return Rect{header.x + header.width - SORT_TOUCH_WIDTH, header.y, SORT_TOUCH_WIDTH, header.height};\n}\n}  // namespace\n''',
    '''Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {\n  const Rect header = TouchHeaderBackButton::headerRect(renderer, input);\n  return Rect{header.x + header.width - SORT_TOUCH_WIDTH, header.y, SORT_TOUCH_WIDTH, header.height};\n}\n\nuint8_t estimateReadingMinutes(const RssItem& item) {\n  std::string cachedText;\n  const auto result = RssArticleCache::load(item, cachedText);\n  if (result != RssArticleCache::CacheResult::READY &&\n      result != RssArticleCache::CacheResult::FALLBACK_READY) {\n    return 0;\n  }\n  const std::string visibleText = RssArticleRichText::visibleText(cachedText);\n  return RssArticleMetadata::readingMinutesForText(visibleText.c_str(), visibleText.size());\n}\n}  // namespace\n''',
    "reading time helper")
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''    if (!duplicate) merged[mergedCount++] = RssArticleMetadata::fromItem(sourceIndex, items[i]);\n''',
    '''    if (!duplicate) {\n      merged[mergedCount++] =\n          RssArticleMetadata::fromItem(sourceIndex, items[i], estimateReadingMinutes(items[i]));\n    }\n''',
    "incoming read time")

# Reuse each 72-byte per-row metadata slot: 64 bytes for source/date subtitle,
# 8 bytes for a compact native trailing value such as "[2 min]".
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''    char* meta = listMetaText + i * LIST_META_CAPACITY;\n    char dateText[16] = {};\n    if (formatPublishedDate(article.published, dateText, sizeof(dateText))) {\n      std::snprintf(meta, LIST_META_CAPACITY, "%s - %s", sources[article.sourceIndex].name.c_str(), dateText);\n    } else {\n      std::snprintf(meta, LIST_META_CAPACITY, "%s", sources[article.sourceIndex].name.c_str());\n    }\n    item.subtitle = meta;\n    item.value = nullptr;\n    item.actionValue = static_cast<int16_t>(i + 1);\n''',
    '''    char* meta = listMetaText + i * LIST_META_CAPACITY;\n    char* value = meta + LIST_SUBTITLE_CAPACITY;\n    char dateText[16] = {};\n    if (formatPublishedDate(article.published, dateText, sizeof(dateText))) {\n      std::snprintf(meta, LIST_SUBTITLE_CAPACITY, "%s - %s", sources[article.sourceIndex].name.c_str(), dateText);\n    } else {\n      std::snprintf(meta, LIST_SUBTITLE_CAPACITY, "%s", sources[article.sourceIndex].name.c_str());\n    }\n    item.subtitle = meta;\n    value[0] = '\\0';\n    if (article.readingMinutes > 0) {\n      std::snprintf(value, LIST_VALUE_CAPACITY, "[%u min]", static_cast<unsigned>(article.readingMinutes));\n    }\n    item.value = value[0] ? value : nullptr;\n    item.actionValue = static_cast<int16_t>(i + 1);\n''',
    "list reading value")
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''  props.inputMask = fui::InputTouch;\n  props.valueInset = 0;\n  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);\n''',
    '''  props.inputMask = fui::InputTouch;\n  props.valueInset = 2;\n  props.valueText = screen.theme().smallText;\n  props.valueText.bold = true;\n  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);\n''',
    "list value style")
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''  // Strong title / quiet metadata. Keep one title line for deterministic row\n  // height and button navigation; removing the value column gives it the full\n  // usable width instead of squeezing it between source/date decorations.\n''',
    '''  // Strong title / quiet metadata. Keep one title line for deterministic row\n  // height and button navigation; the compact trailing value is reserved for\n  // the reading-time cartouche and does not affect subtitle width.\n''',
    "list comment")
replace_once(
    "src/activities/home/RssNewsActivity.cpp",
    '''      article.sourceIndex = sourceIndex;\n      snprintf(article.title, sizeof(article.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),\n''',
    '''      article.sourceIndex = sourceIndex;\n      article.readingMinutes = static_cast<uint8_t>(sample + 1);\n      snprintf(article.title, sizeof(article.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),\n''',
    "simulator read time")

# Host tests lock the exact one-byte metadata cost and the 220 wpm rounding.
replace_once(
    "tests/rss/test_article_cache.cpp",
    '''  const auto record = RssArticleMetadata::fromItem(3, item);\n  check(sizeof(RssItem) == 4684, "production-sized RssItem host model");\n  check(sizeof(record) == 588, "lightweight RSS history record is 588 bytes");\n  check(record.sourceIndex == 3 && std::strcmp(record.title, item.title) == 0 &&\n            std::strcmp(record.link, item.link) == 0 && std::strcmp(record.published, item.published) == 0,\n        "history record keeps source/title/link/date");\n''',
    '''  const auto record = RssArticleMetadata::fromItem(3, item, 7);\n  check(sizeof(RssItem) == 4684, "production-sized RssItem host model");\n  check(sizeof(record) == 589, "lightweight RSS history record is 589 bytes with read time");\n  check(record.sourceIndex == 3 && record.readingMinutes == 7 && std::strcmp(record.title, item.title) == 0 &&\n            std::strcmp(record.link, item.link) == 0 && std::strcmp(record.published, item.published) == 0,\n        "history record keeps source/read-time/title/link/date");\n''',
    "metadata size test")
replace_once(
    "tests/rss/test_article_cache.cpp",
    '''  check(RssArticleMetadata::same(record, changed), "summary is not part of history identity");\n}\n''',
    '''  check(RssArticleMetadata::same(record, changed), "summary is not part of history identity");\n\n  const std::string words220 = [] {\n    std::string text;\n    for (int i = 0; i < 220; ++i) text += i ? " mot" : "mot";\n    return text;\n  }();\n  check(RssArticleMetadata::readingMinutesForText(words220.c_str(), words220.size()) == 1,\n        "220 words rounds to one minute");\n  const std::string words221 = words220 + " mot";\n  check(RssArticleMetadata::readingMinutesForText(words221.c_str(), words221.size()) == 2,\n        "221 words rounds up to two minutes");\n  check(RssArticleMetadata::readingMinutesForText("", 0) == 0, "empty text has no reading estimate");\n  std::string huge;\n  huge.reserve(220 * 101 * 2);\n  for (int i = 0; i < 220 * 101; ++i) huge += i ? " x" : "x";\n  check(RssArticleMetadata::readingMinutesForText(huge.c_str(), huge.size()) == 99,\n        "reading estimate is capped at 99 minutes");\n}\n''',
    "reading time tests")

print("Applied RSS reading-time candidate (220 wpm, native trailing cartouche).")
