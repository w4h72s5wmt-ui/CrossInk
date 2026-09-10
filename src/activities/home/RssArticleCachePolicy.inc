// RSS-local fetch/cache policy. Included in namespace RssArticleCache.
// Only extracted article bodies are persisted. Summaries already exist in
// RssItem and are prepared on opening, never mistaken for a cached article.
namespace {
bool buildFallbackText(const RssItem& item, const char* sourceName, const char* dropRules,
                       const char* dropStartRules, const char* stopRules, std::string& outText) {
  outText.clear();
  if (RssFigaroAuth::isConfiguredFor(item.link)) return false;
  const size_t sourceLength = std::strlen(item.summary);
  if (sourceLength == 0) return false;
  auto storage = allocateBuffer(sourceLength + 1);
  if (!storage) return false;
  char* text = reinterpret_cast<char*>(storage.get());
  std::memcpy(text, item.summary, sourceLength + 1);
  size_t length = sanitizeFallbackMarkup(text, sourceLength);
  length = removeFallbackUrls(text, length);
  length = fallbackRuleCutoff(text, length, stopRules);
  text[length] = '\0';
  length = cleanExtractedText(text, length, item.title, nullptr, sourceName, item.link,
                              dropRules, dropStartRules, stopRules);
  outText.assign(text, length);
  return !outText.empty();
}
}  // namespace

CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                         const char* dropStartRules, const char* stopRules,
                         const CancelCallback& shouldCancel) {
  if (shouldCancel && shouldCancel()) return CacheResult::CANCELLED;
  const bool useFigaroAuth = RssFigaroAuth::isConfiguredFor(item.link);
  const std::string path = bodyPath(item);
  if (bodyCacheIsCurrent(path)) return CacheResult::READY;
  if (Storage.exists(path.c_str())) Storage.remove(path.c_str());

  const auto unavailable = [&]() {
    if (useFigaroAuth) {
      LOG_ERR("RSS", "Figaro AUTH failed; no public fallback cached: %s", item.link);
      return CacheResult::FAILED;
    }
    LOG_ERR("RSS", "Body unavailable; summary only, retry on manual refresh: %s", item.link);
    return item.summary[0] ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  };
  if (!item.link[0]) return unavailable();

  auto htmlStorage = allocateBuffer(MAX_HTML_BYTES + 1);
  auto textStorage = allocateBuffer(MAX_TEXT_BYTES + 1);
  if (!htmlStorage || !textStorage) {
    LOG_ERR("RSS", "OOM allocating article extraction buffers");
    return unavailable();
  }
  char* html = reinterpret_cast<char*>(htmlStorage.get());
  char* text = reinterpret_cast<char*>(textStorage.get());
  static constexpr HttpDownloader::Transport TRANSPORTS[] = {
      HttpDownloader::Transport::WOLFSSL, HttpDownloader::Transport::ESP_HTTP,
  };
  const size_t attemptCount = useFigaroAuth ? 1U : 2U;
  for (size_t attempt = 0; attempt < attemptCount; ++attempt) {
    const char* transportName = useFigaroAuth ? "Figaro auth" : (attempt == 0 ? "wolfSSL" : "ESP_HTTP");
    size_t htmlLength = 0;
    bool htmlTruncated = false;
    const auto receiveChunk = [&](const uint8_t* data, const size_t len) {
      if (len > MAX_HTML_BYTES - htmlLength) { htmlTruncated = true; return false; }
      if (len > 0) {
        if (!data) return false;
        std::memcpy(html + htmlLength, data, len);
        htmlLength += len;
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
    if (result == HttpDownloader::ABORTED || (shouldCancel && shouldCancel())) return CacheResult::CANCELLED;
    if (result != HttpDownloader::OK || htmlLength == 0 || htmlTruncated) {
      LOG_ERR("RSS", "Fetch failed (%s, result=%d, bytes=%zu, truncated=%d): %s",
              transportName, static_cast<int>(result), htmlLength, htmlTruncated, item.link);
      continue;
    }
    html[htmlLength] = '\0';
    size_t textLength = 0;
    if (!extractReadableText(html, htmlLength, text, textLength) || textLength >= MAX_TEXT_BYTES) {
      LOG_ERR("RSS", "Extraction failed/at capacity (%s, html=%zu, text=%zu): %s",
              transportName, htmlLength, textLength, item.link);
      continue;
    }
    const size_t extractedLength = textLength;
    // The reader does not display the feed summary alongside a cached body.
    // Keep its first paragraph; real duplicated lines are still deduplicated.
    textLength = cleanExtractedText(text, textLength, item.title, nullptr, sourceName, item.link,
                                    dropRules, dropStartRules, stopRules);
    LOG_DBG("RSS", "Extraction (%s): html=%zu text=%zu cleaned=%zu", transportName, htmlLength,
            extractedLength, textLength);
    if (textLength < MIN_EXTRACTED_TEXT) {
      LOG_ERR("RSS", "Cleaner removed too much text (%s, before=%zu, after=%zu): %s",
              transportName, extractedLength, textLength, item.link);
      continue;
    }
    if (shouldCancel && shouldCancel()) return CacheResult::CANCELLED;
    if (!writeTextFile(path, text, textLength)) {
      LOG_ERR("RSS", "Could not persist article body: %s", item.link);
      return unavailable();
    }
    return CacheResult::READY;
  }
  return unavailable();
}

CacheResult load(const RssItem& item, const char* sourceName, const char* dropRules,
                 const char* dropStartRules, const char* stopRules, std::string& outText) {
  outText.clear();
  const std::string path = bodyPath(item);
  FsFile file;
  if (Storage.exists(path.c_str()) && Storage.openFileForRead("RSS", path, file)) {
    char marker[BODY_MAGIC_BYTES] = {};
    const size_t size = static_cast<size_t>(file.size());
    const bool valid = size > BODY_MAGIC_BYTES && size <= BODY_MAGIC_BYTES + MAX_TEXT_BYTES &&
                       file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES) &&
                       std::memcmp(marker, BODY_MAGIC, BODY_MAGIC_BYTES) == 0;
    if (valid) {
      const size_t expected = size - BODY_MAGIC_BYTES;
      char buffer[768];
      while (outText.size() < expected) {
        const size_t want = std::min(expected - outText.size(), sizeof(buffer));
        const int count = file.read(buffer, want);
        if (count <= 0) break;
        outText.append(buffer, static_cast<size_t>(count));
      }
      file.close();
      if (outText.size() == expected) return CacheResult::READY;
    } else {
      file.close();
    }
    outText.clear();
    Storage.remove(path.c_str());
  }
  return buildFallbackText(item, sourceName, dropRules, dropStartRules, stopRules, outText)
             ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
}
