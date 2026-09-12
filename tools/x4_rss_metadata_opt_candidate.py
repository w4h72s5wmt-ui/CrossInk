from pathlib import Path


def replace_once(path, old, new, label):
    path = Path(path)
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_section(path, start, end, replacement, label):
    path = Path(path)
    text = path.read_text()
    start_pos = text.find(start)
    if start_pos < 0:
        raise SystemExit(f"{label}: start marker missing")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise SystemExit(f"{label}: end marker missing")
    path.write_text(text[:start_pos] + replacement + text[end_pos:])


# Historical RSS records only need identity/list metadata. Feed summaries remain
# transient during parsing and are persisted only when they are actually used as
# an offline fallback. This removes the 4 KiB summary array from every history
# record without changing RssParser or the network-facing RssItem.
Path("src/activities/home/RssArticleMetadata.h").write_text(r'''#pragma once

#include <RssParser.h>

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace RssArticleMetadata {

struct Record {
  uint8_t sourceIndex = 0;
  char title[RSS_TITLE_CAPACITY + 1] = {};
  char link[RSS_LINK_CAPACITY + 1] = {};
  char published[RSS_PUBLISHED_CAPACITY + 1] = {};
};

constexpr size_t RECORD_BYTES = 1 + (RSS_TITLE_CAPACITY + 1) + (RSS_LINK_CAPACITY + 1) +
                                (RSS_PUBLISHED_CAPACITY + 1);
static_assert(sizeof(Record) == RECORD_BYTES, "RSS history metadata must stay packed/lightweight");

inline bool sameFields(const char* leftLink, const char* leftTitle, const char* leftPublished,
                       const char* rightLink, const char* rightTitle, const char* rightPublished) {
  const bool leftHasLink = leftLink && leftLink[0];
  const bool rightHasLink = rightLink && rightLink[0];
  if (leftHasLink && rightHasLink) return std::strcmp(leftLink, rightLink) == 0;
  if (std::strcmp(leftTitle ? leftTitle : "", rightTitle ? rightTitle : "") != 0) return false;
  const bool leftHasPublished = leftPublished && leftPublished[0];
  const bool rightHasPublished = rightPublished && rightPublished[0];
  if (leftHasPublished || rightHasPublished) {
    return std::strcmp(leftPublished ? leftPublished : "", rightPublished ? rightPublished : "") == 0;
  }
  return true;
}

inline bool same(const RssItem& left, const RssItem& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline bool same(const Record& left, const RssItem& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline bool same(const Record& left, const Record& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline Record fromItem(const uint8_t sourceIndex, const RssItem& item) {
  Record record{};
  record.sourceIndex = sourceIndex;
  std::memcpy(record.title, item.title, sizeof(record.title));
  std::memcpy(record.link, item.link, sizeof(record.link));
  std::memcpy(record.published, item.published, sizeof(record.published));
  record.title[sizeof(record.title) - 1] = '\0';
  record.link[sizeof(record.link) - 1] = '\0';
  record.published[sizeof(record.published) - 1] = '\0';
  return record;
}

}  // namespace RssArticleMetadata
''')

# Host tests now mirror the production RssItem capacities so memory-model
# assertions exercise the same layout rather than a loose oversized stub.
Path("tests/rss/stubs/RssParser.h").write_text(r'''#pragma once

#include <cstddef>

constexpr size_t RSS_TITLE_CAPACITY = 144;
constexpr size_t RSS_LINK_CAPACITY = 384;
constexpr size_t RSS_SUMMARY_CAPACITY = 4096;
constexpr size_t RSS_PUBLISHED_CAPACITY = 56;

struct RssItem {
  char title[RSS_TITLE_CAPACITY + 1] = {};
  char link[RSS_LINK_CAPACITY + 1] = {};
  char summary[RSS_SUMMARY_CAPACITY + 1] = {};
  char published[RSS_PUBLISHED_CAPACITY + 1] = {};
};
''')

# Cache API: body identity is independent of the large parser record. Fallback
# summaries become explicit SD cache entries, while hasCurrentBody continues to
# mean a real extracted article body.
Path("src/activities/home/RssArticleCache.h").write_text(r'''#pragma once

#include <RssParser.h>

#include <functional>
#include <string>

namespace RssArticleCache {

enum class CacheResult {
  READY,
  FALLBACK_READY,
  FAILED,
  CANCELLED,
};

struct ArticleIdentity {
  const char* link = nullptr;
  const char* title = nullptr;
  const char* published = nullptr;
};

using CancelCallback = std::function<bool()>;

ArticleIdentity identityOf(const RssItem& item);

// Returns a stable SD path derived from the article URL (or title/date when a
// feed does not provide a URL). The article body itself is stored separately
// from the RSS metadata cache so hundreds of entries do not consume PSRAM.
std::string bodyPath(const ArticleIdentity& identity);
std::string bodyPath(const RssItem& item);

// A current body is a real extracted article. A readable body may also be a
// sanitized feed-summary fallback persisted after a failed public fetch.
bool hasCurrentBody(const ArticleIdentity& identity);
bool hasCurrentBody(const RssItem& item);
bool hasReadableBody(const ArticleIdentity& identity);
bool hasReadableBody(const RssItem& item);

// Removes the dedicated offline body/fallback for an article. Missing files
// count as success so callers can prune history without special cases.
bool remove(const ArticleIdentity& identity);
bool remove(const RssItem& item);

// Downloads and extracts readable HTML text when the full body is not cached.
// Public-feed failures persist a sanitized summary fallback but are retried on
// every manual refresh. Figaro AUTH never substitutes a public summary.
CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                         const char* dropStartRules, const char* stopRules,
                         const CancelCallback& shouldCancel);

// Loads already-sanitized SD text. READY is a full article and FALLBACK_READY
// is the persisted feed summary. No historical RssItem summary is required.
CacheResult load(const ArticleIdentity& identity, std::string& outText);
CacheResult load(const RssItem& item, std::string& outText);

}  // namespace RssArticleCache
''')

cache_cpp = Path("src/activities/home/RssArticleCache.cpp")
text = cache_cpp.read_text()
old = '''constexpr char BODY_MAGIC[] = "XRSS11\\n";
constexpr size_t BODY_MAGIC_BYTES = sizeof(BODY_MAGIC) - 1;
'''
new = '''constexpr char BODY_MAGIC[] = "XRSS11\\n";
constexpr char FALLBACK_MAGIC[] = "XRSSF1\\n";
constexpr size_t BODY_MAGIC_BYTES = sizeof(BODY_MAGIC) - 1;
static_assert(sizeof(FALLBACK_MAGIC) == sizeof(BODY_MAGIC), "RSS body markers must have equal width");
'''
if text.count(old) != 1:
    raise SystemExit("cache marker anchor mismatch")
text = text.replace(old, new, 1)
cache_cpp.write_text(text)

replace_section(
    "src/activities/home/RssArticleCache.cpp",
    "bool bodyCacheIsCurrent(const std::string& path) {\n",
    "size_t sanitizeFallbackMarkup(char* text, const size_t length) {\n",
    r'''enum class BodyCacheKind : uint8_t { NONE, FULL, FALLBACK };

BodyCacheKind bodyCacheKind(const std::string& path) {
  if (!Storage.exists(path.c_str())) return BodyCacheKind::NONE;
  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return BodyCacheKind::NONE;
  char marker[BODY_MAGIC_BYTES] = {};
  const bool sized = file.size() > BODY_MAGIC_BYTES && file.size() <= BODY_MAGIC_BYTES + MAX_TEXT_BYTES;
  const bool readMarker = sized && file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES);
  file.close();
  if (!readMarker) return BodyCacheKind::NONE;
  if (std::memcmp(marker, BODY_MAGIC, BODY_MAGIC_BYTES) == 0) return BodyCacheKind::FULL;
  if (std::memcmp(marker, FALLBACK_MAGIC, BODY_MAGIC_BYTES) == 0) return BodyCacheKind::FALLBACK;
  return BodyCacheKind::NONE;
}

bool bodyCacheIsCurrent(const std::string& path) { return bodyCacheKind(path) == BodyCacheKind::FULL; }

bool bodyCacheIsReadable(const std::string& path) { return bodyCacheKind(path) != BodyCacheKind::NONE; }

bool writeTextFile(const std::string& path, const char* marker, const char* text, const size_t length) {
  if (!marker || std::strlen(marker) != BODY_MAGIC_BYTES || !text || length == 0) return false;
  Storage.ensureDirectoryExists("/.crosspoint");
  Storage.ensureDirectoryExists(CACHE_DIR);
  const std::string tempPath = path + ".tmp";
  Storage.remove(tempPath.c_str());

  FsFile file;
  if (!Storage.openFileForWrite("RSS", tempPath, file)) return false;
  const size_t markerWritten = file.write(reinterpret_cast<const uint8_t*>(marker), BODY_MAGIC_BYTES);
  const size_t textWritten = file.write(reinterpret_cast<const uint8_t*>(text), length);
  const bool synced = markerWritten == BODY_MAGIC_BYTES && textWritten == length && file.sync();
  file.close();
  if (!synced) {
    Storage.remove(tempPath.c_str());
    return false;
  }
  Storage.remove(path.c_str());
  if (!Storage.rename(tempPath.c_str(), path.c_str())) {
    Storage.remove(tempPath.c_str());
    return false;
  }
  return true;
}

size_t sanitizeFallbackMarkup(char* text, const size_t length) {
''',
    "cache body-state helpers")

replace_section(
    "src/activities/home/RssArticleCache.cpp",
    "std::string bodyPath(const RssItem& item) {\n",
    '#include "RssArticleCachePolicy.inc"\n',
    r'''ArticleIdentity identityOf(const RssItem& item) { return ArticleIdentity{item.link, item.title, item.published}; }

std::string bodyPath(const ArticleIdentity& identity) {
  const char* link = identity.link ? identity.link : "";
  const char* title = identity.title ? identity.title : "";
  const char* published = identity.published ? identity.published : "";
  uint64_t hash = fnv1a64(link);
  if (!link[0]) {
    hash = fnv1a64(title, hash);
    hash = fnv1a64(published, hash);
  }
  const uint64_t authKey = RssFigaroAuth::cacheKeyFor(link);
  for (size_t i = 0; authKey != 0 && i < sizeof(authKey); ++i) {
    hash ^= static_cast<uint8_t>(authKey >> (i * 8U));
    hash *= 1099511628211ULL;
  }
  char name[64];
  std::snprintf(name, sizeof(name), "%s/%016llx.txt", CACHE_DIR, static_cast<unsigned long long>(hash));
  return name;
}

std::string bodyPath(const RssItem& item) { return bodyPath(identityOf(item)); }

bool hasCurrentBody(const ArticleIdentity& identity) { return bodyCacheIsCurrent(bodyPath(identity)); }

bool hasCurrentBody(const RssItem& item) { return hasCurrentBody(identityOf(item)); }

bool hasReadableBody(const ArticleIdentity& identity) { return bodyCacheIsReadable(bodyPath(identity)); }

bool hasReadableBody(const RssItem& item) { return hasReadableBody(identityOf(item)); }

bool remove(const ArticleIdentity& identity) {
  const std::string path = bodyPath(identity);
  if (!Storage.exists(path.c_str())) return true;
  Storage.remove(path.c_str());
  return !Storage.exists(path.c_str());
}

bool remove(const RssItem& item) { return remove(identityOf(item)); }

#include "RssArticleCachePolicy.inc"
''',
    "cache identity API")

policy = Path("src/activities/home/RssArticleCachePolicy.inc")
text = policy.read_text()
text = text.replace(
    "// Only extracted article bodies are persisted. Summaries already exist in\n// RssItem and are prepared on opening, never mistaken for a cached article.\n",
    "// Extracted article bodies and sanitized public-feed fallbacks are persisted\n// separately from lightweight history metadata. Full bodies are still retried\n// whenever only a fallback exists.\n",
    1)
old = '''  const std::string path = bodyPath(item);
  if (bodyCacheIsCurrent(path)) {
    report("cache-hit", HttpDownloader::OK);
    return CacheResult::READY;
  }
  if (Storage.exists(path.c_str())) Storage.remove(path.c_str());

  const auto unavailable = [&]() {
    if (useFigaroAuth) {
      LOG_ERR("RSS", "Figaro AUTH failed; no public fallback cached: %s", item.link);
      return CacheResult::FAILED;
    }
    LOG_ERR("RSS", "Body unavailable; summary only, retry on manual refresh: %s", item.link);
    return item.summary[0] ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  };
'''
new = '''  const std::string path = bodyPath(item);
  const BodyCacheKind existingCache = bodyCacheKind(path);
  if (existingCache == BodyCacheKind::FULL) {
    report("cache-hit", HttpDownloader::OK);
    return CacheResult::READY;
  }
  if (existingCache == BodyCacheKind::NONE && Storage.exists(path.c_str())) Storage.remove(path.c_str());

  const auto unavailable = [&]() {
    if (useFigaroAuth) {
      LOG_ERR("RSS", "Figaro AUTH failed; no public fallback cached: %s", item.link);
      return CacheResult::FAILED;
    }
    std::string fallbackText;
    if (buildFallbackText(item, sourceName, dropRules, dropStartRules, stopRules, fallbackText) &&
        writeTextFile(path, FALLBACK_MAGIC, fallbackText.data(), fallbackText.size())) {
      LOG_DBG("RSS", "Persisted feed-summary fallback: %s", item.link);
      return CacheResult::FALLBACK_READY;
    }
    if (bodyCacheKind(path) == BodyCacheKind::FALLBACK) return CacheResult::FALLBACK_READY;
    LOG_ERR("RSS", "Body/fallback unavailable; retry on manual refresh: %s", item.link);
    return CacheResult::FAILED;
  };
'''
if text.count(old) != 1:
    raise SystemExit("policy unavailable anchor mismatch")
text = text.replace(old, new, 1)
old = "    if (!writeTextFile(path, text, textLength)) {\n"
new = "    if (!writeTextFile(path, BODY_MAGIC, text, textLength)) {\n"
if text.count(old) != 1:
    raise SystemExit("full body writer anchor mismatch")
text = text.replace(old, new, 1)
policy.write_text(text)

replace_section(
    "src/activities/home/RssArticleCachePolicy.inc",
    "CacheResult load(const RssItem& item, const char* sourceName, const char* dropRules,\n",
    "}",
    # This marker replacement is completed below with a dedicated tail rewrite;
    # use a sentinel to avoid accidental partial function matching.
    "__LOAD_REPLACED_BELOW__",
    "cache load sentinel")
# The previous helper intentionally replaced only through the first closing brace,
# which is not sufficient for a nested function. Restore from the sentinel by
# rebuilding the complete tail from the known load() start: load() is the final
# production function in this include.
policy = Path("src/activities/home/RssArticleCachePolicy.inc")
text = policy.read_text()
sentinel = "__LOAD_REPLACED_BELOW__"
pos = text.find(sentinel)
if pos < 0:
    raise SystemExit("cache load sentinel missing")
# Everything after the sentinel came from the old nested body and is discarded.
text = text[:pos] + r'''CacheResult load(const ArticleIdentity& identity, std::string& outText) {
  outText.clear();
  const std::string path = bodyPath(identity);
  const BodyCacheKind kind = bodyCacheKind(path);
  if (kind == BodyCacheKind::NONE) {
    if (Storage.exists(path.c_str())) Storage.remove(path.c_str());
    return CacheResult::FAILED;
  }

  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return CacheResult::FAILED;
  char marker[BODY_MAGIC_BYTES] = {};
  const size_t size = static_cast<size_t>(file.size());
  const bool validSize = size > BODY_MAGIC_BYTES && size <= BODY_MAGIC_BYTES + MAX_TEXT_BYTES;
  const bool validMarker = validSize &&
                           file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES);
  if (!validMarker) {
    file.close();
    Storage.remove(path.c_str());
    return CacheResult::FAILED;
  }

  const size_t expected = size - BODY_MAGIC_BYTES;
  char buffer[768];
  while (outText.size() < expected) {
    const size_t want = std::min(expected - outText.size(), sizeof(buffer));
    const int count = file.read(buffer, want);
    if (count <= 0) break;
    outText.append(buffer, static_cast<size_t>(count));
  }
  file.close();
  if (outText.size() != expected) {
    outText.clear();
    Storage.remove(path.c_str());
    return CacheResult::FAILED;
  }
  return kind == BodyCacheKind::FULL ? CacheResult::READY : CacheResult::FALLBACK_READY;
}

CacheResult load(const RssItem& item, std::string& outText) { return load(identityOf(item), outText); }
'''
policy.write_text(text)

# Activity history now points at the lightweight metadata record and allocates
# the parser scratch only while a refresh is active.
activity_h = Path("src/activities/home/RssNewsActivity.h")
text = activity_h.read_text()
old = '''#include "activities/Activity.h"
#include "activities/ScreenTransitionRefresh.h"
'''
new = '''#include "activities/Activity.h"
#include "activities/ScreenTransitionRefresh.h"
#include "RssArticleMetadata.h"
'''
if text.count(old) != 1:
    raise SystemExit("activity metadata include anchor mismatch")
text = text.replace(old, new, 1)
old = '''  struct CachedArticle {
    uint8_t sourceIndex = 0;
    RssItem item{};
  };
'''
new = '''  using CachedArticle = RssArticleMetadata::Record;
'''
if text.count(old) != 1:
    raise SystemExit("CachedArticle anchor mismatch")
text = text.replace(old, new, 1)
text = text.replace(
    '''  // V4 binds the binary article cache to the full feeds.txt configuration,
  // including sync/history limits, so capacity changes invalidate metadata cleanly.
  static constexpr uint16_t CACHE_VERSION = 4;
''',
    '''  // V5 stores lightweight history metadata; old development caches are
  // intentionally invalidated rather than migrated.
  static constexpr uint16_t CACHE_VERSION = 5;
''',
    1)
text = text.replace(
    '''  bool ensureBuffers();
  void loadSources();
''',
    '''  bool ensureBuffers();
  bool ensureFeedBuffer();
  void releaseFeedBuffer();
  void loadSources();
''',
    1)
text = text.replace(
    "  void mergeSourceArticles(uint8_t sourceIndex, RssItem* items, size_t count);\n",
    "  bool mergeSourceArticles(uint8_t sourceIndex, RssItem* items, size_t count);\n",
    1)
activity_h.write_text(text)

activity_cpp = Path("src/activities/home/RssNewsActivity.cpp")
text = activity_cpp.read_text()
old = '''bool sameRssItem(const RssItem& left, const RssItem& right) {
  if (left.link[0] && right.link[0]) return std::strcmp(left.link, right.link) == 0;
  if (std::strcmp(left.title, right.title) != 0) return false;
  if (left.published[0] || right.published[0]) return std::strcmp(left.published, right.published) == 0;
  return true;
}

'''
if text.count(old) != 1:
    raise SystemExit("sameRssItem helper anchor mismatch")
text = text.replace(old, "", 1)
activity_cpp.write_text(text)

replace_section(
    "src/activities/home/RssNewsActivity.cpp",
    "bool RssNewsActivity::ensureBuffers() {\n",
    "void RssNewsActivity::loadSources() {\n",
    r'''bool RssNewsActivity::ensureBuffers() {
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
''',
    "runtime RSS buffers")

activity_cpp = Path("src/activities/home/RssNewsActivity.cpp")
text = activity_cpp.read_text()
text = text.replace(
    "      RssArticleCache::remove(stale.item);\n",
    "      RssArticleCache::remove({stale.link, stale.title, stale.published});\n",
    1)
activity_cpp.write_text(text)

replace_section(
    "src/activities/home/RssNewsActivity.cpp",
    "void RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {\n",
    "void RssNewsActivity::rebuildDisplayOrder() {\n",
    r'''bool RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {
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
    if (!duplicate) merged[mergedCount++] = RssArticleMetadata::fromItem(sourceIndex, items[i]);
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
''',
    "lightweight history merge")

activity_cpp = Path("src/activities/home/RssNewsActivity.cpp")
text = activity_cpp.read_text()
replacements = [
    ("publishedDateKey(left.item.published)", "publishedDateKey(left.published)"),
    ("publishedDateKey(right.item.published)", "publishedDateKey(right.published)"),
    ("item.label = article.item.title;", "item.label = article.title;"),
    ("formatPublishedDate(article.item.published, dateText, sizeof(dateText))", "formatPublishedDate(article.published, dateText, sizeof(dateText))"),
    ("formatPublishedDate(article.item.published, articleDate, sizeof(articleDate))", "formatPublishedDate(article.published, articleDate, sizeof(articleDate))"),
    ("articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 3);", "articleTitleLines = renderer.wrappedText(scale.titleFontId, article.title, maxWidth, 3);"),
]
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"activity field replacement missing: {old}")
    text = text.replace(old, new, 1)
old = '''  const auto bodyResult = RssArticleCache::load(article.item, source.name.c_str(), source.dropRules.c_str(),
                                              source.dropStartRules.c_str(), source.stopRules.c_str(), offlineBody);
'''
new = '''  const auto bodyResult = RssArticleCache::load(
      {article.link, article.title, article.published}, offlineBody);
'''
if text.count(old) != 1:
    raise SystemExit("activity article load anchor mismatch")
text = text.replace(old, new, 1)
# source is no longer needed solely for load().
text = text.replace("  const Source& source = sources[article.sourceIndex];\n", "", 1)
old = '''      CachedArticle& article = articles[articleCount++];
      article = CachedArticle{};
      article.sourceIndex = sourceIndex;
      snprintf(article.item.title, sizeof(article.item.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),
               sources[sourceIndex].name.c_str());
      snprintf(article.item.summary, sizeof(article.item.summary),
               "Contenu hors ligne de demonstration pour verifier le cache SD, le tactile et la pagination de lecture.");
      snprintf(article.item.published, sizeof(article.item.published), "2026-09-%02uT12:00:00Z",
               static_cast<unsigned>(8 - sample));
'''
new = '''      CachedArticle& article = articles[articleCount++];
      article = CachedArticle{};
      article.sourceIndex = sourceIndex;
      snprintf(article.title, sizeof(article.title), "Exemple %u - %s", static_cast<unsigned>(sample + 1),
               sources[sourceIndex].name.c_str());
      snprintf(article.published, sizeof(article.published), "2026-09-%02uT12:00:00Z",
               static_cast<unsigned>(8 - sample));
'''
if text.count(old) != 1:
    raise SystemExit("simulator metadata anchor mismatch")
text = text.replace(old, new, 1)
old = '''      if (!cancelled) {
        mergeSourceArticles(sourceIndex, feedItems, fetchedCount);
        ++successfulSources;
      } else {
'''
new = '''      if (!cancelled) {
        if (mergeSourceArticles(sourceIndex, feedItems, fetchedCount)) {
          ++successfulSources;
        } else {
          refreshHadError = true;
        }
      } else {
'''
if text.count(old) != 1:
    raise SystemExit("refresh merge result anchor mismatch")
text = text.replace(old, new, 1)
old = '''            if (sameRssItem(feedItems[i], articles[j].item)) {
              referenced = true;
              break;
            }
'''
new = '''            if (RssArticleMetadata::same(articles[j], feedItems[i])) {
              referenced = true;
              break;
            }
'''
if text.count(old) != 1:
    raise SystemExit("cancel cleanup identity anchor mismatch")
text = text.replace(old, new, 1)
activity_cpp.write_text(text)

# Allocate the large RssItem scratch only for a refresh, then release it before
# returning to the list/Home. This also makes max(sync) safe because history
# merging no longer writes historical records back into the feed array.
activity_cpp = Path("src/activities/home/RssNewsActivity.cpp")
text = activity_cpp.read_text()
old = '''  if (sourceCount == 0) {
    refreshHadError = true;
    state = State::LIST;
    statusMessage = "Aucun flux RSS";
    requestUpdate();
    return;
  }
  usedNetwork = true;
'''
new = '''  if (sourceCount == 0) {
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
'''
if text.count(old) != 1:
    raise SystemExit("refresh scratch allocation anchor mismatch")
text = text.replace(old, new, 1)
old = '''  if (cancelled) {
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
'''
new = '''  if (cancelled) {
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
'''
if text.count(old) != 1:
    raise SystemExit("refresh scratch release anchor mismatch")
text = text.replace(old, new, 1)
activity_cpp.write_text(text)

# Tests cover persisted fallback state, retry-to-full behavior, invalid marker
# rejection, and the exact lightweight metadata layout.
test = Path("tests/rss/test_article_cache.cpp")
text = test.read_text()
old = '#include "../../src/activities/home/RssArticleCache.cpp"\n'
new = '#include "../../src/activities/home/RssArticleCache.cpp"\n#include "../../src/activities/home/RssArticleMetadata.h"\n'
if text.count(old) != 1:
    raise SystemExit("test metadata include anchor mismatch")
text = text.replace(old, new, 1)
old = '''RC::CacheResult load(const RssItem& item, std::string& out) {
  return RC::load(item, "Test", "", "", "[Lire la suite]", out);
}
'''
new = '''RC::CacheResult load(const RssItem& item, std::string& out) {
  return RC::load(item, out);
}
'''
if text.count(old) != 1:
    raise SystemExit("test load helper anchor mismatch")
text = text.replace(old, new, 1)
test.write_text(text)

replace_section(
    "tests/rss/test_article_cache.cpp",
    "void cacheTests() {\n",
    "std::string readFile(const char* path) {\n",
    r'''void metadataTests() {
  auto item = makeItem();
  std::strcpy(item.published, "2026-09-12T12:00:00Z");
  const auto record = RssArticleMetadata::fromItem(3, item);
  check(sizeof(RssItem) == 4684, "production-sized RssItem host model");
  check(sizeof(record) == 588, "lightweight RSS history record is 588 bytes");
  check(record.sourceIndex == 3 && std::strcmp(record.title, item.title) == 0 &&
            std::strcmp(record.link, item.link) == 0 && std::strcmp(record.published, item.published) == 0,
        "history record keeps source/title/link/date");
  check(RssArticleMetadata::same(record, item), "history identity matches source RssItem");
  auto changed = item;
  std::strcpy(changed.summary, "un autre resume ne change pas l'identite");
  check(RssArticleMetadata::same(record, changed), "summary is not part of history identity");
}

void cacheTests() {
  auto item = makeItem();
  std::string out;
  reset();
  const std::string path = RC::bodyPath(item);
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "network failure -> persisted summary fallback");
  check(testFiles[path].rfind("XRSSF1\\n", 0) == 0, "fallback has distinct SD marker");
  check(RC::hasReadableBody(item) && !RC::hasCurrentBody(item), "fallback readable but not a full body");
  check(load(item, out) == RC::CacheResult::FALLBACK_READY && out == "Le resume du flux reste disponible.",
        "persisted summary fallback loads without RssItem history summary");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY, "manual retry replaces fallback with full body");
  check(testFiles[path].rfind("XRSS11\\n", 0) == 0, "full body keeps XRSS11 marker");
  check(load(item, out) == RC::CacheResult::READY && out.find("FIN_UTILE") != std::string::npos, "body loads");
  const auto cachedCalls = H::publicCalls;
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == cachedCalls, "valid full cache reused");
  check(RC::hasCurrentBody(item) && RC::hasReadableBody(item), "full body probes current/readable");

  reset();
  testFiles[RC::bodyPath(item)] = "XRSS10\\nAncien corps de developpement";
  check(!RC::hasCurrentBody(item) && !RC::hasReadableBody(item), "obsolete marker rejected");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 1, "obsolete body invalidated and refetched");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS11\\n", 0) == 0, "refetched full body version");

  reset();
  H::replies.push_back({"<article>trop court</article>"});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && RC::hasReadableBody(item),
        "short extraction persists retriable fallback");
  reset();
  H::replies.push_back({std::string(RC::MAX_HTML_BYTES + 1, 'x')});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && RC::hasReadableBody(item),
        "oversized HTML persists retriable fallback");
  reset();
  testOom = true;
  check(fetch(item) == RC::CacheResult::FAILED && testFiles.empty(), "OOM without existing fallback drops metadata safely");

  reset();
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "seed fallback before failed replacement");
  const std::string fallbackBefore = testFiles[RC::bodyPath(item)];
  testWriteFail = true;
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles[RC::bodyPath(item)] == fallbackBefore,
        "failed full-body write preserves existing fallback");

  reset();
  testAuth = true;
  std::strcpy(item.link, "https://www.lefigaro.fr/test");
  check(fetch(item) == RC::CacheResult::FAILED && H::authCalls == 1 && H::publicCalls == 0,
        "AUTH failure never public fetch or summary fallback");
  check(load(item, out) == RC::CacheResult::FAILED && out.empty(), "AUTH failure no summary");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 0, "AUTH retry succeeds");

  reset(); item = makeItem(); H::replies.push_back({page}); testWriteFail = true;
  check(fetch(item) == RC::CacheResult::FAILED && testFiles.empty(), "body/fallback write failure is not retained");
  reset(); H::replies.push_back({page});
  int polls = 0;
  check(fetch(item, [&]{ return ++polls >= 3; }) == RC::CacheResult::CANCELLED && testFiles.empty(),
        "cancellation during fetch");
}

std::string readFile(const char* path) {
''',
    "cache/metadata tests")

test = Path("tests/rss/test_article_cache.cpp")
text = test.read_text()
text = text.replace("  htmlTests(); figaroCleanupTests(); cacheTests();\n",
                    "  htmlTests(); figaroCleanupTests(); metadataTests(); cacheTests();\n", 1)
old = '''    check(RC::load(item, "Frandroid", drop.c_str(), dropStart.c_str(), stop.c_str(), body) == RC::CacheResult::READY,
          "real Frandroid body loads");
'''
new = '''    check(RC::load(item, body) == RC::CacheResult::READY,
          "real Frandroid body loads");
'''
if text.count(old) != 1:
    raise SystemExit("real fixture load anchor mismatch")
text = text.replace(old, new, 1)
test.write_text(text)

# Sanity checks catch accidental retention of the old 4 KiB history payload or
# the #259 feed-scratch/history overflow pattern before compilation.
activity_h_text = Path("src/activities/home/RssNewsActivity.h").read_text()
activity_cpp_text = Path("src/activities/home/RssNewsActivity.cpp").read_text()
policy_text = Path("src/activities/home/RssArticleCachePolicy.inc").read_text()
checks = {
    "history uses lightweight record": "using CachedArticle = RssArticleMetadata::Record;" in activity_h_text,
    "history cache version bumped": "CACHE_VERSION = 5" in activity_h_text,
    "no historical RssItem payload": "RssItem item{}" not in activity_h_text,
    "merge no longer appends history into feed scratch": "items[mergedCount++] = articles" not in activity_cpp_text,
    "feed scratch released": activity_cpp_text.count("releaseFeedBuffer();") >= 2,
    "fallback persisted": "FALLBACK_MAGIC" in policy_text,
    "old load-time fallback builder removed": "return buildFallbackText(item" not in policy_text,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("candidate validation failed: " + ", ".join(failed))

print("Applied lightweight RSS history + persisted fallback + transient feed scratch.")
