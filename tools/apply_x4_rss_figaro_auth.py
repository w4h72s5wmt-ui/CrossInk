from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("src/activities/home/RssArticleCache.cpp")
text = path.read_text()

# Absorb the old Build 214 micro-fix here so the workflow no longer needs a
# separate stacked patch.
duplicate = '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\nbool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n'''
if text.count(duplicate) == 1:
    text = text.replace(
        duplicate,
        '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n''',
        1,
    )
elif text.count(duplicate) != 0:
    raise RuntimeError("RSS duplicated helper signature has unexpected shape")

text = replace_once(
    text,
    '#include "network/HttpDownloader.h"\n',
    '#include "network/HttpDownloader.h"\n#include "RssFigaroAuth.h"\n',
    "RSS Figaro auth include",
)

old_body_path = '''std::string bodyPath(const RssItem& item) {\n  uint64_t hash = fnv1a64(item.link);\n  if (!item.link[0]) {\n    hash = fnv1a64(item.title, hash);\n    hash = fnv1a64(item.published, hash);\n  }\n  char name[64];\n'''
new_body_path = '''std::string bodyPath(const RssItem& item) {\n  uint64_t hash = fnv1a64(item.link);\n  if (!item.link[0]) {\n    hash = fnv1a64(item.title, hash);\n    hash = fnv1a64(item.published, hash);\n  }\n  const uint64_t authKey = RssFigaroAuth::cacheKeyFor(item.link);\n  for (size_t i = 0; authKey != 0 && i < sizeof(authKey); ++i) {\n    hash ^= static_cast<uint8_t>(authKey >> (i * 8U));\n    hash *= 1099511628211ULL;\n  }\n  char name[64];\n'''
text = replace_once(text, old_body_path, new_body_path, "RSS authenticated cache namespace")

old_fetch = '''  static constexpr HttpDownloader::Transport TRANSPORTS[] = {\n      HttpDownloader::Transport::WOLFSSL,\n      HttpDownloader::Transport::ESP_HTTP,\n  };\n\n  for (size_t attempt = 0; attempt < 2; ++attempt) {\n    if (attempt > 0) LOG_DBG("RSS", "Retrying article with ESP_HTTP: %s", item.link);\n    size_t htmlLength = 0;\n    bool htmlTruncated = false;\n\n    HttpDownloader::DownloadOptions options;\n    options.bufferSize = HTTP_BUFFER_SIZE;\n    options.transport = TRANSPORTS[attempt];\n    options.shouldCancel = shouldCancel;\n    const auto result = HttpDownloader::streamUrl(\n        item.link,\n        [&](const uint8_t* data, const size_t len) {\n          const size_t remaining = MAX_HTML_BYTES - htmlLength;\n          const size_t copyLength = std::min(remaining, len);\n          if (copyLength > 0) {\n            std::memcpy(html + htmlLength, data, copyLength);\n            htmlLength += copyLength;\n          }\n          if (copyLength < len) htmlTruncated = true;\n          return true;\n        },\n        nullptr, "", "", std::move(options));\n'''

new_fetch = '''  static constexpr HttpDownloader::Transport TRANSPORTS[] = {\n      HttpDownloader::Transport::WOLFSSL,\n      HttpDownloader::Transport::ESP_HTTP,\n  };\n  const bool useFigaroAuth = RssFigaroAuth::isConfiguredFor(item.link);\n  const size_t attemptCount = 2U;\n\n  for (size_t attempt = 0; attempt < attemptCount; ++attempt) {\n    const bool authenticatedAttempt = useFigaroAuth && attempt == 0;\n    const size_t transportIndex = useFigaroAuth ? 0U : attempt;\n    const char* transportName = authenticatedAttempt ? "Figaro auth" :\n                                (transportIndex == 0 ? "wolfSSL" : "ESP_HTTP");\n    if (attempt > 0) LOG_DBG("RSS", "Retrying article fetch: %s", item.link);\n    size_t htmlLength = 0;\n    bool htmlTruncated = false;\n\n    const auto receiveChunk = [&](const uint8_t* data, const size_t len) {\n      const size_t remaining = MAX_HTML_BYTES - htmlLength;\n      const size_t copyLength = std::min(remaining, len);\n      if (copyLength > 0) {\n        std::memcpy(html + htmlLength, data, copyLength);\n        htmlLength += copyLength;\n      }\n      if (copyLength < len) htmlTruncated = true;\n      return true;\n    };\n\n    HttpDownloader::DownloadError result = HttpDownloader::HTTP_ERROR;\n    if (authenticatedAttempt) {\n      result = RssFigaroAuth::streamUrl(item.link, receiveChunk, shouldCancel);\n    } else {\n      HttpDownloader::DownloadOptions options;\n      options.bufferSize = HTTP_BUFFER_SIZE;\n      options.transport = TRANSPORTS[transportIndex];\n      options.shouldCancel = shouldCancel;\n      result = HttpDownloader::streamUrl(item.link, receiveChunk, nullptr, "", "", std::move(options));\n    }\n'''
text = replace_once(text, old_fetch, new_fetch, "RSS Figaro authenticated fetch attempt")

text = text.replace('attempt == 0 ? "wolfSSL" : "ESP_HTTP"', 'transportName')

# Once an authenticated HTTP 200 produced a body, an extraction/cleaning issue
# will not be fixed by downloading the public version of the same article.
text = text.replace(
    '''    if (!extractReadableText(html, htmlLength, text, textLength)) {\n      LOG_ERR("RSS", "Article extraction failed (%s): %s", transportName, item.link);\n      continue;\n    }\n''',
    '''    if (!extractReadableText(html, htmlLength, text, textLength)) {\n      LOG_ERR("RSS", "Article extraction failed (%s): %s", transportName, item.link);\n      if (authenticatedAttempt) return persistCleanFallback();\n      continue;\n    }\n''',
)
text = text.replace(
    '''    if (textLength < MIN_EXTRACTED_TEXT) {\n      LOG_ERR("RSS", "Article cleaner removed too much text (%s): %s",\n              transportName, item.link);\n      continue;\n    }\n''',
    '''    if (textLength < MIN_EXTRACTED_TEXT) {\n      LOG_ERR("RSS", "Article cleaner removed too much text (%s): %s",\n              transportName, item.link);\n      if (authenticatedAttempt) return persistCleanFallback();\n      continue;\n    }\n''',
)
text = text.replace(
    'LOG_ERR("RSS", "Both article transports failed; using cleaned feed fallback: %s", item.link);',
    'LOG_ERR("RSS", "Article fetch attempts failed; using cleaned feed fallback: %s", item.link);',
)

if '#include "RssFigaroAuth.h"' not in text:
    raise RuntimeError("RSS Figaro auth include missing")
if "RssFigaroAuth::cacheKeyFor(item.link)" not in text:
    raise RuntimeError("RSS authenticated cache namespace missing")
if "RssFigaroAuth::streamUrl(item.link, receiveChunk, shouldCancel)" not in text:
    raise RuntimeError("RSS authenticated fetch path missing")
if duplicate in text:
    raise RuntimeError("RSS Build 214 duplicate helper fix was not absorbed")

path.write_text(text)

# Bound the RSS-local TLS client to refreshFeeds itself. Match only the stable
# function signature because previous RSS overlays can rewrite its first body
# statements. The RAII scope releases TLS and cookie heap on every return path.
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
    '''void RssNewsActivity::refreshFeeds() {\n  RssFigaroAuth::resetSession();\n  struct FigaroSessionScope {\n    ~FigaroSessionScope() { RssFigaroAuth::resetSession(); }\n  } figaroSessionScope;\n''',
    "RSS Figaro refresh session scope",
)
news_path.write_text(news)

print("Applied X4 Pro Figaro auth with bounded refresh session and single anonymous rescue.")
