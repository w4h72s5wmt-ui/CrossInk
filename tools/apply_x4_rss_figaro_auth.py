from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"{label}: expected unique section boundaries")
    first = text.index(start)
    last = text.index(end, first)
    return text[:first] + replacement + text[last:]


# This is the existing Figaro integration step, not another stacked overlay.
# Keep the network implementation in RssFigaroAuth.cpp and replace the cache
# routine coherently after the existing SD-only cleanup integration.
path = Path("src/activities/home/RssArticleCache.cpp")
text = path.read_text()

# Absorb the old Build 214 duplicate-signature correction here.
duplicate = (
    "bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n" * 2
)
if text.count(duplicate) == 1:
    text = text.replace(duplicate, duplicate[:len(duplicate) // 2], 1)
elif text.count(duplicate) != 0:
    raise RuntimeError("RSS duplicated helper signature has unexpected shape")

text = replace_once(
    text,
    '#include "network/HttpDownloader.h"\n',
    '#include "network/HttpDownloader.h"\n#include "RssFigaroAuth.h"\n',
    "RSS Figaro auth include",
)

old_body_path = '''std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  char name[64];
'''
new_body_path = '''std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  const uint64_t authKey = RssFigaroAuth::cacheKeyFor(item.link);
  for (size_t i = 0; authKey != 0 && i < sizeof(authKey); ++i) {
    hash ^= static_cast<uint8_t>(authKey >> (i * 8U));
    hash *= 1099511628211ULL;
  }
  char name[64];
'''
text = replace_once(text, old_body_path, new_body_path, "RSS authenticated cache namespace")

ensure_cached = r'''CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                        const char* dropStartRules, const char* stopRules,
                        const CancelCallback& shouldCancel) {
  const bool useFigaroAuth = RssFigaroAuth::isConfiguredFor(item.link);
  const std::string path = bodyPath(item);
  if (bodyCacheIsCurrent(path)) return CacheResult::READY;
  if (Storage.exists(path.c_str())) Storage.remove(path.c_str());
  if (shouldCancel && shouldCancel()) return CacheResult::CANCELLED;

  // Guard every failure path, including allocation, extraction and SD writes.
  // AUTH must never persist a public RSS summary under an authenticated key.
  const auto persistCleanFallback = [&]() {
    if (useFigaroAuth) {
      LOG_ERR("RSS", "Figaro AUTH failed; no public fallback cached: %s", item.link);
      return CacheResult::FAILED;
    }
    return persistFallback(item, sourceName, dropRules, dropStartRules, stopRules)
               ? CacheResult::FALLBACK_READY
               : CacheResult::FAILED;
  };
  if (!item.link[0]) return persistCleanFallback();

  auto htmlStorage = allocateBuffer(MAX_HTML_BYTES + 1);
  auto textStorage = allocateBuffer(MAX_TEXT_BYTES + 1);
  if (!htmlStorage || !textStorage) {
    LOG_ERR("RSS", "OOM allocating article extraction buffers");
    return persistCleanFallback();
  }

  char* html = reinterpret_cast<char*>(htmlStorage.get());
  char* text = reinterpret_cast<char*>(textStorage.get());
  static constexpr HttpDownloader::Transport TRANSPORTS[] = {
      HttpDownloader::Transport::WOLFSSL,
      HttpDownloader::Transport::ESP_HTTP,
  };
  const size_t attemptCount = useFigaroAuth ? 1U : 2U;

  for (size_t attempt = 0; attempt < attemptCount; ++attempt) {
    const char* transportName = useFigaroAuth ? "Figaro auth" : (attempt == 0 ? "wolfSSL" : "ESP_HTTP");
    if (attempt > 0) LOG_DBG("RSS", "Retrying article with ESP_HTTP: %s", item.link);
    size_t htmlLength = 0;
    bool htmlTruncated = false;

    const auto receiveChunk = [&](const uint8_t* data, const size_t len) {
      const size_t remaining = MAX_HTML_BYTES - htmlLength;
      if (len > remaining) {
        htmlTruncated = true;
        if (useFigaroAuth) return false;
      }
      const size_t copyLength = std::min(remaining, len);
      if (copyLength > 0) {
        std::memcpy(html + htmlLength, data, copyLength);
        htmlLength += copyLength;
      }
      return true;
    };

    HttpDownloader::DownloadError result;
    if (useFigaroAuth) {
      result = RssFigaroAuth::streamUrl(item.link, receiveChunk, shouldCancel);
    } else {
      HttpDownloader::DownloadOptions options;
      options.bufferSize = HTTP_BUFFER_SIZE;
      options.transport = TRANSPORTS[attempt];
      options.shouldCancel = shouldCancel;
      result = HttpDownloader::streamUrl(item.link, receiveChunk, nullptr, "", "", std::move(options));
    }

    if (result == HttpDownloader::ABORTED) return CacheResult::CANCELLED;
    if (result != HttpDownloader::OK || htmlLength == 0 || (useFigaroAuth && htmlTruncated)) {
      LOG_ERR("RSS", "Article fetch failed (%s, truncated=%d): %s", transportName, htmlTruncated, item.link);
      continue;
    }
    html[htmlLength] = '\0';

    size_t textLength = 0;
    if (!extractReadableText(html, htmlLength, text, textLength)) {
      LOG_ERR("RSS", "Article extraction failed (%s): %s", transportName, item.link);
      continue;
    }
    if (useFigaroAuth && textLength >= MAX_TEXT_BYTES) {
      LOG_ERR("RSS", "Figaro AUTH exceeds text capacity; not cached: %s", item.link);
      return CacheResult::FAILED;
    }
    textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link,
                                    dropRules, dropStartRules, stopRules);
    if (textLength < MIN_EXTRACTED_TEXT) {
      LOG_ERR("RSS", "Article cleaner removed too much text (%s): %s", transportName, item.link);
      continue;
    }
    if (htmlTruncated) LOG_DBG("RSS", "HTML truncated safely for %s", item.link);

    if (!writeTextFile(path, text, textLength)) {
      LOG_ERR("RSS", "Could not persist article body: %s", item.link);
      return persistCleanFallback();
    }
    return CacheResult::READY;
  }

  return persistCleanFallback();
}

'''
text = replace_section(
    text,
    "CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,\n",
    "bool load(const RssItem& item, std::string& outText) {\n",
    ensure_cached,
    "RSS strict authenticated cache routine",
)

for required in (
    '#include "RssFigaroAuth.h"',
    "RssFigaroAuth::cacheKeyFor(item.link)",
    "RssFigaroAuth::streamUrl(item.link, receiveChunk, shouldCancel)",
    "const size_t attemptCount = useFigaroAuth ? 1U : 2U;",
    "Figaro AUTH failed; no public fallback cached",
):
    if required not in text:
        raise RuntimeError(f"RSS Figaro integration missing: {required}")
if duplicate in text:
    raise RuntimeError("RSS Build 214 duplicate helper fix was not absorbed")
path.write_text(text)

# Keep the existing refresh-scoped lifetime: no TLS or cookie retained while
# reading offline, including when refresh exits through cancellation/failure.
news_path = Path("src/activities/home/RssNewsActivity.cpp")
news = news_path.read_text()
news = replace_once(
    news,
    '#include "RssArticleCache.h"\n',
    '#include "RssArticleCache.h"\n#include "RssFigaroAuth.h"\n',
    "RSS Figaro refresh session include",
)
news = replace_once(
    news,
    'void RssNewsActivity::refreshFeeds() {\n',
    '''void RssNewsActivity::refreshFeeds() {
  RssFigaroAuth::resetSession();
  struct FigaroSessionScope {
    ~FigaroSessionScope() { RssFigaroAuth::resetSession(); }
  } figaroSessionScope;
''',
    "RSS Figaro refresh session scope",
)
news_path.write_text(news)

print("Applied X4 Pro Figaro auth: explicit stream, strict AUTH cache, no anonymous rescue.")
