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


# X4 Pro RSS only. Publisher-specific text rules now live exclusively in
# /RSS/feeds.txt. Firmware keeps the generic cleaner and the Figaro structural
# preamble seam because that operation cannot be represented safely as a
# line-oriented drop/stop rule.

header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()
header = replace_once(
    header,
    "    std::string stopRules;\n    bool builtInProfile = true;\n",
    "    std::string stopRules;\n",
    "remove RSS built-in profile state",
)
header_path.write_text(header)

news_path = Path("src/activities/home/RssNewsActivity.cpp")
news = news_path.read_text()

load_sources = r'''void RssNewsActivity::loadSources() {
  sourceCount = 0;
  for (const auto& source : DEFAULT_SOURCES) {
    if (sourceCount >= MAX_SOURCES) break;
    sources[sourceCount++] = Source{source.name, source.url, source.syncLimit, source.historyLimit, {}, {}, {}};
  }

  if (!ensureFeedConfigFile()) {
    LOG_ERR("RSS", "Could not create/open %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  FsFile file;
  if (!Storage.openFileForRead("RSS", FEEDS_PATH, file)) {
    LOG_ERR("RSS", "Could not read %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  const size_t bytes = std::min(static_cast<size_t>(file.size()), FEED_CONFIG_MAX_BYTES);
  std::array<char, FEED_CONFIG_MAX_BYTES + 1> buffer{};
  const int read = bytes > 0 ? file.read(buffer.data(), bytes) : 0;
  file.close();
  if (read <= 0) {
    LOG_ERR("RSS", "Empty RSS feed configuration; using built-in feeds");
    return;
  }

  const char* const configBegin = buffer.data();
  const char* const configEnd = configBegin + static_cast<size_t>(read);

  const auto trimRange = [](const char*& begin, const char*& end) {
    while (begin < end && std::isspace(static_cast<unsigned char>(*begin))) ++begin;
    while (end > begin && std::isspace(static_cast<unsigned char>(end[-1]))) --end;
  };
  const auto rangeEquals = [](const char* begin, const char* end, const char* literal) {
    const size_t length = static_cast<size_t>(end - begin);
    const size_t literalLength = std::strlen(literal);
    return length == literalLength && std::memcmp(begin, literal, length) == 0;
  };
  const auto rangeStartsWith = [](const char* begin, const char* end, const char* literal) {
    const size_t length = static_cast<size_t>(end - begin);
    const size_t literalLength = std::strlen(literal);
    return length >= literalLength && std::memcmp(begin, literal, literalLength) == 0;
  };
  const auto parseLimit = [](const char* begin, const char* end, const uint16_t fallback,
                             const uint16_t maximum) {
    if (begin >= end) return fallback;
    if (*begin == '+') ++begin;
    if (begin >= end) return fallback;
    unsigned value = 0;
    for (const char* cursor = begin; cursor < end; ++cursor) {
      if (*cursor < '0' || *cursor > '9') return fallback;
      value = value * 10U + static_cast<unsigned>(*cursor - '0');
      if (value > maximum) return fallback;
    }
    return value >= 1U ? static_cast<uint16_t>(value) : fallback;
  };

  size_t parsedCount = 0;
  const char* lineBegin = configBegin;
  while (lineBegin < configEnd && parsedCount < MAX_SOURCES) {
    const char* lineEnd = lineBegin;
    while (lineEnd < configEnd && *lineEnd != '\n') ++lineEnd;

    const char* begin = lineBegin;
    const char* end = lineEnd;
    trimRange(begin, end);
    if (begin < end && *begin != '#') {
      const char* firstSeparator = begin;
      while (firstSeparator < end && *firstSeparator != '|') ++firstSeparator;
      if (firstSeparator < end) {
        const char* secondSeparator = firstSeparator + 1;
        while (secondSeparator < end && *secondSeparator != '|') ++secondSeparator;

        const char* nameBegin = begin;
        const char* nameEnd = firstSeparator;
        const char* urlBegin = firstSeparator + 1;
        const char* urlEnd = secondSeparator;
        trimRange(nameBegin, nameEnd);
        trimRange(urlBegin, urlEnd);

        uint16_t syncLimit = DEFAULT_SYNC_LIMIT;
        uint16_t historyLimit = DEFAULT_HISTORY_LIMIT;
        const char* dropBegin = nullptr;
        const char* dropEnd = nullptr;
        const char* dropStartBegin = nullptr;
        const char* dropStartEnd = nullptr;
        const char* stopBegin = nullptr;
        const char* stopEnd = nullptr;

        const char* parameterBegin = secondSeparator < end ? secondSeparator + 1 : end;
        while (parameterBegin < end) {
          const char* parameterEnd = parameterBegin;
          while (parameterEnd < end && *parameterEnd != '|') ++parameterEnd;
          const char* fieldBegin = parameterBegin;
          const char* fieldEnd = parameterEnd;
          trimRange(fieldBegin, fieldEnd);
          const char* equals = fieldBegin;
          while (equals < fieldEnd && *equals != '=') ++equals;
          if (equals < fieldEnd) {
            const char* keyBegin = fieldBegin;
            const char* keyEnd = equals;
            const char* valueBegin = equals + 1;
            const char* valueEnd = fieldEnd;
            trimRange(keyBegin, keyEnd);
            trimRange(valueBegin, valueEnd);

            if (rangeEquals(keyBegin, keyEnd, "sync")) {
              syncLimit = parseLimit(valueBegin, valueEnd, DEFAULT_SYNC_LIMIT,
                                     static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (rangeEquals(keyBegin, keyEnd, "history")) {
              historyLimit = parseLimit(valueBegin, valueEnd, DEFAULT_HISTORY_LIMIT,
                                        static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (rangeEquals(keyBegin, keyEnd, "drop")) {
              dropBegin = valueBegin;
              dropEnd = valueEnd;
            } else if (rangeEquals(keyBegin, keyEnd, "dropstart")) {
              dropStartBegin = valueBegin;
              dropStartEnd = valueEnd;
            } else if (rangeEquals(keyBegin, keyEnd, "stop")) {
              stopBegin = valueBegin;
              stopEnd = valueEnd;
            }
          }
          parameterBegin = parameterEnd < end ? parameterEnd + 1 : end;
        }

        const bool supportedUrl = rangeStartsWith(urlBegin, urlEnd, "https://") ||
                                  rangeStartsWith(urlBegin, urlEnd, "http://");
        if (nameBegin < nameEnd && supportedUrl) {
          Source& target = sources[parsedCount++];
          target.name.assign(nameBegin, static_cast<size_t>(nameEnd - nameBegin));
          target.url.assign(urlBegin, static_cast<size_t>(urlEnd - urlBegin));
          target.syncLimit = syncLimit;
          target.historyLimit = historyLimit;
          if (dropBegin) target.dropRules.assign(dropBegin, static_cast<size_t>(dropEnd - dropBegin));
          else target.dropRules.clear();
          if (dropStartBegin) target.dropStartRules.assign(dropStartBegin, static_cast<size_t>(dropStartEnd - dropStartBegin));
          else target.dropStartRules.clear();
          if (stopBegin) target.stopRules.assign(stopBegin, static_cast<size_t>(stopEnd - stopBegin));
          else target.stopRules.clear();
        } else {
          LOG_ERR("RSS", "Ignoring invalid feed line");
        }
      } else {
        LOG_ERR("RSS", "Ignoring feed line without '|'");
      }
    }
    lineBegin = lineEnd < configEnd ? lineEnd + 1 : configEnd;
  }

  if (parsedCount == 0) {
    LOG_ERR("RSS", "No valid feeds in %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  for (size_t i = parsedCount; i < MAX_SOURCES; ++i) sources[i] = Source{};
  sourceCount = parsedCount;
  LOG_DBG("RSS", "Loaded %zu feeds from %s", sourceCount, FEEDS_PATH);
}

'''
news = replace_section(
    news,
    "void RssNewsActivity::loadSources() {\n",
    "bool RssNewsActivity::ensureFeedConfigFile() {\n",
    load_sources,
    "RSS SD-only direct parser",
)

# Keep the auto-created file intentionally generic: publisher rule strings must
# not be compiled back into flash. Development builds expect the richer file
# supplied on SD when publisher-specific cleanup is desired.
ensure_config = r'''bool RssNewsActivity::ensureFeedConfigFile() {
  Storage.ensureDirectoryExists(FEEDS_DIR);
  if (Storage.exists(FEEDS_PATH)) return true;

  std::string content;
  content.reserve(768);
  content += "# CrossInk RSS feeds\n";
  content += "# Name|URL|sync=30|history=100|drop=...|dropstart=...|stop=...\n";
  content += "# Rules are optional and separated with ';'. Maximum: 8 feeds.\n";
  for (const auto& source : DEFAULT_SOURCES) {
    content += source.name;
    content += '|';
    content += source.url;
    content += "|sync=";
    content += std::to_string(source.syncLimit);
    content += "|history=";
    content += std::to_string(source.historyLimit);
    content += '\n';
  }

  FsFile file;
  if (!Storage.openFileForWrite("RSS", FEEDS_PATH, file)) return false;
  const size_t written = file.write(reinterpret_cast<const uint8_t*>(content.data()), content.size());
  const bool synced = written == content.size() && file.sync();
  file.close();
  if (!synced) {
    Storage.remove(FEEDS_PATH);
    return false;
  }
  return true;
}

'''
news = replace_section(
    news,
    "bool RssNewsActivity::ensureFeedConfigFile() {\n",
    "uint32_t RssNewsActivity::sourceConfigHash() const {\n",
    ensure_config,
    "RSS generic config creation",
)
news = replace_once(
    news,
    "    mix('|');\n    mix(sources[i].builtInProfile ? 'A' : 'G');\n    mix('\\n');\n",
    "    mix('\\n');\n",
    "remove RSS profile cache hash",
)
news_path.write_text(news)

cache_header_path = Path("src/activities/home/RssArticleCache.h")
cache_header = cache_header_path.read_text()
cache_header = replace_once(
    cache_header,
    "                        const char* dropStartRules, const char* stopRules, bool builtInProfile,\n",
    "                        const char* dropStartRules, const char* stopRules,\n",
    "remove RSS profile cache API",
)
cache_header_path.write_text(cache_header)

cache_path = Path("src/activities/home/RssArticleCache.cpp")
cache = cache_path.read_text()

# Remove the old publisher enum/domain dispatch entirely. Rule matching below
# is shared by extracted bodies and RSS-summary fallbacks.
cache = replace_section(
    cache,
    "enum class SourceCleanupProfile : uint8_t {\n",
    "bool matchesCleanupRuleList(const char* rules, const char* line, const size_t length) {\n",
    "",
    "remove RSS publisher profiles",
)
cache = replace_section(
    cache,
    "bool isSourceSpecificNoise(const SourceCleanupProfile profile, const char* line, const size_t length,\n",
    "uint64_t normalizedLineHash(const char* line, const size_t length) {\n",
    "",
    "remove RSS publisher noise/stop switches",
)
cache = replace_once(
    cache,
    "bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle, const char* articleSummary,\n                        const char* sourceName, const SourceCleanupProfile profile, const bool nearStart) {\n",
    "bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle, const char* articleSummary,\n                        const char* sourceName, const bool nearStart) {\n",
    "simplify RSS generic cleaner signature",
)
cache = replace_once(cache, "  return isSourceSpecificNoise(profile, line, length, nearStart);\n", "  return false;\n",
                     "remove RSS publisher tail dispatch")
cache = replace_once(
    cache,
    "                          const char* dropStartRules, const char* stopRules, const bool builtInProfile) {\n",
    "                          const char* dropStartRules, const char* stopRules) {\n",
    "remove RSS profile cleaner argument",
)
cache = replace_once(cache, "  const SourceCleanupProfile profile = sourceCleanupProfile(articleUrl, builtInProfile);\n\n", "",
                     "remove RSS profile selection")

old_clean = '''      if (lineLength > 0 &&\n          (isSourceStopLine(profile, text + start, lineLength, keptLines) ||\n           (keptLines >= 2 && matchesCleanupRuleList(stopRules, text + start, lineLength)))) {\n        break;\n      }\n      const bool fileDrop = lineLength == 0 || matchesCleanupRuleList(dropRules, text + start, lineLength) ||\n                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength)) ||\n                            (nearStart && isFigaroArticle(articleUrl) &&\n                             isStandaloneFigaroNoise(text + start, lineLength));\n      if (!fileDrop &&\n          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, profile, nearStart)) {\n'''
new_clean = '''      if (lineLength > 0 && keptLines >= 2 && matchesCleanupRuleList(stopRules, text + start, lineLength)) break;\n      const bool fileDrop = lineLength == 0 || matchesCleanupRuleList(dropRules, text + start, lineLength) ||\n                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength));\n      if (!fileDrop &&\n          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, nearStart)) {\n'''
cache = replace_once(cache, old_clean, new_clean, "route extracted body through SD rules only")

# The old fallback cutoff carried Frandroid/Science&Vie/Figaro literals in
# firmware. Find the earliest configured stop token directly in fallback text.
fallback_cutoff = r'''size_t fallbackRuleCutoff(const char* text, const size_t length, const char* stopRules) {
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

'''
cache = replace_section(cache, "size_t fallbackCutoff(const char* text, const size_t length, const char* articleUrl) {\n",
                        "bool persistFallback(const RssItem& item,", fallback_cutoff,
                        "replace RSS publisher fallback cutoffs")
cache = replace_once(
    cache,
    "bool persistFallback(const RssItem& item, const char* sourceName, const char* dropRules,\n                     const char* dropStartRules, const char* stopRules, const bool builtInProfile) {\n",
    "bool persistFallback(const RssItem& item, const char* sourceName, const char* dropRules,\n                     const char* dropStartRules, const char* stopRules) {\n",
    "remove RSS fallback profile argument",
)
cache = replace_once(cache, "  textLength = fallbackCutoff(text, textLength, item.link);\n",
                     "  textLength = fallbackRuleCutoff(text, textLength, stopRules);\n",
                     "use SD stop rules for fallback")
cache = replace_once(
    cache,
    "  textLength = cleanExtractedText(text, textLength, item.title, nullptr, sourceName, item.link,\n                                  dropRules, dropStartRules, stopRules, builtInProfile);\n",
    "  textLength = cleanExtractedText(text, textLength, item.title, nullptr, sourceName, item.link,\n                                  dropRules, dropStartRules, stopRules);\n",
    "clean fallback with SD rules only",
)
cache = replace_once(
    cache,
    "CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,\n                        const char* dropStartRules, const char* stopRules, const bool builtInProfile,\n",
    "CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,\n                        const char* dropStartRules, const char* stopRules,\n",
    "remove RSS ensureCached profile argument",
)
cache = replace_once(
    cache,
    "    return persistFallback(item, sourceName, dropRules, dropStartRules, stopRules, builtInProfile)\n",
    "    return persistFallback(item, sourceName, dropRules, dropStartRules, stopRules)\n",
    "remove RSS fallback profile forwarding",
)
cache = replace_once(
    cache,
    "    textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link,\n                                    dropRules, dropStartRules, stopRules, builtInProfile);\n",
    "    textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link,\n                                    dropRules, dropStartRules, stopRules);\n",
    "remove RSS extracted profile forwarding",
)

# Standalone Figaro text noise is represented by dropstart in feeds.txt now.
cache = replace_section(cache, "bool isStandaloneFigaroNoise(const char* line, const size_t length) {\n",
                        "bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n",
                        "bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n",
                        "remove RSS Figaro text-rule helper")
cache_path.write_text(cache)

news = news_path.read_text()
news = replace_once(
    news,
    "            sources[sourceIndex].dropStartRules.c_str(), sources[sourceIndex].stopRules.c_str(),\n            sources[sourceIndex].builtInProfile, [this, &cancelled]() {\n",
    "            sources[sourceIndex].dropStartRules.c_str(), sources[sourceIndex].stopRules.c_str(),\n            [this, &cancelled]() {\n",
    "remove RSS profile call argument",
)
news_path.write_text(news)

# Final guards: no publisher profile machinery or publisher-specific cleanup
# strings may remain in RssArticleCache.cpp. Generic cleanup and structural
# Figaro preamble handling must remain.
cache = cache_path.read_text()
news = news_path.read_text()
header = header_path.read_text()
for forbidden in (
    "SourceCleanupProfile", "builtInCleanupRules", "builtInNearStartNoise", "isSourceSpecificNoise",
    "isSourceStopLine", "isStandaloneFigaroNoise", "builtInProfile",
    "télécharger frandroid gratuitement", "telecharger frandroid gratuitement",
    "envie de retrouver les meilleurs articles de frandroid", "tags associés", "tags associes",
    "article rédigé par", "article redige par", "écouter", "ecouter", "réagir", "reagir",
    "Pour ne rater aucun bon plan", "WhatsApp Frandroid", "Pour lire la suite",
    "Cet article est réservé à nos abonnés", "Cet article est reserve a nos abonnes",
):
    if forbidden in cache:
        raise RuntimeError(f"RSS publisher rule still compiled in firmware: {forbidden}")
if "profile" in news[news.find("void RssNewsActivity::loadSources() {"):news.find("uint32_t RssNewsActivity::sourceConfigHash() const {")]:
    raise RuntimeError("RSS profile field still parsed")
if "bool builtInProfile" in header or "builtInProfile" in news:
    raise RuntimeError("RSS built-in profile state still present")
if "figaroPreamblePrefix" not in cache or "isFigaroArticle" not in cache:
    raise RuntimeError("RSS Figaro structural preamble cleanup was lost")
if "fallbackRuleCutoff" not in cache or "matchesCleanupRuleList(stopRules" not in cache:
    raise RuntimeError("RSS SD rules are not active for body/fallback cleanup")
if "const std::string config(" in news or ".substr(" in news[news.find("void RssNewsActivity::loadSources() {"):news.find("bool RssNewsActivity::ensureFeedConfigFile() {")]:
    raise RuntimeError("RSS direct parser optimization was lost")

print("Moved RSS publisher text cleanup to /RSS/feeds.txt; kept only generic and Figaro structural firmware cleanup.")
