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


header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()

header = replace_once(
    header,
    '''  struct Source {
    std::string name;
    std::string url;
  };

  struct DefaultSource {
    const char* name;
    const char* url;
  };
''',
    '''  struct Source {
    std::string name;
    std::string url;
    uint16_t syncLimit = 30;
    uint16_t historyLimit = 100;
  };

  struct DefaultSource {
    const char* name;
    const char* url;
    uint16_t syncLimit;
    uint16_t historyLimit;
  };
''',
    "RSS per-feed limit fields",
)

header = replace_once(
    header,
    '''  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr size_t MAX_ARTICLES = MAX_SOURCES * ITEMS_PER_SOURCE;
''',
    '''  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr uint16_t DEFAULT_SYNC_LIMIT = 30;
  static constexpr uint16_t DEFAULT_HISTORY_LIMIT = 100;
  static constexpr size_t MAX_ARTICLES = MAX_SOURCES * ITEMS_PER_SOURCE;
''',
    "RSS per-feed limit defaults",
)

header = replace_once(
    header,
    '''  static constexpr std::array<DefaultSource, DEFAULT_SOURCE_COUNT> DEFAULT_SOURCES = {{
      {"iGeneration", "https://www.igen.fr/rss"},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft"},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml"},
      {"Frandroid", "https://www.frandroid.com/feed"},
      {"Science & Vie", "https://www.science-et-vie.com/feed"},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml"},
  }};
''',
    '''  static constexpr std::array<DefaultSource, DEFAULT_SOURCE_COUNT> DEFAULT_SOURCES = {{
      {"iGeneration", "https://www.igen.fr/rss", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Frandroid", "https://www.frandroid.com/feed", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Science & Vie", "https://www.science-et-vie.com/feed", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
  }};
''',
    "RSS default feed limits",
)

header_path.write_text(header)


cpp_path = Path("src/activities/home/RssNewsActivity.cpp")
cpp = cpp_path.read_text()

cpp = replace_once(
    cpp,
    '''std::string trimFeedField(std::string value) {
  const auto notSpace = [](const unsigned char c) { return !std::isspace(c); };
  const auto first = std::find_if(value.begin(), value.end(), notSpace);
  if (first == value.end()) return {};
  const auto last = std::find_if(value.rbegin(), value.rend(), notSpace).base();
  return std::string(first, last);
}

''',
    r'''std::string trimFeedField(std::string value) {
  const auto notSpace = [](const unsigned char c) { return !std::isspace(c); };
  const auto first = std::find_if(value.begin(), value.end(), notSpace);
  if (first == value.end()) return {};
  const auto last = std::find_if(value.rbegin(), value.rend(), notSpace).base();
  return std::string(first, last);
}

uint16_t parseFeedLimit(const std::string& value, const uint16_t fallback, const uint16_t maximum) {
  unsigned parsed = 0;
  char extra = '\0';
  if (std::sscanf(value.c_str(), "%u%c", &parsed, &extra) != 1 || parsed < 1 || parsed > maximum) return fallback;
  return static_cast<uint16_t>(parsed);
}

''',
    "RSS feed limit parser",
)

source_methods = r'''void RssNewsActivity::loadSources() {
  sourceCount = 0;
  for (const auto& source : DEFAULT_SOURCES) {
    if (sourceCount >= MAX_SOURCES) break;
    sources[sourceCount++] = Source{source.name, source.url, source.syncLimit, source.historyLimit};
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
            }
          }
          if (parameterEnd == std::string::npos) break;
          parameterStart = parameterEnd + 1;
        }

        const bool supportedUrl = url.rfind("https://", 0) == 0 || url.rfind("http://", 0) == 0;
        if (!name.empty() && supportedUrl) {
          parsed[parsedCount++] = Source{std::move(name), std::move(url), syncLimit, historyLimit};
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
  content.reserve(1024);
  content += "# CrossInk RSS feeds\n";
  content += "# Format: Name|URL|sync=30|history=100\n";
  content += "# sync: max articles downloaded per synchronization (1-100).\n";
  content += "# history: max articles kept for this feed on SD (1-100).\n";
  content += "# Missing/invalid parameters use sync=30 and history=100.\n";
  content += "# One feed per line; blank lines and lines beginning with # are ignored.\n";
  content += "# Maximum: 8 feeds. Changes are loaded next time the RSS app opens.\n";
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
  LOG_DBG("RSS", "Created default feed configuration at %s", FEEDS_PATH);
  return true;
}

'''
cpp = replace_section(
    cpp,
    "void RssNewsActivity::loadSources() {\n",
    "uint32_t RssNewsActivity::sourceConfigHash() const {\n",
    source_methods,
    "RSS feed config parameter parsing",
)

cpp = replace_once(
    cpp,
    '''  RssParser parser(feedItems, FEED_ITEM_CAPACITY);
''',
    '''  const size_t syncLimit = std::clamp<size_t>(sources[sourceIndex].syncLimit, 1, FEED_ITEM_CAPACITY);
  RssParser parser(feedItems, syncLimit);
''',
    "RSS per-feed synchronization limit",
)

cpp = replace_once(
    cpp,
    '''  size_t mergedCount = 0;
  const size_t incomingCount = std::min(count, ITEMS_PER_SOURCE);
''',
    '''  const size_t historyLimit = std::clamp<size_t>(sources[sourceIndex].historyLimit, 1, ITEMS_PER_SOURCE);
  size_t mergedCount = 0;
  const size_t incomingCount = std::min(count, historyLimit);
''',
    "RSS per-feed history limit setup",
)

cpp = replace_once(
    cpp,
    '''  for (size_t i = 0; i < articleCount && mergedCount < ITEMS_PER_SOURCE; ++i) {
''',
    '''  for (size_t i = 0; i < articleCount && mergedCount < historyLimit; ++i) {
''',
    "RSS per-feed retained history limit",
)

cpp_path.write_text(cpp)


# Guard the generated C++ so parameter mistakes fail in the patch step rather
# than producing a firmware with silently ignored limits.
if "uint16_t syncLimit = 30;" not in header or "uint16_t historyLimit = 100;" not in header:
    raise RuntimeError("RSS per-feed limit fields missing")
if '"# Format: Name|URL|sync=30|history=100\\n"' not in cpp:
    raise RuntimeError("RSS feeds.txt parameter documentation missing")
if "RssParser parser(feedItems, syncLimit);" not in cpp:
    raise RuntimeError("RSS sync limit is not applied to parser capacity")
if "mergedCount < historyLimit" not in cpp:
    raise RuntimeError("RSS history limit is not applied to retained articles")
if "for (const char c : sources[i].url) mix(c);" not in cpp:
    raise RuntimeError("RSS source identity hash missing")

print("Applied per-feed RSS sync/history limits from feeds.txt.")
