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

// Downloads and extracts readable HTML text when the body is not cached yet.
// If extraction/networking fails, the feed-provided body is persisted instead.
CacheResult ensureCached(const RssItem& item, const CancelCallback& shouldCancel);

// Loads the cached offline body. Returns false when no dedicated body file is
// available; callers can still fall back to item.summary for legacy entries.
bool load(const RssItem& item, std::string& outText);

}  // namespace RssArticleCache
