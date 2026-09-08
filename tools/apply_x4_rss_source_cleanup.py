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


# Source-aware cleanup runs after the generic article cleaner. It deliberately
# keeps all rules local/readable and identifies publishers from the article URL
# rather than the editable feed display name. The display name is passed only
# to recognize generic "follow <source>" calls to action.
header_path = Path("src/activities/home/RssArticleCache.h")
header = header_path.read_text()
header = replace_once(
    header,
    '''CacheResult ensureCached(const RssItem& item, const CancelCallback& shouldCancel);
''',
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const CancelCallback& shouldCancel);
''',
    "RSS source-aware cache API",
)
header_path.write_text(header)


cache_path = Path("src/activities/home/RssArticleCache.cpp")
cpp = cache_path.read_text()

cpp = replace_once(
    cpp,
    '''constexpr char BODY_MAGIC[] = "XRSS2\\n";
''',
    '''constexpr char BODY_MAGIC[] = "XRSS3\\n";
''',
    "RSS source cleaner cache version",
)

source_cleaner = r'''bool normalizedLineEquals(const char* left, const size_t leftLength, const char* right) {
  if (!left || !right) return false;
  size_t li = 0;
  size_t ri = 0;
  while (li < leftLength || right[ri]) {
    while (li < leftLength && std::isspace(static_cast<unsigned char>(left[li]))) ++li;
    while (right[ri] && std::isspace(static_cast<unsigned char>(right[ri]))) ++ri;
    if (li >= leftLength || !right[ri]) return li >= leftLength && !right[ri];
    const unsigned char lc = static_cast<unsigned char>(left[li]);
    const unsigned char rc = static_cast<unsigned char>(right[ri]);
    if (lc < 0x80 && rc < 0x80) {
      if (std::tolower(lc) != std::tolower(rc)) return false;
    } else if (lc != rc) {
      return false;
    }
    ++li;
    ++ri;
  }
  return true;
}

size_t normalizeComparable(const char* data, const size_t length, char* out, const size_t capacity) {
  if (!data || !out || capacity == 0) return 0;
  size_t written = 0;
  for (size_t i = 0; i < length && data[i] && written + 1 < capacity; ++i) {
    const unsigned char c = static_cast<unsigned char>(data[i]);
    if (c < 0x80) {
      if (!std::isalnum(c)) continue;
      out[written++] = static_cast<char>(std::tolower(c));
    } else {
      // Preserve UTF-8 bytes verbatim. Duplicate/title text from the same page
      // therefore compares reliably without needing a Unicode allocation.
      out[written++] = static_cast<char>(c);
    }
  }
  out[written] = '\0';
  return written;
}

bool normalizedContains(const char* haystack, const size_t haystackLength, const char* needle, const size_t needleLength) {
  if (!haystack || !needle || needleLength == 0 || haystackLength < needleLength) return false;
  for (size_t i = 0; i + needleLength <= haystackLength; ++i) {
    if (std::memcmp(haystack + i, needle, needleLength) == 0) return true;
  }
  return false;
}

bool looselyMatchesTitle(const char* line, const size_t lineLength, const char* title) {
  if (!line || !title || !title[0]) return false;
  if (normalizedLineEquals(line, lineLength, title)) return true;

  char lineNormalized[384] = {};
  char titleNormalized[384] = {};
  const size_t lineSize = normalizeComparable(line, lineLength, lineNormalized, sizeof(lineNormalized));
  const size_t titleSize = normalizeComparable(title, std::strlen(title), titleNormalized, sizeof(titleNormalized));
  if (lineSize == 0 || titleSize == 0) return false;
  if (lineSize == titleSize && std::memcmp(lineNormalized, titleNormalized, lineSize) == 0) return true;

  const size_t shorter = std::min(lineSize, titleSize);
  const size_t longer = std::max(lineSize, titleSize);
  if (shorter < 24) return false;
  const size_t toleratedExtra = std::max<size_t>(14, shorter / 3);
  if (longer > shorter + toleratedExtra) return false;
  return lineSize >= titleSize
             ? normalizedContains(lineNormalized, lineSize, titleNormalized, titleSize)
             : normalizedContains(titleNormalized, titleSize, lineNormalized, lineSize);
}

bool lineRepeatedBySummary(const char* line, const size_t lineLength, const char* summary) {
  if (!line || !summary || !summary[0]) return false;
  char lineNormalized[384] = {};
  char summaryNormalized[768] = {};
  const size_t lineSize = normalizeComparable(line, lineLength, lineNormalized, sizeof(lineNormalized));
  const size_t summarySize = normalizeComparable(summary, std::strlen(summary), summaryNormalized, sizeof(summaryNormalized));
  // Require a real sentence: very short phrases can legitimately recur in the
  // article body and should not be discarded just because the feed excerpt
  // happens to contain them.
  if (lineSize < 40 || summarySize < lineSize) return false;
  return normalizedContains(summaryNormalized, summarySize, lineNormalized, lineSize);
}

bool lineStartsWithInsensitive(const char* line, const size_t length, const char* prefix) {
  if (!line || !prefix) return false;
  size_t start = 0;
  while (start < length && std::isspace(static_cast<unsigned char>(line[start]))) ++start;
  while (start < length && (line[start] == '-' || line[start] == '*' || line[start] == ':' || line[start] == '>')) {
    ++start;
    while (start < length && std::isspace(static_cast<unsigned char>(line[start]))) ++start;
  }
  const size_t prefixLength = std::strlen(prefix);
  if (length - start < prefixLength) return false;
  for (size_t i = 0; i < prefixLength; ++i) {
    if (!asciiEqual(line[start + i], prefix[i])) return false;
  }
  return true;
}

bool containsSourceName(const char* line, const size_t length, const char* sourceName) {
  if (!sourceName || !sourceName[0]) return false;
  return rangeContainsInsensitive(line, 0, length, sourceName);
}

enum class SourceCleanupProfile : uint8_t {
  GENERIC,
  FRANDROID,
  FUTURA,
  IPHONESOFT,
  IGENERATION,
  JEUXVIDEO,
  SCIENCE_ET_VIE,
};

SourceCleanupProfile sourceCleanupProfile(const char* articleUrl) {
  if (!articleUrl || !articleUrl[0]) return SourceCleanupProfile::GENERIC;
  const size_t length = std::strlen(articleUrl);
  if (rangeContainsInsensitive(articleUrl, 0, length, "frandroid.com")) return SourceCleanupProfile::FRANDROID;
  if (rangeContainsInsensitive(articleUrl, 0, length, "futura-sciences.com")) return SourceCleanupProfile::FUTURA;
  if (rangeContainsInsensitive(articleUrl, 0, length, "iphonesoft.fr")) return SourceCleanupProfile::IPHONESOFT;
  if (rangeContainsInsensitive(articleUrl, 0, length, "igen.fr")) return SourceCleanupProfile::IGENERATION;
  if (rangeContainsInsensitive(articleUrl, 0, length, "jeuxvideo.com")) return SourceCleanupProfile::JEUXVIDEO;
  if (rangeContainsInsensitive(articleUrl, 0, length, "science-et-vie.com")) return SourceCleanupProfile::SCIENCE_ET_VIE;
  return SourceCleanupProfile::GENERIC;
}

bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {
  if (!line || length == 0 || length > 240) return false;
  const bool follow = lineStartsWithInsensitive(line, length, "suivre ") ||
                      lineStartsWithInsensitive(line, length, "suivez ") ||
                      lineStartsWithInsensitive(line, length, "suivez-nous") ||
                      lineStartsWithInsensitive(line, length, "suivez nous") ||
                      lineStartsWithInsensitive(line, length, "ajoutez ");
  if (!follow) return false;

  // A tiny standalone "Suivre" link is always navigation. Longer sentences
  // are removed only when they clearly target the publisher/social platforms.
  if (length <= 48 || containsSourceName(line, length, sourceName)) return true;
  static constexpr const char* TARGETS[] = {
      "google actualit", "google news", "discover", "facebook", "instagram", "twitter", "linkedin",
      "youtube", "tiktok", "newsletter", "sources préférées", "sources preferees", "nos réseaux", "nos reseaux",
  };
  for (const char* target : TARGETS) {
    if (rangeContainsInsensitive(line, 0, length, target)) return true;
  }
  return false;
}

bool isSourceSpecificNoise(const SourceCleanupProfile profile, const char* line, const size_t length,
                           const bool nearStart) {
  if (!line || length == 0) return true;
  switch (profile) {
    case SourceCleanupProfile::FRANDROID:
      return rangeContainsInsensitive(line, 0, length, "télécharger frandroid gratuitement") ||
             rangeContainsInsensitive(line, 0, length, "telecharger frandroid gratuitement") ||
             rangeContainsInsensitive(line, 0, length, "voir tous ses articles") ||
             rangeContainsInsensitive(line, 0, length, "frandroid sur google news") ||
             rangeContainsInsensitive(line, 0, length, "signaler une erreur dans le texte");

    case SourceCleanupProfile::FUTURA:
      return rangeContainsInsensitive(line, 0, length, "tags associés") ||
             rangeContainsInsensitive(line, 0, length, "tags associes") ||
             rangeContainsInsensitive(line, 0, length, "voir tous les tags") ||
             rangeContainsInsensitive(line, 0, length, "article rédigé par") ||
             rangeContainsInsensitive(line, 0, length, "article redige par") ||
             rangeContainsInsensitive(line, 0, length, "relu par") ||
             rangeContainsInsensitive(line, 0, length, "ajoutez futura à vos sources") ||
             rangeContainsInsensitive(line, 0, length, "ajoutez futura a vos sources") ||
             rangeContainsInsensitive(line, 0, length, "suivez-nous sur discover") ||
             rangeContainsInsensitive(line, 0, length, "suivez-nous sur google actualités") ||
             rangeContainsInsensitive(line, 0, length, "suivez-nous sur google actualites") ||
             rangeContainsInsensitive(line, 0, length, "cela vous intéressera aussi") ||
             rangeContainsInsensitive(line, 0, length, "cela vous interessera aussi") ||
             rangeContainsInsensitive(line, 0, length, "[en vidéo]") ||
             rangeContainsInsensitive(line, 0, length, "[en video]");

    case SourceCleanupProfile::IPHONESOFT:
      return nearStart &&
             (rangeContainsInsensitive(line, 0, length, "écouter") ||
              rangeContainsInsensitive(line, 0, length, "ecouter") ||
              rangeContainsInsensitive(line, 0, length, "réagir") ||
              rangeContainsInsensitive(line, 0, length, "reagir") ||
              (length < 100 && rangeContainsInsensitive(line, 0, length, " coms")) ||
              (length < 180 && rangeContainsInsensitive(line, 0, length, " > ")));

    case SourceCleanupProfile::IGENERATION:
      // iGeneration places author/date/comment/category metadata immediately
      // below the page title. Keep conservative rules: only discard obvious
      // UI separators/metadata near the beginning, never ordinary prose.
      return nearStart &&
             ((length < 120 && rangeContainsInsensitive(line, 0, length, " • ")) ||
              normalizedLineEquals(line, length, "* * *"));

    case SourceCleanupProfile::JEUXVIDEO:
    case SourceCleanupProfile::SCIENCE_ET_VIE:
    case SourceCleanupProfile::GENERIC:
      return false;
  }
  return false;
}

bool isSourceStopLine(const SourceCleanupProfile profile, const char* line, const size_t length,
                      const size_t keptLines) {
  if (!line || keptLines < 2) return false;
  if (profile == SourceCleanupProfile::FRANDROID) {
    // These appear after the editorial body; stopping here also removes author
    // bios, app-download boxes and social/footer fragments that follow.
    return rangeContainsInsensitive(line, 0, length, "envie de retrouver les meilleurs articles de frandroid") ||
           rangeContainsInsensitive(line, 0, length, "signaler une erreur dans le texte");
  }
  return false;
}

uint64_t normalizedLineHash(const char* line, const size_t length) {
  uint64_t hash = 14695981039346656037ULL;
  bool wrote = false;
  for (size_t i = 0; i < length; ++i) {
    const unsigned char c = static_cast<unsigned char>(line[i]);
    if (c < 0x80) {
      if (!std::isalnum(c)) continue;
      hash ^= static_cast<uint8_t>(std::tolower(c));
    } else {
      hash ^= c;
    }
    hash *= 1099511628211ULL;
    wrote = true;
  }
  return wrote ? hash : 0;
}

bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle, const char* articleSummary,
                        const char* sourceName, const SourceCleanupProfile profile, const bool nearStart) {
  if (!line || length == 0) return true;

  // The app already renders the title separately. Site templates often repeat
  // the same title/breadcrumb immediately inside <article>, sometimes with a
  // publisher/category prefix, so use a cautious fuzzy comparison near start.
  if (articleTitle && articleTitle[0] &&
      (normalizedLineEquals(line, length, articleTitle) || (nearStart && looselyMatchesTitle(line, length, articleTitle)))) {
    return true;
  }

  // Feed excerpts/chapeaux are frequently repeated verbatim as the first body
  // paragraph. Remove that copy only near the beginning and only for a full
  // sentence contained in the RSS summary.
  if (nearStart && lineRepeatedBySummary(line, length, articleSummary)) return true;

  if (length <= 24 && (normalizedLineEquals(line, length, "Suivre") || normalizedLineEquals(line, length, "Suivez"))) {
    return true;
  }
  if (isFollowCallToAction(line, length, sourceName)) return true;

  if (rangeContainsInsensitive(line, 0, length, "http://") || rangeContainsInsensitive(line, 0, length, "https://") ||
      rangeContainsInsensitive(line, 0, length, "www.")) {
    size_t spaces = 0;
    for (size_t i = 0; i < length; ++i) spaces += std::isspace(static_cast<unsigned char>(line[i])) ? 1U : 0U;
    if (spaces <= 2 || length < 140) return true;
  }

  if (normalizedLineEquals(line, length, "Image") || lineStartsWithInsensitive(line, length, "Image:")) return true;
  if (nearStart && length < 140 && lineStartsWithInsensitive(line, length, "Image ")) return true;

  size_t pipes = 0;
  size_t arrows = 0;
  for (size_t i = 0; i < length; ++i) {
    pipes += line[i] == '|' ? 1U : 0U;
    arrows += line[i] == '>' ? 1U : 0U;
  }
  if (length < 180 && (pipes >= 2 || arrows >= 2)) return true;

  if (length <= 240) {
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
        "ajoutez-nous à vos sources", "ajoutez nous a vos sources", "sources préférées", "sources preferees",
        "signaler une erreur",   "voir tous les articles", "tous nos articles",
    };
    for (const char* marker : NOISE_LINES) {
      if (rangeContainsInsensitive(line, 0, length, marker)) return true;
    }
  }

  return isSourceSpecificNoise(profile, line, length, nearStart);
}

size_t cleanExtractedText(char* text, const size_t length, const char* articleTitle, const char* articleSummary,
                          const char* sourceName, const char* articleUrl) {
  if (!text || length == 0) return 0;
  constexpr size_t HASH_SLOTS = 128;
  uint64_t recentHashes[HASH_SLOTS] = {};
  size_t hashCount = 0;
  size_t hashCursor = 0;
  size_t read = 0;
  size_t write = 0;
  size_t keptLines = 0;
  bool pendingBlank = false;
  const SourceCleanupProfile profile = sourceCleanupProfile(articleUrl);

  while (read < length) {
    size_t end = read;
    while (end < length && text[end] != '\n') ++end;
    size_t start = read;
    while (start < end && std::isspace(static_cast<unsigned char>(text[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    const size_t lineLength = end - start;

    if (lineLength == 0) {
      if (write > 0) pendingBlank = true;
    } else {
      const bool nearStart = keptLines < 8;
      if (isSourceStopLine(profile, text + start, lineLength, keptLines)) break;
      if (!looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, profile, nearStart)) {
        const uint64_t hash = normalizedLineHash(text + start, lineLength);
        bool duplicate = false;
        if (lineLength >= 12 && hash != 0) {
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
          ++keptLines;
          pendingBlank = false;
          if (lineLength >= 12 && hash != 0) {
            if (hashCount < HASH_SLOTS) {
              recentHashes[hashCount++] = hash;
            } else {
              recentHashes[hashCursor] = hash;
              hashCursor = (hashCursor + 1) % HASH_SLOTS;
            }
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

'''

cpp = replace_section(
    cpp,
    "bool normalizedLineEquals(const char* left, const size_t leftLength, const char* right) {\n",
    "bool bodyCacheIsCurrent(const std::string& path) {\n",
    source_cleaner,
    "RSS source-aware duplicate/noise cleaner",
)

cpp = replace_once(
    cpp,
    '''CacheResult ensureCached(const RssItem& item, const CancelCallback& shouldCancel) {
''',
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const CancelCallback& shouldCancel) {
''',
    "RSS source-aware ensureCached signature",
)

cpp = replace_once(
    cpp,
    '''  textLength = cleanExtractedText(text, textLength, item.title);
''',
    '''  textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link);
''',
    "RSS source-aware post-cleaning call",
)

cache_path.write_text(cpp)


news_path = Path("src/activities/home/RssNewsActivity.cpp")
news = news_path.read_text()
news = replace_once(
    news,
    '''        const auto cacheResult = RssArticleCache::ensureCached(feedItems[itemIndex], [this, &cancelled]() {
''',
    '''        const auto cacheResult = RssArticleCache::ensureCached(
            feedItems[itemIndex], sources[sourceIndex].name.c_str(), [this, &cancelled]() {
''',
    "RSS pass source name to article cleaner",
)
news_path.write_text(news)


# Fail early if an upstream overlay drifts or any of the new behavior stops
# being wired into the generated firmware sources.
if 'constexpr char BODY_MAGIC[] = "XRSS3\\n";' not in cpp:
    raise RuntimeError("RSS source cleaner cache version missing")
if "lineRepeatedBySummary" not in cpp or "looselyMatchesTitle" not in cpp:
    raise RuntimeError("RSS title/summary redundancy filtering missing")
if "SourceCleanupProfile::FRANDROID" not in cpp or "SourceCleanupProfile::FUTURA" not in cpp:
    raise RuntimeError("RSS per-source cleanup profiles missing")
if "envie de retrouver les meilleurs articles de frandroid" not in cpp:
    raise RuntimeError("RSS Frandroid footer cutoff missing")
if "ajoutez futura à vos sources" not in cpp:
    raise RuntimeError("RSS Futura CTA filtering missing")
if "sources[sourceIndex].name.c_str(), [this, &cancelled]" not in news:
    raise RuntimeError("RSS source name is not passed to article cleaner")

print("Applied source-aware RSS cleanup with fuzzy header/chapeau deduplication and follow-CTA filtering.")
