// RSS-local fetch/cache policy. Included in namespace RssArticleCache.
// Only extracted article bodies are persisted. Summaries already exist in
// RssItem and are prepared on opening, never mistaken for a cached article.
namespace {
bool isFigaroPolicyUrl(const char* articleUrl) {
  if (!articleUrl || !articleUrl[0]) return false;
  return findInsensitive(articleUrl, std::strlen(articleUrl), "lefigaro.fr") != std::string::npos;
}

// Figaro injects gift/save/error UI inside the editorial <article>. On some
// page variants all of that UI is flattened onto one long extracted line, so
// the normal short-line noise filter cannot remove it. Require multiple strong
// UI markers near the beginning, then cut only through the last known UI tail
// and preserve the editorial suffix byte-for-byte.
size_t stripFigaroUiPreamble(char* text, size_t length, const char* articleUrl) {
  if (!text || length == 0 || !isFigaroPolicyUrl(articleUrl)) return length;

  const size_t scanLimit = std::min(length, static_cast<size_t>(3200));
  static constexpr const char* MARKERS[] = {
      "Offrir l'article",
      "Vous pourrez à nouveau offrir",
      "Vous pourrez a nouveau offrir",
      "articles à offrir ce mois",
      "articles a offrir ce mois",
      "Le contenu n'a pas pu être chargé",
      "Le contenu n'a pas pu etre charge",
      "Sauvegarder un article",
      "Nouvelle fonctionnalité",
      "Nouvelle fonctionnalite",
      "sauvegarder des articles pour les lire plus tard",
  };

  size_t first = std::string::npos;
  size_t hits = 0;
  for (const char* marker : MARKERS) {
    const size_t found = findInsensitive(text, scanLimit, marker);
    if (found == std::string::npos) continue;
    first = std::min(first, found);
    ++hits;
  }
  if (hits < 2 || first == std::string::npos || first > 1800) return length;

  size_t cut = first;
  const auto extendThrough = [&](const char* marker) {
    const size_t found = findInsensitive(text, scanLimit, marker, first);
    if (found != std::string::npos) cut = std::max(cut, found + std::strlen(marker));
  };

  extendThrough("Créer un compte Se connecter");
  extendThrough("Creer un compte Se connecter");
  extendThrough("Pour sauvegarder un article vous devez être connecté, vous pourrez ainsi les consulter sur tous vos appareils.");
  extendThrough("Pour sauvegarder un article vous devez etre connecte, vous pourrez ainsi les consulter sur tous vos appareils.");
  extendThrough("Avec votre compte, vous pouvez désormais sauvegarder des articles pour les lire plus tard sur tous vos appareils.");
  extendThrough("Avec votre compte, vous pouvez desormais sauvegarder des articles pour les lire plus tard sur tous vos appareils.");
  extendThrough("Veuillez rafraîchir la page.");
  extendThrough("Veuillez rafraichir la page.");

  if (cut <= first || cut >= length) return cut >= length ? 0 : length;
  while (cut < length && std::isspace(static_cast<unsigned char>(text[cut]))) ++cut;
  if (cut >= length) return 0;

  const size_t remaining = length - cut;
  std::memmove(text, text + cut, remaining);
  text[remaining] = '\0';
  return remaining;
}

// Figaro may flatten the share bar directly against the first editorial word,
// e.g. "-Lien copié- Mail- X- MessengerBenjamin...". A line-based feed rule
// would delete the article opening too. Require the ordered share labels near
// the start and cut exactly through "Messenger", preserving the suffix bytes.
size_t stripFigaroSharePrefix(char* text, size_t length, const char* articleUrl) {
  if (!text || length == 0 || !isFigaroPolicyUrl(articleUrl)) return length;

  const size_t scanLimit = std::min(length, static_cast<size_t>(320));
  size_t copied = findInsensitive(text, scanLimit, "Lien copié");
  if (copied == std::string::npos) copied = findInsensitive(text, scanLimit, "Lien copie");
  if (copied == std::string::npos || copied > 64) return length;

  const size_t mail = findInsensitive(text, scanLimit, "Mail", copied + 4);
  if (mail == std::string::npos || mail <= copied || mail > copied + 80) return length;

  const size_t messenger = findInsensitive(text, scanLimit, "Messenger", mail + 4);
  if (messenger == std::string::npos || messenger <= mail || messenger > mail + 96) return length;

  size_t cut = messenger + std::strlen("Messenger");
  while (cut < length && std::isspace(static_cast<unsigned char>(text[cut]))) ++cut;
  if (cut >= length) return 0;

  const size_t remaining = length - cut;
  std::memmove(text, text + cut, remaining);
  text[remaining] = '\0';
  return remaining;
}

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
  RssFetchDiagnostics::Record diagnostic;
  diagnostic.startedMs = RssFetchDiagnostics::now();
  const auto report = [&](const char* phase, const int result) {
    diagnostic.phase = phase;
    diagnostic.result = result;
    RssFetchDiagnostics::write(item.link, diagnostic);
  };
  if (shouldCancel && shouldCancel()) return CacheResult::CANCELLED;
  const bool useFigaroAuth = RssFigaroAuth::isConfiguredFor(item.link);
  const std::string path = bodyPath(item);
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
  if (!item.link[0]) {
    report("no-url", HttpDownloader::HTTP_ERROR);
    return unavailable();
  }

  auto htmlStorage = allocateBuffer(MAX_HTML_BYTES + 1);
  auto textStorage = allocateBuffer(MAX_TEXT_BYTES + 1);
  if (!htmlStorage || !textStorage) {
    LOG_ERR("RSS", "OOM allocating article extraction buffers");
    report("buffer-allocation", HttpDownloader::HTTP_ERROR);
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
    diagnostic = RssFetchDiagnostics::Record{};
    diagnostic.startedMs = RssFetchDiagnostics::now();
    diagnostic.transport = useFigaroAuth ? "auth-cache" : (attempt == 0 ? "wolfSSL" : "ESP_HTTP");
    size_t htmlLength = 0;
    bool htmlTruncated = false;
    const auto receiveChunk = [&](const uint8_t* data, const size_t len) {
      diagnostic.received += len;
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
    diagnostic.stored = htmlLength;
    diagnostic.truncated = htmlTruncated;
    if (result == HttpDownloader::ABORTED || (shouldCancel && shouldCancel())) {
      report("cancelled", HttpDownloader::ABORTED);
      return CacheResult::CANCELLED;
    }
    if (result != HttpDownloader::OK || htmlLength == 0 || htmlTruncated) {
      LOG_ERR("RSS", "Fetch failed (%s, result=%d, bytes=%zu, truncated=%d): %s",
              transportName, static_cast<int>(result), htmlLength, htmlTruncated, item.link);
      report(htmlTruncated ? "html-capacity" : "fetch", result);
      continue;
    }
    html[htmlLength] = '\0';
    size_t textLength = 0;
    const bool extracted = extractReadableText(html, htmlLength, text, textLength);
    diagnostic.extracted = textLength;
    if (!extracted || textLength >= MAX_TEXT_BYTES) {
      LOG_ERR("RSS", "Extraction failed/at capacity (%s, html=%zu, text=%zu): %s",
              transportName, htmlLength, textLength, item.link);
      report(textLength >= MAX_TEXT_BYTES ? "text-capacity" : "extraction", HttpDownloader::HTTP_ERROR);
      continue;
    }
    const size_t extractedLength = textLength;
    textLength = cleanExtractedText(text, textLength, item.title, nullptr, sourceName, item.link,
                                    dropRules, dropStartRules, stopRules);
    textLength = stripFigaroUiPreamble(text, textLength, item.link);
    textLength = stripFigaroSharePrefix(text, textLength, item.link);
    diagnostic.cleaned = textLength;
    LOG_DBG("RSS", "Extraction (%s): html=%zu text=%zu cleaned=%zu", transportName, htmlLength,
            extractedLength, textLength);
    if (textLength < MIN_EXTRACTED_TEXT) {
      LOG_ERR("RSS", "Cleaner removed too much text (%s, before=%zu, after=%zu): %s",
              transportName, extractedLength, textLength, item.link);
      report("cleaner", HttpDownloader::HTTP_ERROR);
      continue;
    }
    if (shouldCancel && shouldCancel()) {
      report("cancelled", HttpDownloader::ABORTED);
      return CacheResult::CANCELLED;
    }
    if (!writeTextFile(path, text, textLength)) {
      LOG_ERR("RSS", "Could not persist article body: %s", item.link);
      report("body-write", HttpDownloader::FILE_ERROR);
      return unavailable();
    }
    report("body-ready", HttpDownloader::OK);
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
