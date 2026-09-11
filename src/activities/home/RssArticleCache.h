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

using CancelCallback = std::function<bool()>;

// Returns a stable SD path derived from the article URL (or title/date when a
// feed does not provide a URL). The article body itself is stored separately
// from the RSS metadata cache so hundreds of entries do not consume PSRAM.
std::string bodyPath(const RssItem& item);

// Removes the dedicated offline body for an article. Missing files count as
// success so callers can prune history without special cases.
bool remove(const RssItem& item);

// Downloads and extracts readable HTML text when the body is not cached yet.
// A failure leaves no body file; the feed summary remains in RSS metadata
// and a subsequent manual refresh retries this article.
CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                        const char* dropStartRules, const char* stopRules,
                        const CancelCallback& shouldCancel);

// Loads a current body (READY), or prepares the feed summary (FALLBACK_READY)
// without persisting it. AUTH never substitutes a public summary.
CacheResult load(const RssItem& item, const char* sourceName, const char* dropRules,
                 const char* dropStartRules, const char* stopRules, std::string& outText);

}  // namespace RssArticleCache
