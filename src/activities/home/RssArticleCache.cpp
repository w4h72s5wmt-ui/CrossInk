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
#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

namespace RssArticleCache {
namespace {
constexpr char CACHE_DIR[] = "/.crosspoint/rss_articles";
// Plain-text cache format marker. Bumping this invalidates old extracted text
// after the cleaner changes, while keeping files human-readable on the SD card.
constexpr char BODY_MAGIC[] = "XRSS11\n";
constexpr char FALLBACK_MAGIC[] = "XRSSF1\n";
constexpr size_t BODY_MAGIC_BYTES = sizeof(BODY_MAGIC) - 1;
static_assert(sizeof(FALLBACK_MAGIC) == sizeof(BODY_MAGIC), "RSS body markers must have equal width");
constexpr size_t MAX_HTML_BYTES = 1536U * 1024U;
constexpr size_t MAX_TEXT_BYTES = 64U * 1024U;
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

#include "RssArticleHtml.inc"

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

bool matchesCleanupRuleList(const char* rules, const char* line, const size_t length) {
  if (!rules || !rules[0] || !line || length == 0) return false;
  const size_t rulesLength = std::strlen(rules);
  size_t start = 0;
  while (start <= rulesLength) {
    size_t end = start;
    while (end < rulesLength && rules[end] != ';') ++end;
    while (start < end && std::isspace(static_cast<unsigned char>(rules[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(rules[end - 1]))) --end;
    if (end > start) {
      const size_t tokenLength = end - start;
      for (size_t i = 0; i + tokenLength <= length; ++i) {
        size_t j = 0;
        while (j < tokenLength && asciiEqual(line[i + j], rules[start + j])) ++j;
        if (j == tokenLength) return true;
      }
    }
    if (end >= rulesLength) break;
    start = end + 1;
  }
  return false;
}

bool isFigaroArticle(const char* articleUrl) {
  if (!articleUrl || !articleUrl[0]) return false;
  return rangeContainsInsensitive(articleUrl, 0, std::strlen(articleUrl), "lefigaro.fr");
}

size_t findCleanupMarker(const char* text, const size_t length, const char* marker, const size_t start = 0) {
  if (!text || !marker || start >= length) return std::string::npos;
  const size_t markerLength = std::strlen(marker);
  if (markerLength == 0 || markerLength > length - start) return std::string::npos;
  for (size_t i = start; i + markerLength <= length; ++i) {
    size_t j = 0;
    while (j < markerLength && asciiEqual(text[i + j], marker[j])) ++j;
    if (j == markerLength) return i;
  }
  return std::string::npos;
}

// Figaro sometimes flattens title/byline/date/social/topics and the first real
// paragraph onto one extracted line. Never drop that whole line: locate the
// seam after the inline "Sujets" list and keep the editorial suffix.
size_t figaroPreamblePrefix(const char* line, const size_t length) {
  if (!line || length < 24) return 0;
  const size_t subjects = findCleanupMarker(line, length, "Sujets");
  if (subjects != std::string::npos && subjects < 1200) {
    const size_t scanStart = subjects + std::strlen("Sujets");
    const size_t scanEnd = std::min(length, subjects + 700);
    size_t separators = 0;
    for (size_t i = scanStart; i < scanEnd; ++i) {
      if (line[i] == '-') ++separators;
      if (i <= scanStart + 6 || separators == 0) continue;
      const unsigned char previous = static_cast<unsigned char>(line[i - 1]);
      const unsigned char current = static_cast<unsigned char>(line[i]);
      const bool previousWord = (previous >= 'a' && previous <= 'z') || previous >= 0x80;
      const bool startsSentence = (current >= 'A' && current <= 'Z') || current == '"' ||
                                  (current == 0xc2 && i + 1 < scanEnd &&
                                   static_cast<unsigned char>(line[i + 1]) == 0xab);
      if (previousWord && startsSentence) return i;
    }
  }

  // Some variants have the social CTA but no topic list. If the browser CTA
  // is immediately followed by prose, remove only through that fixed phrase.
  const char* browserMarker = "nouvel onglet)";
  const size_t browser = findCleanupMarker(line, length, browserMarker);
  if (browser != std::string::npos && browser < 1000) {
    size_t after = browser + std::strlen(browserMarker);
    while (after < length && std::isspace(static_cast<unsigned char>(line[after]))) ++after;
    if (after < length && findCleanupMarker(line, length, "Sujets", after) != after) return after;
  }
  return 0;
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
                        const char* sourceName, const bool nearStart) {
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

  return false;
}

size_t cleanExtractedText(char* text, const size_t length, const char* articleTitle, const char* articleSummary,
                          const char* sourceName, const char* articleUrl, const char* dropRules,
                          const char* dropStartRules, const char* stopRules) {
  if (!text || length == 0) return 0;
  constexpr size_t HASH_SLOTS = 128;
  uint64_t recentHashes[HASH_SLOTS] = {};
  size_t hashCount = 0;
  size_t hashCursor = 0;
  size_t read = 0;
  size_t write = 0;
  size_t keptLines = 0;
  bool pendingBlank = false;
  while (read < length) {
    size_t end = read;
    while (end < length && text[end] != '\n') ++end;
    size_t start = read;
    while (start < end && std::isspace(static_cast<unsigned char>(text[start]))) ++start;
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    size_t lineLength = end - start;

    if (lineLength == 0) {
      if (write > 0) pendingBlank = true;
    } else {
      const bool nearStart = keptLines < 8;
      if (nearStart && isFigaroArticle(articleUrl)) {
        const size_t prefix = figaroPreamblePrefix(text + start, lineLength);
        if (prefix > 0 && prefix < lineLength) {
          start += prefix;
          lineLength -= prefix;
          while (lineLength > 0 && std::isspace(static_cast<unsigned char>(text[start]))) {
            ++start;
            --lineLength;
          }
        }
      }
      if (lineLength > 0 && keptLines >= 2 && matchesCleanupRuleList(stopRules, text + start, lineLength)) break;
      const bool fileDrop = lineLength == 0 || matchesCleanupRuleList(dropRules, text + start, lineLength) ||
                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength));
      if (!fileDrop &&
          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, nearStart)) {
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

enum class BodyCacheKind : uint8_t { NONE, FULL, FALLBACK };

BodyCacheKind bodyCacheKind(const std::string& path) {
  if (!Storage.exists(path.c_str())) return BodyCacheKind::NONE;
  FsFile file;
  if (!Storage.openFileForRead("RSS", path, file)) return BodyCacheKind::NONE;
  char marker[BODY_MAGIC_BYTES] = {};
  const bool sized = file.size() > BODY_MAGIC_BYTES && file.size() <= BODY_MAGIC_BYTES + MAX_TEXT_BYTES;
  const bool readMarker = sized && file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES);
  file.close();
  if (!readMarker) return BodyCacheKind::NONE;
  if (std::memcmp(marker, BODY_MAGIC, BODY_MAGIC_BYTES) == 0) return BodyCacheKind::FULL;
  if (std::memcmp(marker, FALLBACK_MAGIC, BODY_MAGIC_BYTES) == 0) return BodyCacheKind::FALLBACK;
  return BodyCacheKind::NONE;
}

bool bodyCacheIsCurrent(const std::string& path) { return bodyCacheKind(path) == BodyCacheKind::FULL; }

bool bodyCacheIsReadable(const std::string& path) { return bodyCacheKind(path) != BodyCacheKind::NONE; }

bool writeTextFile(const std::string& path, const char* marker, const char* text, const size_t length) {
  if (!marker || std::strlen(marker) != BODY_MAGIC_BYTES || !text || length == 0) return false;
  Storage.ensureDirectoryExists("/.crosspoint");
  Storage.ensureDirectoryExists(CACHE_DIR);
  const std::string tempPath = path + ".tmp";
  Storage.remove(tempPath.c_str());

  FsFile file;
  if (!Storage.openFileForWrite("RSS", tempPath, file)) return false;
  const size_t markerWritten = file.write(reinterpret_cast<const uint8_t*>(marker), BODY_MAGIC_BYTES);
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

size_t sanitizeFallbackMarkup(char* text, const size_t length) {
  if (!text || length == 0) return 0;
  size_t read = 0;
  size_t write = 0;
  while (read < length) {
    if (text[read] == '<') {
      const size_t tagEnd = findInsensitive(text, length, ">", read + 1);
      if (tagEnd == std::string::npos) {
        appendChar(text, write, text[read++]);
        continue;
      }
      char tagName[24] = {};
      bool closing = false;
      bool selfClosing = false;
      const size_t tagLength = parseTagName(text, read, tagEnd, tagName, sizeof(tagName), closing, selfClosing);
      if (tagLength > 0) {
        if (tagEquals(tagName, "br") || tagEquals(tagName, "li") || tagEquals(tagName, "tr") ||
            tagEquals(tagName, "dt") || tagEquals(tagName, "dd")) {
          appendLineBreak(text, write);
        } else if (isParagraphTag(tagName)) {
          appendParagraphBreak(text, write);
        }
      }
      read = tagEnd + 1;
      continue;
    }
    if (text[read] == '&') {
      read = decodeEntity(text, length, read, text, write);
      continue;
    }
    const unsigned char c = static_cast<unsigned char>(text[read]);
    if (c == '\r' || c == '\n' || c == '\t' || c == '\f' || c == ' ') {
      appendSpace(text, write);
      ++read;
      continue;
    }
    if (c < 0x20) {
      ++read;
      continue;
    }
    appendChar(text, write, text[read++]);
  }
  while (write > 0 && (text[write - 1] == ' ' || text[write - 1] == '\n')) --write;
  text[write] = '\0';
  return write;
}

size_t removeFallbackUrls(char* text, const size_t length) {
  if (!text || length == 0) return 0;
  size_t read = 0;
  size_t write = 0;
  while (read < length) {
    const bool url = startsWithInsensitive(text, length, read, "http://") ||
                     startsWithInsensitive(text, length, read, "https://") ||
                     startsWithInsensitive(text, length, read, "www.");
    if (url) {
      while (read < length && !std::isspace(static_cast<unsigned char>(text[read]))) ++read;
      while (write > 0 && text[write - 1] == ' ') --write;
      if (read < length && write > 0) appendSpace(text, write);
      continue;
    }
    text[write++] = text[read++];
  }
  while (write > 0 && std::isspace(static_cast<unsigned char>(text[write - 1]))) --write;
  text[write] = '\0';
  return write;
}

size_t fallbackRuleCutoff(const char* text, const size_t length, const char* stopRules) {
  if (!text || length == 0 || !stopRules || !stopRules[0]) return length;
  const size_t rulesLength = std::strlen(stopRules);
  size_t cutoff = length;
  size_t ruleStart = 0;
  while (ruleStart <= rulesLength) {
    size_t ruleEnd = ruleStart;
    while (ruleEnd < rulesLength && stopRules[ruleEnd] != ';') ++ruleEnd;
    while (ruleStart < ruleEnd && std::isspace(static_cast<unsigned char>(stopRules[ruleStart]))) ++ruleStart;
    while (ruleEnd > ruleStart && std::isspace(static_cast<unsigned char>(stopRules[ruleEnd - 1]))) --ruleEnd;
    const size_t tokenLength = ruleEnd - ruleStart;
    if (tokenLength > 0 && tokenLength <= length) {
      for (size_t i = 0; i + tokenLength <= cutoff; ++i) {
        size_t j = 0;
        while (j < tokenLength && asciiEqual(text[i + j], stopRules[ruleStart + j])) ++j;
        if (j == tokenLength) {
          cutoff = i;
          break;
        }
      }
    }
    if (ruleEnd >= rulesLength) break;
    ruleStart = ruleEnd + 1;
  }
  while (cutoff > 0 && std::isspace(static_cast<unsigned char>(text[cutoff - 1]))) --cutoff;
  return cutoff;
}

}  // namespace

ArticleIdentity identityOf(const RssItem& item) { return ArticleIdentity{item.link, item.title, item.published}; }

std::string bodyPath(const ArticleIdentity& identity) {
  const char* link = identity.link ? identity.link : "";
  const char* title = identity.title ? identity.title : "";
  const char* published = identity.published ? identity.published : "";
  uint64_t hash = fnv1a64(link);
  if (!link[0]) {
    hash = fnv1a64(title, hash);
    hash = fnv1a64(published, hash);
  }
  const uint64_t authKey = RssFigaroAuth::cacheKeyFor(link);
  for (size_t i = 0; authKey != 0 && i < sizeof(authKey); ++i) {
    hash ^= static_cast<uint8_t>(authKey >> (i * 8U));
    hash *= 1099511628211ULL;
  }
  char name[64];
  std::snprintf(name, sizeof(name), "%s/%016llx.txt", CACHE_DIR, static_cast<unsigned long long>(hash));
  return name;
}

std::string bodyPath(const RssItem& item) { return bodyPath(identityOf(item)); }

bool hasCurrentBody(const ArticleIdentity& identity) { return bodyCacheIsCurrent(bodyPath(identity)); }

bool hasCurrentBody(const RssItem& item) { return hasCurrentBody(identityOf(item)); }

bool hasReadableBody(const ArticleIdentity& identity) { return bodyCacheIsReadable(bodyPath(identity)); }

bool hasReadableBody(const RssItem& item) { return hasReadableBody(identityOf(item)); }

bool remove(const ArticleIdentity& identity) {
  const std::string path = bodyPath(identity);
  if (!Storage.exists(path.c_str())) return true;
  Storage.remove(path.c_str());
  return !Storage.exists(path.c_str());
}

bool remove(const RssItem& item) { return remove(identityOf(item)); }

#include "RssArticleCachePolicy.inc"

}  // namespace RssArticleCache
