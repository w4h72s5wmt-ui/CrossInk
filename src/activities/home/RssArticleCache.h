#pragma once

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
