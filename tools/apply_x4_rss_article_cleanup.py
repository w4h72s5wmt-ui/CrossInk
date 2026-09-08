from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_pos] + replacement + text[end_pos:]


# ---------------------------------------------------------------------------
# Article body cache: version the plain-text files, preserve paragraph/list
# structure, filter common web chrome/ad/recommendation blocks, and deduplicate
# repeated lines without allocating another article-sized buffer.
# ---------------------------------------------------------------------------
cache_header_path = Path("src/activities/home/RssArticleCache.h")
cache_header = cache_header_path.read_text()
cache_header = replace_once(
    cache_header,
    '''std::string bodyPath(const RssItem& item);

// Downloads and extracts readable HTML text when the body is not cached yet.
''',
    '''std::string bodyPath(const RssItem& item);

// Removes the dedicated offline body for an article. Missing files count as
// success so callers can prune history without special cases.
bool remove(const RssItem& item);

// Downloads and extracts readable HTML text when the body is not cached yet.
''',
    "RSS article body removal API",
)
cache_header_path.write_text(cache_header)

cache_cpp_path = Path("src/activities/home/RssArticleCache.cpp")
cache_cpp = cache_cpp_path.read_text()
cache_cpp = replace_once(
    cache_cpp,
    '''constexpr char CACHE_DIR[] = "/.crosspoint/rss_articles";
constexpr size_t MAX_HTML_BYTES = 1536U * 1024U;
''',
    '''constexpr char CACHE_DIR[] = "/.crosspoint/rss_articles";
// Plain-text cache format marker. Bumping this invalidates old extracted text
// after the cleaner changes, while keeping files human-readable on the SD card.
constexpr char BODY_MAGIC[] = "XRSS2\\n";
constexpr size_t BODY_MAGIC_BYTES = sizeof(BODY_MAGIC) - 1;
constexpr size_t MAX_HTML_BYTES = 1536U * 1024U;
''',
    "RSS article body cache version marker",
)

cleaner_helpers = r'''void appendSpace(char* out, size_t& outLength) {
  if (outLength == 0) return;
  if (out[outLength - 1] != ' ' && out[outLength - 1] != '\n') appendChar(out, outLength, ' ');
}

void trimTrailingSpaces(char* out, size_t& outLength) {
  while (outLength > 0 && out[outLength - 1] == ' ') --outLength;
}

void appendLineBreak(char* out, size_t& outLength) {
  trimTrailingSpaces(out, outLength);
  if (outLength == 0 || out[outLength - 1] == '\n') return;
  appendChar(out, outLength, '\n');
}

void appendParagraphBreak(char* out, size_t& outLength) {
  trimTrailingSpaces(out, outLength);
  if (outLength == 0) return;
  if (out[outLength - 1] != '\n') appendChar(out, outLength, '\n');
  if (outLength < 2 || out[outLength - 2] != '\n') appendChar(out, outLength, '\n');
}

bool rangeContainsInsensitive(const char* data, const size_t start, const size_t end, const char* needle) {
  if (!data || !needle || start >= end) return false;
  const size_t needleLength = std::strlen(needle);
  if (needleLength == 0 || end - start < needleLength) return false;
  for (size_t i = start; i + needleLength <= end; ++i) {
    size_t j = 0;
    while (j < needleLength && asciiEqual(data[i + j], needle[j])) ++j;
    if (j == needleLength) return true;
  }
  return false;
}

size_t parseTagName(const char* data, const size_t tagStart, const size_t tagEnd, char* name, const size_t nameSize,
                    bool& closing, bool& selfClosing) {
  closing = false;
  selfClosing = false;
  if (!data || !name || nameSize < 2 || tagStart >= tagEnd) return 0;
  size_t pos = tagStart + 1;
  while (pos < tagEnd && std::isspace(static_cast<unsigned char>(data[pos]))) ++pos;
  if (pos < tagEnd && data[pos] == '/') {
    closing = true;
    ++pos;
    while (pos < tagEnd && std::isspace(static_cast<unsigned char>(data[pos]))) ++pos;
  }
  if (pos >= tagEnd || data[pos] == '!' || data[pos] == '?') return 0;

  size_t length = 0;
  while (pos < tagEnd && length + 1 < nameSize) {
    const unsigned char c = static_cast<unsigned char>(data[pos]);
    if (!(std::isalnum(c) || c == '-' || c == ':')) break;
    name[length++] = static_cast<char>(std::tolower(c));
    ++pos;
  }
  name[length] = '\0';

  size_t tail = tagEnd;
  while (tail > tagStart + 1 && std::isspace(static_cast<unsigned char>(data[tail - 1]))) --tail;
  selfClosing = tail > tagStart + 1 && data[tail - 1] == '/';
  return length;
}

bool tagEquals(const char* name, const char* expected) {
  return name && expected && std::strcmp(name, expected) == 0;
}

bool isParagraphTag(const char* name) {
  return tagEquals(name, "p") || tagEquals(name, "div") || tagEquals(name, "section") ||
         tagEquals(name, "article") || tagEquals(name, "blockquote") || tagEquals(name, "figure") ||
         tagEquals(name, "figcaption") || tagEquals(name, "ul") || tagEquals(name, "ol") ||
         tagEquals(name, "table") || tagEquals(name, "h1") || tagEquals(name, "h2") ||
         tagEquals(name, "h3") || tagEquals(name, "h4") || tagEquals(name, "h5") || tagEquals(name, "h6");
}

bool isAlwaysSkippedTag(const char* name) {
  return tagEquals(name, "script") || tagEquals(name, "style") || tagEquals(name, "noscript") ||
         tagEquals(name, "svg") || tagEquals(name, "form") || tagEquals(name, "iframe") ||
         tagEquals(name, "template") || tagEquals(name, "canvas") || tagEquals(name, "button") ||
         tagEquals(name, "nav") || tagEquals(name, "footer") || tagEquals(name, "aside") ||
         tagEquals(name, "header");
}

bool isNoiseContainer(const char* name, const char* data, const size_t tagStart, const size_t tagEnd) {
  if (isAlwaysSkippedTag(name)) return true;
  const bool container = tagEquals(name, "div") || tagEquals(name, "section") || tagEquals(name, "ul") ||
                         tagEquals(name, "ol") || tagEquals(name, "article");
  if (!container) return false;
  static constexpr const char* MARKERS[] = {
      "advert",       "publicit",     "sponsor",      "promo",       "outbrain",      "taboola",
      "related",      "recommend",    "newsletter",   "social",      "share",         "cookie",
      "consent",      "sidebar",      "breadcrumb",   "comment",     "paywall",       "subscription",
      "most-read",    "mostread",     "popular",      "trending",    "read-more",     "readmore",
      "also-read",    "suggest",      "teaser",       "cross-sell",  "native-ad",     "ad-container",
      "ad_container", "adslot",       "ad-slot",      "partner",     "affiliate",     "recommendation",
  };
  for (const char* marker : MARKERS) {
    if (rangeContainsInsensitive(data, tagStart, tagEnd, marker)) return true;
  }
  return false;
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

  char skippedTag[24] = {};
  int skipDepth = 0;
  size_t i = rangeStart;
  while (i < rangeEnd && textLength < MAX_TEXT_BYTES) {
    if (html[i] == '<') {
      if (startsWithInsensitive(html, rangeEnd, i, "<!--")) {
        const size_t commentEnd = findInsensitive(html, rangeEnd, "-->", i + 4);
        i = commentEnd == std::string::npos ? rangeEnd : commentEnd + 3;
        continue;
      }
      const size_t tagEnd = findInsensitive(html, rangeEnd, ">", i + 1);
      if (tagEnd == std::string::npos) break;
      char tagName[24] = {};
      bool closing = false;
      bool selfClosing = false;
      const size_t tagLength = parseTagName(html, i, tagEnd, tagName, sizeof(tagName), closing, selfClosing);
      if (tagLength == 0) {
        i = tagEnd + 1;
        continue;
      }

      if (skipDepth > 0) {
        if (std::strcmp(tagName, skippedTag) == 0) {
          if (closing) {
            --skipDepth;
          } else if (!selfClosing) {
            ++skipDepth;
          }
        }
        i = tagEnd + 1;
        continue;
      }

      if (!closing && isNoiseContainer(tagName, html, i, tagEnd)) {
        if (!selfClosing) {
          std::snprintf(skippedTag, sizeof(skippedTag), "%s", tagName);
          skipDepth = 1;
        }
        i = tagEnd + 1;
        continue;
      }

      if (tagEquals(tagName, "br")) {
        appendLineBreak(text, textLength);
      } else if (tagEquals(tagName, "li")) {
        if (closing) {
          appendLineBreak(text, textLength);
        } else {
          appendLineBreak(text, textLength);
          appendChar(text, textLength, '-');
          appendChar(text, textLength, ' ');
        }
      } else if (tagEquals(tagName, "tr") || tagEquals(tagName, "dt") || tagEquals(tagName, "dd")) {
        appendLineBreak(text, textLength);
      } else if (tagEquals(tagName, "td") || tagEquals(tagName, "th")) {
        appendSpace(text, textLength);
      } else if (isParagraphTag(tagName)) {
        appendParagraphBreak(text, textLength);
      }
      i = tagEnd + 1;
      continue;
    }
    if (skipDepth > 0) {
      ++i;
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

bool normalizedLineEquals(const char* left, const size_t leftLength, const char* right) {
  if (!left || !right) return false;
  size_t li = 0;
  size_t ri = 0;
  while (li < leftLength || right[ri]) {
    while (li < leftLength && std::isspace(static_cast<unsigned char>(left[li]))) ++li;
    while (right[ri] && std::isspace(static_cast<unsigned char>(right[ri]))) ++ri;
    if (li >= leftLength || !right[ri]) return li >= leftLength && !right[ri];
    const unsigned char lc = static_cast<unsigned char>(left[li]);
    const unsigned char rc = static_cast<unsigned char>(right[ri]);
    if (std::tolower(lc) != std::tolower(rc)) return false;
    ++li;
    ++ri;
  }
  return true;
}

uint64_t normalizedLineHash(const char* line, const size_t length) {
  uint64_t hash = 14695981039346656037ULL;
  bool pendingSpace = false;
  for (size_t i = 0; i < length; ++i) {
    const unsigned char c = static_cast<unsigned char>(line[i]);
    if (std::isspace(c)) {
      pendingSpace = true;
      continue;
    }
    if (pendingSpace) {
      hash ^= static_cast<uint8_t>(' ');
      hash *= 1099511628211ULL;
      pendingSpace = false;
    }
    hash ^= static_cast<uint8_t>(std::tolower(c));
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle) {
  if (!line || length == 0) return true;
  if (articleTitle && articleTitle[0] && normalizedLineEquals(line, length, articleTitle)) return true;

  if (rangeContainsInsensitive(line, 0, length, "http://") || rangeContainsInsensitive(line, 0, length, "https://") ||
      rangeContainsInsensitive(line, 0, length, "www.")) {
    size_t spaces = 0;
    for (size_t i = 0; i < length; ++i) spaces += std::isspace(static_cast<unsigned char>(line[i])) ? 1U : 0U;
    if (spaces <= 2 || length < 140) return true;
  }

  size_t pipes = 0;
  size_t arrows = 0;
  for (size_t i = 0; i < length; ++i) {
    pipes += line[i] == '|' ? 1U : 0U;
    arrows += line[i] == '>' ? 1U : 0U;
  }
  if (length < 180 && (pipes >= 2 || arrows >= 2)) return true;

  if (length <= 220) {
    static constexpr const char* NOISE_LINES[] = {
        "publicité",             "advertisement",        "contenu sponsorisé",    "contenu sponsorise",
        "sponsorisé",            "sponsorise",           "lire aussi",             "à lire aussi",
        "a lire aussi",          "voir aussi",           "sur le même sujet",      "sur le meme sujet",
        "vous aimerez",          "articles similaires",  "contenus recommandés",  "contenus recommandes",
        "recommandé",            "recommande",           "pour aller plus loin",   "en savoir plus",
        "newsletter",            "abonnez-vous",         "abonnez vous",           "s'abonner",
        "se connecter",          "connexion",            "partager",               "partagez",
        "suivez-nous",           "suivez nous",          "téléchargez notre application", "telechargez notre application",
        "cookies",               "politique de confidentialité", "politique de confidentialite", "mentions légales",
        "mentions legales",      "tous droits réservés", "tous droits reserves",   "facebook",
        "twitter",               "instagram",            "linkedin",               "whatsapp",
        "telegram",              "pinterest",            "accueil >",              "accueil |",
    };
    for (const char* marker : NOISE_LINES) {
      if (rangeContainsInsensitive(line, 0, length, marker)) return true;
    }
  }
  return false;
}

size_t cleanExtractedText(char* text, const size_t length, const char* articleTitle) {
  if (!text || length == 0) return 0;
  constexpr size_t HASH_SLOTS = 128;
  uint64_t recentHashes[HASH_SLOTS] = {};
  size_t hashCount = 0;
  size_t hashCursor = 0;
  size_t read = 0;
  size_t write = 0;
  bool pendingBlank = false;

  while (read < length) {
    size_t end = read;
    while (end < length && text[end] != '\n') ++end;
    size_t start = read;
    while (start < end && std::isspace(static_cast<unsigned char>(text[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    const size_t lineLength = end - start;

    if (lineLength == 0) {
      if (write > 0) pendingBlank = true;
    } else if (!looksLikeNoiseLine(text + start, lineLength, articleTitle)) {
      const uint64_t hash = normalizedLineHash(text + start, lineLength);
      bool duplicate = false;
      if (lineLength >= 12) {
        for (size_t h = 0; h < hashCount; ++h) {
          if (recentHashes[h] == hash) {
            duplicate = true;
            break;
          }
        }
      }
      if (!duplicate) {
        if (write > 0) {
          text[write++] = '\n';
          if (pendingBlank) text[write++] = '\n';
        }
        if (write != start) std::memmove(text + write, text + start, lineLength);
        write += lineLength;
        pendingBlank = false;
        if (lineLength >= 12) {
          if (hashCount < HASH_SLOTS) {
            recentHashes[hashCount++] = hash;
          } else {
            recentHashes[hashCursor] = hash;
            hashCursor = (hashCursor + 1) % HASH_SLOTS;
          }
        }
      }
    }
    read = end < length ? end + 1 : length;
  }

  while (write > 0 && (text[write - 1] == ' ' || text[write - 1] == '\n')) --write;
  text[write] = '\0';
  return write;
}

bool bodyCacheIsCurrent(const std::string& path) {
  if (!Storage.exists(path.c_str())) return false;
  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return false;
  char marker[BODY_MAGIC_BYTES] = {};
  const bool valid = file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES) &&
                     std::memcmp(marker, BODY_MAGIC, BODY_MAGIC_BYTES) == 0;
  file.close();
  return valid;
}

'''
cache_cpp = replace_section(
    cache_cpp,
    "void appendSpace(char* out, size_t& outLength) {\n",
    "bool writeTextFile(const std::string& path, const char* text, const size_t length) {\n",
    cleaner_helpers,
    "RSS readable HTML extraction and cleanup helpers",
)

cache_cpp = replace_section(
    cache_cpp,
    "bool writeTextFile(const std::string& path, const char* text, const size_t length) {\n",
    "bool persistFallback(const RssItem& item) {\n",
    r'''bool writeTextFile(const std::string& path, const char* text, const size_t length) {
  if (!text || length == 0) return false;
  Storage.ensureDirectoryExists("/.crosspoint");
  Storage.ensureDirectoryExists(CACHE_DIR);
  const std::string tempPath = path + ".tmp";
  Storage.remove(tempPath.c_str());

  FsFile file;
  if (!Storage.openFileForWrite("RSS", tempPath, file)) return false;
  const size_t markerWritten = file.write(reinterpret_cast<const uint8_t*>(BODY_MAGIC), BODY_MAGIC_BYTES);
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

''',
    "RSS versioned article body writer",
)

cache_cpp = replace_once(
    cache_cpp,
    '''std::string bodyPath(const RssItem& item) {
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
''',
    '''std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  char name[64];
  std::snprintf(name, sizeof(name), "%s/%016llx.txt", CACHE_DIR, static_cast<unsigned long long>(hash));
  return name;
}

bool remove(const RssItem& item) {
  const std::string path = bodyPath(item);
  if (!Storage.exists(path.c_str())) return true;
  Storage.remove(path.c_str());
  return !Storage.exists(path.c_str());
}

CacheResult ensureCached(const RssItem& item, const CancelCallback& shouldCancel) {
  const std::string path = bodyPath(item);
  if (bodyCacheIsCurrent(path)) return CacheResult::READY;
  // Old extractor versions were plain text without BODY_MAGIC. Remove them so
  // one refresh upgrades formatting instead of serving stale noisy text.
  if (Storage.exists(path.c_str())) Storage.remove(path.c_str());
''',
    "RSS stale article body invalidation and remove API",
)

cache_cpp = replace_once(
    cache_cpp,
    '''  size_t textLength = 0;
  if (!extractReadableText(html, htmlLength, text, textLength)) {
    LOG_ERR("RSS", "Article extraction failed: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  if (htmlTruncated) LOG_DBG("RSS", "HTML truncated safely for %s", item.link);
''',
    '''  size_t textLength = 0;
  if (!extractReadableText(html, htmlLength, text, textLength)) {
    LOG_ERR("RSS", "Article extraction failed: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  textLength = cleanExtractedText(text, textLength, item.title);
  if (textLength < MIN_EXTRACTED_TEXT) {
    LOG_ERR("RSS", "Article cleaner removed too much text: %s", item.link);
    return persistFallback(item) ? CacheResult::FALLBACK_READY : CacheResult::FAILED;
  }
  if (htmlTruncated) LOG_DBG("RSS", "HTML truncated safely for %s", item.link);
''',
    "RSS extracted article post-cleaning",
)

cache_cpp = replace_once(
    cache_cpp,
    '''bool load(const RssItem& item, std::string& outText) {
  outText.clear();
  const std::string path = bodyPath(item);
  if (!Storage.exists(path.c_str())) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return false;
  char buffer[768];
''',
    '''bool load(const RssItem& item, std::string& outText) {
  outText.clear();
  const std::string path = bodyPath(item);
  if (!Storage.exists(path.c_str())) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return false;
  char marker[BODY_MAGIC_BYTES] = {};
  if (file.read(marker, BODY_MAGIC_BYTES) != static_cast<int>(BODY_MAGIC_BYTES) ||
      std::memcmp(marker, BODY_MAGIC, BODY_MAGIC_BYTES) != 0) {
    file.close();
    // Stale pre-cleaner body: discard it and fall back to the feed summary
    // until the next refresh downloads the improved extraction.
    Storage.remove(path.c_str());
    return false;
  }
  char buffer[768];
''',
    "RSS article body reader version check",
)

cache_cpp_path.write_text(cache_cpp)


# ---------------------------------------------------------------------------
# News history lifecycle: when a source exceeds its 100 retained entries,
# remove the dropped body file unless another source still references it. Also
# clean unmerged bodies if a refresh is cancelled and invalidate bodies tied to
# an obsolete feeds.txt configuration.
# ---------------------------------------------------------------------------
news_cpp_path = Path("src/activities/home/RssNewsActivity.cpp")
news_cpp = news_cpp_path.read_text()

load_cache = r'''bool RssNewsActivity::loadCache() {
  articleCount = 0;
  if (!articles || !Storage.exists(CACHE_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", CACHE_PATH, file)) return false;

  CacheHeader header{};
  const bool headerOk = file.read(&header, sizeof(header)) == static_cast<int>(sizeof(header));
  const bool layoutOk = headerOk && header.magic == CACHE_MAGIC && header.version == CACHE_VERSION &&
                        header.count <= MAX_ARTICLES;
  if (!layoutOk) {
    LOG_ERR("RSS", "Ignoring incompatible RSS cache; refresh will rebuild it");
    file.close();
    return false;
  }

  if (header.sourceHash != sourceConfigHash()) {
    // The source indexes in this cache belong to the previous feeds.txt. Purge
    // their dedicated bodies before discarding metadata so removed/reordered
    // sources cannot leave permanent SD orphans.
    for (uint16_t i = 0; i < header.count; ++i) {
      CachedArticle stale{};
      if (file.read(&stale, sizeof(stale)) != static_cast<int>(sizeof(stale))) break;
      RssArticleCache::remove(stale.item);
    }
    file.close();
    Storage.remove(CACHE_PATH);
    LOG_DBG("RSS", "Purged article bodies for obsolete feed configuration");
    return false;
  }

  for (uint16_t i = 0; i < header.count; ++i) {
    CachedArticle article{};
    if (file.read(&article, sizeof(article)) != static_cast<int>(sizeof(article)) || article.sourceIndex >= sourceCount) {
      LOG_ERR("RSS", "RSS cache truncated or invalid at record %u", static_cast<unsigned>(i));
      articleCount = 0;
      file.close();
      return false;
    }
    articles[articleCount++] = article;
  }
  file.close();
  LOG_DBG("RSS", "Loaded %zu cached articles", articleCount);
  return true;
}

'''
news_cpp = replace_section(
    news_cpp,
    "bool RssNewsActivity::loadCache() {\n",
    "bool RssNewsActivity::saveCache() const {\n",
    load_cache,
    "RSS cache/config body cleanup",
)

merge_source = r'''void RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {
  if (!articles || !items || sourceIndex >= sourceCount) return;

  size_t mergedCount = 0;
  const size_t incomingCount = std::min(count, ITEMS_PER_SOURCE);
  for (size_t i = 0; i < incomingCount; ++i) {
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (sameRssItem(items[i], items[j])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) {
      if (mergedCount != i) items[mergedCount] = items[i];
      ++mergedCount;
    }
  }

  for (size_t i = 0; i < articleCount && mergedCount < ITEMS_PER_SOURCE; ++i) {
    if (articles[i].sourceIndex != sourceIndex) continue;
    bool duplicate = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (sameRssItem(articles[i].item, items[j])) {
        duplicate = true;
        break;
      }
    }
    if (!duplicate) items[mergedCount++] = articles[i].item;
  }

  // Delete full-text bodies that just fell out of this source's 100-entry
  // history. A shared URL is kept when another configured source still points
  // to the same article.
  for (size_t i = 0; i < articleCount; ++i) {
    if (articles[i].sourceIndex != sourceIndex) continue;
    bool retained = false;
    for (size_t j = 0; j < mergedCount; ++j) {
      if (sameRssItem(articles[i].item, items[j])) {
        retained = true;
        break;
      }
    }
    if (retained) continue;

    bool referencedElsewhere = false;
    for (size_t j = 0; j < articleCount; ++j) {
      if (j == i || articles[j].sourceIndex == sourceIndex) continue;
      if (sameRssItem(articles[i].item, articles[j].item)) {
        referencedElsewhere = true;
        break;
      }
    }
    if (!referencedElsewhere) RssArticleCache::remove(articles[i].item);
  }

  size_t writeIndex = 0;
  for (size_t readIndex = 0; readIndex < articleCount; ++readIndex) {
    if (articles[readIndex].sourceIndex == sourceIndex) continue;
    if (writeIndex != readIndex) articles[writeIndex] = articles[readIndex];
    ++writeIndex;
  }
  articleCount = writeIndex;

  const size_t addCount = std::min(mergedCount, MAX_ARTICLES - articleCount);
  for (size_t i = 0; i < addCount; ++i) {
    CachedArticle& article = articles[articleCount++];
    article = CachedArticle{};
    article.sourceIndex = sourceIndex;
    article.item = items[i];
  }
}

'''
news_cpp = replace_section(
    news_cpp,
    "void RssNewsActivity::mergeSourceArticles(const uint8_t sourceIndex, RssItem* items, const size_t count) {\n",
    "void RssNewsActivity::rebuildDisplayOrder() {\n",
    merge_source,
    "RSS dropped-history body pruning",
)

refresh_feeds = r'''void RssNewsActivity::refreshFeeds() {
  if (sourceCount == 0) {
    refreshHadError = true;
    state = State::LIST;
    statusMessage = "Aucun flux RSS";
    requestUpdate();
    return;
  }
  usedNetwork = true;
  refreshHadError = false;
  goHomeAfterRefreshCancel = false;
  state = State::REFRESHING;
  statusMessage = sources[0].name.c_str();
  if (requestUpdateAndWait() != RequestUpdateResult::Rendered) requestUpdate(true);

  size_t successfulSources = 0;
  bool cancelled = false;
  for (uint8_t sourceIndex = 0; sourceIndex < sourceCount; ++sourceIndex) {
    statusMessage = sources[sourceIndex].name.c_str();
    requestUpdate(true);

    size_t fetchedCount = 0;
    if (fetchSource(sourceIndex, fetchedCount, cancelled)) {
      size_t processedBodies = 0;
      for (size_t itemIndex = 0; itemIndex < fetchedCount; ++itemIndex) {
        statusMessage = sources[sourceIndex].name + " " + std::to_string(itemIndex + 1) + "/" +
                        std::to_string(fetchedCount);
        requestUpdate(true);
        const auto cacheResult = RssArticleCache::ensureCached(feedItems[itemIndex], [this, &cancelled]() {
          mappedInput.update();
          if (mappedInput.wasHomeGesture()) {
            goHomeAfterRefreshCancel = true;
            cancelled = true;
          }
          if (mappedInput.isPressed(MappedInputManager::Button::Back) ||
              mappedInput.wasPressed(MappedInputManager::Button::Back) ||
              mappedInput.wasReleased(MappedInputManager::Button::Back)) {
            cancelled = true;
          }
          return cancelled;
        });
        processedBodies = itemIndex + 1;
        if (cacheResult == RssArticleCache::CacheResult::CANCELLED) {
          cancelled = true;
          break;
        }
        if (cacheResult == RssArticleCache::CacheResult::FAILED) refreshHadError = true;
      }
      if (!cancelled) {
        mergeSourceArticles(sourceIndex, feedItems, fetchedCount);
        ++successfulSources;
      } else {
        // This source was not merged into metadata. Remove any newly-created
        // body that is not already referenced by the current history.
        for (size_t i = 0; i < processedBodies; ++i) {
          bool referenced = false;
          for (size_t j = 0; j < articleCount; ++j) {
            if (sameRssItem(feedItems[i], articles[j].item)) {
              referenced = true;
              break;
            }
          }
          if (!referenced) RssArticleCache::remove(feedItems[i]);
        }
      }
    } else if (!cancelled) {
      refreshHadError = true;
    }
    if (cancelled) break;
  }

  if (cancelled) {
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
  if (successfulSources > 0 && !saveCache()) {
    LOG_ERR("RSS", "Could not persist refreshed cache");
    refreshHadError = true;
  }
  selectorIndex = 0;
  topIndex = 0;
  state = State::LIST;
  requestUpdate();
}

'''
news_cpp = replace_section(
    news_cpp,
    "void RssNewsActivity::refreshFeeds() {\n",
    "void RssNewsActivity::seedSimulatorArticles() {\n",
    refresh_feeds,
    "RSS cancelled-refresh body cleanup",
)

news_cpp_path.write_text(news_cpp)


# Defensive checks: these catch accidental Python escape interpretation and
# future source drift before PlatformIO gets involved.
for path in (cache_cpp_path, news_cpp_path):
    text = path.read_text()
    if "\x00" in text:
        raise RuntimeError(f"{path}: generated C++ contains an embedded NUL")

if 'constexpr char BODY_MAGIC[] = "XRSS2\\n";' not in cache_cpp:
    raise RuntimeError("RSS body cache version marker missing")
if "appendParagraphBreak" not in cache_cpp or "cleanExtractedText" not in cache_cpp:
    raise RuntimeError("RSS article readability cleaner missing")
if 'tagEquals(name, "nav")' not in cache_cpp or '"publicit"' not in cache_cpp:
    raise RuntimeError("RSS web-chrome/ad filtering missing")
if "RssArticleCache::remove(articles[i].item);" not in news_cpp:
    raise RuntimeError("RSS dropped-history body pruning missing")
if "Purged article bodies for obsolete feed configuration" not in news_cpp:
    raise RuntimeError("RSS feed-config body cleanup missing")
if "processedBodies" not in news_cpp:
    raise RuntimeError("RSS cancelled-refresh body cleanup missing")

print("Applied RSS article paragraph cleanup, web-noise filtering, cache versioning, and SD body pruning.")
