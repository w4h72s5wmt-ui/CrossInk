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
# Feed configuration: add editable per-site cleanup rules. The generic cleaner
# remains firmware code, while publisher-specific tuning lives on the SD card.
# ---------------------------------------------------------------------------
header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()
header = replace_once(
    header,
    '''  struct Source {
    std::string name;
    std::string url;
    uint16_t syncLimit = 30;
    uint16_t historyLimit = 100;
  };
''',
    '''  struct Source {
    std::string name;
    std::string url;
    uint16_t syncLimit = 30;
    uint16_t historyLimit = 100;
    std::string dropRules;
    std::string dropStartRules;
    std::string stopRules;
    bool builtInProfile = true;
  };
''',
    "RSS editable cleanup rule fields",
)
header_path.write_text(header)

cpp_path = Path("src/activities/home/RssNewsActivity.cpp")
cpp = cpp_path.read_text()

source_methods = r'''void RssNewsActivity::loadSources() {
  sourceCount = 0;
  for (const auto& source : DEFAULT_SOURCES) {
    if (sourceCount >= MAX_SOURCES) break;
    sources[sourceCount++] =
        Source{source.name, source.url, source.syncLimit, source.historyLimit, {}, {}, {}, true};
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
  buffer[static_cast<size_t>(read)] = '\0';

  std::array<Source, MAX_SOURCES> parsed{};
  size_t parsedCount = 0;
  const std::string config(buffer.data(), static_cast<size_t>(read));
  size_t lineStart = 0;
  while (lineStart <= config.size() && parsedCount < MAX_SOURCES) {
    const size_t lineEnd = config.find('\n', lineStart);
    const size_t end = lineEnd == std::string::npos ? config.size() : lineEnd;
    std::string line = trimFeedField(config.substr(lineStart, end - lineStart));
    if (!line.empty() && line.front() != '#') {
      const size_t firstSeparator = line.find('|');
      if (firstSeparator != std::string::npos) {
        const size_t secondSeparator = line.find('|', firstSeparator + 1);
        std::string name = trimFeedField(line.substr(0, firstSeparator));
        std::string url = trimFeedField(
            line.substr(firstSeparator + 1,
                        secondSeparator == std::string::npos ? std::string::npos : secondSeparator - firstSeparator - 1));
        uint16_t syncLimit = DEFAULT_SYNC_LIMIT;
        uint16_t historyLimit = DEFAULT_HISTORY_LIMIT;
        std::string dropRules;
        std::string dropStartRules;
        std::string stopRules;
        bool builtInProfile = true;

        size_t parameterStart = secondSeparator == std::string::npos ? line.size() : secondSeparator + 1;
        while (parameterStart < line.size()) {
          const size_t parameterEnd = line.find('|', parameterStart);
          const size_t parameterLength =
              parameterEnd == std::string::npos ? std::string::npos : parameterEnd - parameterStart;
          const std::string parameter = trimFeedField(line.substr(parameterStart, parameterLength));
          const size_t equals = parameter.find('=');
          if (equals != std::string::npos) {
            const std::string key = trimFeedField(parameter.substr(0, equals));
            const std::string value = trimFeedField(parameter.substr(equals + 1));
            if (key == "sync") {
              syncLimit = parseFeedLimit(value, DEFAULT_SYNC_LIMIT, static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (key == "history") {
              historyLimit = parseFeedLimit(value, DEFAULT_HISTORY_LIMIT, static_cast<uint16_t>(ITEMS_PER_SOURCE));
            } else if (key == "drop") {
              dropRules = value;
            } else if (key == "dropstart") {
              dropStartRules = value;
            } else if (key == "stop") {
              stopRules = value;
            } else if (key == "profile") {
              builtInProfile = value != "generic" && value != "none" && value != "file";
            }
          }
          if (parameterEnd == std::string::npos) break;
          parameterStart = parameterEnd + 1;
        }

        const bool supportedUrl = url.rfind("https://", 0) == 0 || url.rfind("http://", 0) == 0;
        if (!name.empty() && supportedUrl) {
          parsed[parsedCount++] = Source{std::move(name), std::move(url), syncLimit, historyLimit,
                                         std::move(dropRules), std::move(dropStartRules), std::move(stopRules),
                                         builtInProfile};
        } else {
          LOG_ERR("RSS", "Ignoring invalid feed line: %s", line.c_str());
        }
      } else {
        LOG_ERR("RSS", "Ignoring feed line without '|': %s", line.c_str());
      }
    }
    if (lineEnd == std::string::npos) break;
    lineStart = lineEnd + 1;
  }

  if (parsedCount == 0) {
    LOG_ERR("RSS", "No valid feeds in %s; using built-in feeds", FEEDS_PATH);
    return;
  }

  for (size_t i = 0; i < parsedCount; ++i) sources[i] = std::move(parsed[i]);
  for (size_t i = parsedCount; i < MAX_SOURCES; ++i) sources[i] = Source{};
  sourceCount = parsedCount;
  LOG_DBG("RSS", "Loaded %zu feeds from %s", sourceCount, FEEDS_PATH);
}

bool RssNewsActivity::ensureFeedConfigFile() {
  Storage.ensureDirectoryExists(FEEDS_DIR);
  if (Storage.exists(FEEDS_PATH)) return true;

  std::string content;
  content.reserve(1200);
  content += "# CrossInk RSS feeds\n";
  content += "# Name|URL|sync=30|history=100|profile=auto|drop=...|dropstart=...|stop=...\n";
  content += "# Multiple cleanup phrases use ';'. Matching is case-insensitive.\n";
  content += "# drop: remove matching line anywhere. dropstart: only near article start.\n";
  content += "# stop: discard the matching line and everything after it.\n";
  content += "# profile=generic disables firmware publisher rules so this file has full control.\n";
  content += "# Maximum: 8 feeds. Changes are loaded next time the RSS app opens.\n";
  for (const auto& source : DEFAULT_SOURCES) {
    content += source.name;
    content += '|';
    content += source.url;
    content += "|sync=";
    content += std::to_string(source.syncLimit);
    content += "|history=";
    content += std::to_string(source.historyLimit);
    content += "|profile=auto\n";
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
  LOG_DBG("RSS", "Created default feed configuration at %s", FEEDS_PATH);
  return true;
}

'''
cpp = replace_section(
    cpp,
    "void RssNewsActivity::loadSources() {\n",
    "uint32_t RssNewsActivity::sourceConfigHash() const {\n",
    source_methods,
    "RSS editable cleanup rules parser",
)

cpp = replace_once(
    cpp,
    '''    for (const char c : sources[i].url) mix(c);
    mix('\\n');
''',
    '''    for (const char c : sources[i].url) mix(c);
    mix('|');
    for (const char c : sources[i].dropRules) mix(c);
    mix('|');
    for (const char c : sources[i].dropStartRules) mix(c);
    mix('|');
    for (const char c : sources[i].stopRules) mix(c);
    mix('|');
    mix(sources[i].builtInProfile ? 'A' : 'G');
    mix('\\n');
''',
    "RSS cleanup rules cache identity",
)
cpp_path.write_text(cpp)


# ---------------------------------------------------------------------------
# Article cleaner: apply file rules on top of the generic cleaner. profile=
# generic/file/none disables the old URL-derived site profile, so every source-
# specific behavior can be controlled from feeds.txt without reflashing.
# ---------------------------------------------------------------------------
cache_header_path = Path("src/activities/home/RssArticleCache.h")
cache_header = cache_header_path.read_text()
cache_header = replace_once(
    cache_header,
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const CancelCallback& shouldCancel);
''',
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                        const char* dropStartRules, const char* stopRules, bool builtInProfile,
                        const CancelCallback& shouldCancel);
''',
    "RSS editable cleanup cache API",
)
cache_header_path.write_text(cache_header)

cache_cpp_path = Path("src/activities/home/RssArticleCache.cpp")
cache_cpp = cache_cpp_path.read_text()

cache_cpp = replace_once(
    cache_cpp,
    '''SourceCleanupProfile sourceCleanupProfile(const char* articleUrl) {
  if (!articleUrl || !articleUrl[0]) return SourceCleanupProfile::GENERIC;
''',
    '''SourceCleanupProfile sourceCleanupProfile(const char* articleUrl, const bool builtInProfile) {
  if (!builtInProfile || !articleUrl || !articleUrl[0]) return SourceCleanupProfile::GENERIC;
''',
    "RSS optional built-in source profile",
)

rule_helper = r'''bool matchesCleanupRuleList(const char* rules, const char* line, const size_t length) {
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

'''
cache_cpp = replace_once(
    cache_cpp,
    '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {
''',
    rule_helper + '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {
''',
    "RSS cleanup rule matcher",
)

cache_cpp = replace_once(
    cache_cpp,
    '''size_t cleanExtractedText(char* text, const size_t length, const char* articleTitle, const char* articleSummary,
                          const char* sourceName, const char* articleUrl) {
''',
    '''size_t cleanExtractedText(char* text, const size_t length, const char* articleTitle, const char* articleSummary,
                          const char* sourceName, const char* articleUrl, const char* dropRules,
                          const char* dropStartRules, const char* stopRules, const bool builtInProfile) {
''',
    "RSS cleanup rule arguments",
)
cache_cpp = replace_once(
    cache_cpp,
    '''  const SourceCleanupProfile profile = sourceCleanupProfile(articleUrl);
''',
    '''  const SourceCleanupProfile profile = sourceCleanupProfile(articleUrl, builtInProfile);
''',
    "RSS configurable source profile selection",
)
cache_cpp = replace_once(
    cache_cpp,
    '''      if (isSourceStopLine(profile, text + start, lineLength, keptLines)) break;
      if (!looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, profile, nearStart)) {
''',
    '''      if (isSourceStopLine(profile, text + start, lineLength, keptLines) ||
          (keptLines >= 2 && matchesCleanupRuleList(stopRules, text + start, lineLength))) {
        break;
      }
      const bool fileDrop = matchesCleanupRuleList(dropRules, text + start, lineLength) ||
                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength));
      if (!fileDrop &&
          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, profile, nearStart)) {
''',
    "RSS apply editable cleanup rules",
)

cache_cpp = replace_once(
    cache_cpp,
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const CancelCallback& shouldCancel) {
''',
    '''CacheResult ensureCached(const RssItem& item, const char* sourceName, const char* dropRules,
                        const char* dropStartRules, const char* stopRules, const bool builtInProfile,
                        const CancelCallback& shouldCancel) {
''',
    "RSS editable cleanup ensureCached signature",
)
cache_cpp = replace_once(
    cache_cpp,
    '''  textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link);
''',
    '''  textLength = cleanExtractedText(text, textLength, item.title, item.summary, sourceName, item.link,
                                      dropRules, dropStartRules, stopRules, builtInProfile);
''',
    "RSS editable cleanup post-processing call",
)
cache_cpp_path.write_text(cache_cpp)

news_path = Path("src/activities/home/RssNewsActivity.cpp")
news = news_path.read_text()
news = replace_once(
    news,
    '''        const auto cacheResult = RssArticleCache::ensureCached(
            feedItems[itemIndex], sources[sourceIndex].name.c_str(), [this, &cancelled]() {
''',
    '''        const auto cacheResult = RssArticleCache::ensureCached(
            feedItems[itemIndex], sources[sourceIndex].name.c_str(), sources[sourceIndex].dropRules.c_str(),
            sources[sourceIndex].dropStartRules.c_str(), sources[sourceIndex].stopRules.c_str(),
            sources[sourceIndex].builtInProfile, [this, &cancelled]() {
''',
    "RSS pass editable cleanup rules",
)
news_path.write_text(news)


# Guard against format drift and accidental silent fallback.
if "std::string dropRules;" not in header or "std::string stopRules;" not in header:
    raise RuntimeError("RSS editable cleanup fields missing")
if 'key == "drop"' not in cpp or 'key == "dropstart"' not in cpp or 'key == "stop"' not in cpp:
    raise RuntimeError("RSS editable cleanup parser missing")
if "for (const char c : sources[i].dropRules) mix(c);" not in cpp:
    raise RuntimeError("RSS cleanup rules do not invalidate stale cache")
if "matchesCleanupRuleList" not in cache_cpp:
    raise RuntimeError("RSS cleanup rule matcher missing")
if "sourceCleanupProfile(articleUrl, builtInProfile)" not in cache_cpp:
    raise RuntimeError("RSS built-in profile toggle missing")
if "sources[sourceIndex].dropStartRules.c_str()" not in news:
    raise RuntimeError("RSS cleanup rules are not passed to article cache")

print("Applied editable per-feed RSS cleanup rules from feeds.txt.")
