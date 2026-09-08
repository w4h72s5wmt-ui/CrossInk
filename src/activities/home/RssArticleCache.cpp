#include "RssArticleCache.h"

#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "network/HttpDownloader.h"

namespace RssArticleCache {
namespace {
constexpr char CACHE_DIR[] = "/.crosspoint/rss_articles";
constexpr size_t MAX_HTML_BYTES = 1536U * 1024U;
constexpr size_t MAX_TEXT_BYTES = 48U * 1024U;
constexpr size_t HTTP_BUFFER_SIZE = 4096;
constexpr size_t MIN_EXTRACTED_TEXT = 180;

HeapByteBuffer allocateBuffer(const size_t bytes) {
  auto buffer = makePsramByteBufferNoThrow(bytes);
  if (!buffer) buffer = makeHeapByteBufferNoThrow(bytes);
  return buffer;
}

uint64_t fnv1a64(const char* text, uint64_t hash = 14695981039346656037ULL) {
  if (!text) return hash;
  while (*text) {
    hash ^= static_cast<uint8_t>(*text++);
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool asciiEqual(const char left, const char right) {
  return std::tolower(static_cast<unsigned char>(left)) == std::tolower(static_cast<unsigned char>(right));
}

size_t findInsensitive(const char* data, const size_t length, const char* needle, const size_t start = 0) {
  const size_t needleLength = std::strlen(needle);
  if (!data || needleLength == 0 || length < needleLength || start >= length) return std::string::npos;
  for (size_t i = start; i + needleLength <= length; ++i) {
    size_t j = 0;
    while (j < needleLength && asciiEqual(data[i + j], needle[j])) ++j;
    if (j == needleLength) return i;
  }
  return std::string::npos;
}

bool startsWithInsensitive(const char* data, const size_t length, const size_t pos, const char* needle) {
  const size_t needleLength = std::strlen(needle);
  if (!data || pos + needleLength > length) return false;
  for (size_t i = 0; i < needleLength; ++i) {
    if (!asciiEqual(data[pos + i], needle[i])) return false;
  }
  return true;
}

void appendChar(char* out, size_t& outLength, const char value) {
  if (outLength >= MAX_TEXT_BYTES) return;
  out[outLength++] = value;
}

void appendSpace(char* out, size_t& outLength) {
  if (outLength == 0) return;
  if (out[outLength - 1] != ' ' && out[outLength - 1] != '\n') appendChar(out, outLength, ' ');
}

void appendNewline(char* out, size_t& outLength) {
  while (outLength > 0 && out[outLength - 1] == ' ') --outLength;
  if (outLength == 0 || out[outLength - 1] == '\n') return;
  appendChar(out, outLength, '\n');
}

bool isBlockTag(const char* data, const size_t length, const size_t tagStart) {
  size_t pos = tagStart;
  if (pos < length && data[pos] == '/') ++pos;
  return startsWithInsensitive(data, length, pos, "p") || startsWithInsensitive(data, length, pos, "br") ||
         startsWithInsensitive(data, length, pos, "div") || startsWithInsensitive(data, length, pos, "li") ||
         startsWithInsensitive(data, length, pos, "h1") || startsWithInsensitive(data, length, pos, "h2") ||
         startsWithInsensitive(data, length, pos, "h3") || startsWithInsensitive(data, length, pos, "h4") ||
         startsWithInsensitive(data, length, pos, "h5") || startsWithInsensitive(data, length, pos, "h6") ||
         startsWithInsensitive(data, length, pos, "section") || startsWithInsensitive(data, length, pos, "article");
}

size_t decodeEntity(const char* data, const size_t length, const size_t pos, char* out, size_t& outLength) {
  const size_t semicolon = [&]() {
    const size_t maxEnd = std::min(length, pos + 12);
    for (size_t i = pos + 1; i < maxEnd; ++i) {
      if (data[i] == ';') return i;
      if (data[i] == '<' || data[i] == '&' || std::isspace(static_cast<unsigned char>(data[i]))) break;
    }
    return std::string::npos;
  }();
  if (semicolon == std::string::npos) {
    appendChar(out, outLength, '&');
    return pos + 1;
  }

  const std::string entity(data + pos + 1, semicolon - pos - 1);
  if (entity == "amp") appendChar(out, outLength, '&');
  else if (entity == "lt") appendChar(out, outLength, '<');
  else if (entity == "gt") appendChar(out, outLength, '>');
  else if (entity == "quot") appendChar(out, outLength, '"');
  else if (entity == "apos" || entity == "#39") appendChar(out, outLength, '\'');
  else if (entity == "nbsp") appendSpace(out, outLength);
  else if (!entity.empty() && entity[0] == '#') {
    unsigned value = 0;
    const bool hex = entity.size() > 2 && (entity[1] == 'x' || entity[1] == 'X');
    if (std::sscanf(entity.c_str() + (hex ? 2 : 1), hex ? "%x" : "%u", &value) == 1 && value >= 0x20 && value <= 0x7e) {
      appendChar(out, outLength, static_cast<char>(value));
    } else {
      appendSpace(out, outLength);
    }
  } else {
    appendSpace(out, outLength);
  }
  return semicolon + 1;
}

bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {
  textLength = 0;
  if (!html || !text || htmlLength == 0) return false;

  size_t rangeStart = 0;
  size_t rangeEnd = htmlLength;
  const struct Candidate {
    const char* open;
    const char* close;
  } candidates[] = {{"<article", "</article>"}, {"<main", "</main>"}, {"<body", "</body>"}};
  for (const auto& candidate : candidates) {
    const size_t start = findInsensitive(html, htmlLength, candidate.open);
    if (start == std::string::npos) continue;
    const size_t openEnd = findInsensitive(html, htmlLength, ">", start);
    if (openEnd == std::string::npos) continue;
    const size_t end = findInsensitive(html, htmlLength, candidate.close, openEnd + 1);
    rangeStart = openEnd + 1;
    rangeEnd = end == std::string::npos ? htmlLength : end;
    break;
  }

  size_t i = rangeStart;
  while (i < rangeEnd && textLength < MAX_TEXT_BYTES) {
    if (html[i] == '<') {
      if (startsWithInsensitive(html, rangeEnd, i, "<script") || startsWithInsensitive(html, rangeEnd, i, "<style") ||
          startsWithInsensitive(html, rangeEnd, i, "<noscript") || startsWithInsensitive(html, rangeEnd, i, "<svg") ||
          startsWithInsensitive(html, rangeEnd, i, "<form")) {
        const char* closing = startsWithInsensitive(html, rangeEnd, i, "<script")   ? "</script>"
                              : startsWithInsensitive(html, rangeEnd, i, "<style")  ? "</style>"
                              : startsWithInsensitive(html, rangeEnd, i, "<noscript") ? "</noscript>"
                              : startsWithInsensitive(html, rangeEnd, i, "<svg")    ? "</svg>"
                                                                                      : "</form>";
        const size_t end = findInsensitive(html, rangeEnd, closing, i + 1);
        i = end == std::string::npos ? rangeEnd : end + std::strlen(closing);
        continue;
      }
      const size_t tagEnd = findInsensitive(html, rangeEnd, ">", i + 1);
      if (tagEnd == std::string::npos) break;
      if (isBlockTag(html, rangeEnd, i + 1)) appendNewline(text, textLength);
      i = tagEnd + 1;
      continue;
    }
    if (html[i] == '&') {
      i = decodeEntity(html, rangeEnd, i, text, textLength);
      continue;
    }
    const unsigned char c = static_cast<unsigned char>(html[i]);
    if (c == '\r' || c == '\n' || c == '\t' || c == '\f') {
      appendSpace(text, textLength);
      ++i;
      continue;
    }
    if (c < 0x20) {
      ++i;
      continue;
    }
    if (c == ' ') appendSpace(text, textLength);
    else appendChar(text, textLength, static_cast<char>(c));
    ++i;
  }

  while (textLength > 0 && (text[textLength - 1] == ' ' || text[textLength - 1] == '\n')) --textLength;
  text[textLength] = '\0';
  return textLength >= MIN_EXTRACTED_TEXT;
}

bool writeTextFile(const std::string& path, const char* text, const size_t length) {
  if (!text || length == 0) return false;
  Storage.ensureDirectoryExists("/.crosspoint");
  Storage.ensureDirectoryExists(CACHE_DIR);
  const std::string tempPath = path + ".tmp";
  Storage.remove(tempPath.c_str());

  FsFile file;
  if (!Storage.openFileForWrite("RSS", tempPath, file)) return false;
  const size_t written = file.write(reinterpret_cast<const uint8_t*>(text), length);
  const bool synced = written == length && file.sync();
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

bool persistFallback(const RssItem& item) {
  const size_t length = std::strlen(item.summary);
  return length > 0 && writeTextFile(bodyPath(item), item.summary, length);
}
}  // namespace

std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  char name[64];
  std::snprintf(name, sizeof(name), "%s/%016llx.txt", CACHE_DIR, static_cast<unsigned long long>(hash));
  return name;
}

CacheResult ensureCached(const RssItem& item, const CancelCallback& shouldCancel) {
  const std::string path = bodyPath(item);
  if (Storage.exists(path.c_str())) return CacheResult::READY;
  if (shouldCancel && shouldCancel()) return CacheResult::CANCELLED;

  if (!item.link[0]) return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;

  auto htmlStorage = allocateBuffer(MAX_HTML_BYTES + 1);
  auto textStorage = allocateBuffer(MAX_TEXT_BYTES + 1);
  if (!htmlStorage || !textStorage) {
    LOG_ERR("RSS", "OOM allocating article extraction buffers");
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }

  char* html = reinterpret_cast<char*>(htmlStorage.get());
  char* text = reinterpret_cast<char*>(textStorage.get());
  size_t htmlLength = 0;
  bool htmlTruncated = false;

  HttpDownloader::DownloadOptions options;
  options.bufferSize = HTTP_BUFFER_SIZE;
  options.transport = HttpDownloader::Transport::WOLFSSL;
  options.shouldCancel = shouldCancel;
  const auto result = HttpDownloader::streamUrl(
      item.link,
      [&](const uint8_t* data, const size_t len) {
        const size_t remaining = MAX_HTML_BYTES - htmlLength;
        const size_t copyLength = std::min(remaining, len);
        if (copyLength > 0) {
          std::memcpy(html + htmlLength, data, copyLength);
          htmlLength += copyLength;
        }
        if (copyLength < len) htmlTruncated = true;
        return true;
      },
      nullptr, "", "", std::move(options));

  if (result == HttpDownloader::ABORTED && shouldCancel && shouldCancel()) return CacheResult::CANCELLED;
  if (result != HttpDownloader::OK || htmlLength == 0) {
    LOG_ERR("RSS", "Article fetch failed: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  html[htmlLength] = '\0';

  size_t textLength = 0;
  if (!extractReadableText(html, htmlLength, text, textLength)) {
    LOG_ERR("RSS", "Article extraction failed: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  if (htmlTruncated) LOG_DBG("RSS", "HTML truncated safely for %s", item.link);

  if (!writeTextFile(path, text, textLength)) {
    LOG_ERR("RSS", "Could not persist article body: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  return CacheResult::READY;
}

bool load(const RssItem& item, std::string& outText) {
  outText.clear();
  const std::string path = bodyPath(item);
  if (!Storage.exists(path.c_str())) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return false;
  char buffer[768];
  while (outText.size() < MAX_TEXT_BYTES) {
    const size_t remaining = MAX_TEXT_BYTES - outText.size();
    const size_t want = std::min(remaining, sizeof(buffer));
    const int read = file.read(buffer, want);
    if (read <= 0) break;
    outText.append(buffer, static_cast<size_t>(read));
  }
  file.close();
  return !outText.empty();
}

}  // namespace RssArticleCache
