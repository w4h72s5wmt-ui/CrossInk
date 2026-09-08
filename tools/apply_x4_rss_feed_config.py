from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()

header = replace_once(
    header,
    '''  struct Source {
    const char* name;
    const char* url;
  };

  // X4 Pro only: keep a generous offline archive. The feed parser is bounded
  // to 100 current items/source while the SD cache preserves older unique
  // entries until that source reaches the same 100-item history limit.
  static constexpr size_t SOURCE_COUNT = 8;
  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr size_t MAX_ARTICLES = SOURCE_COUNT * ITEMS_PER_SOURCE;
  static constexpr size_t FEED_ITEM_CAPACITY = ITEMS_PER_SOURCE;
  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2
  // V3 invalidates the V2 binary layout because RssItem now stores a 4 KB body.
  static constexpr uint16_t CACHE_VERSION = 3;
  static constexpr char CACHE_PATH[] = "/.crosspoint/rss_news.bin";
  static constexpr char CACHE_TMP_PATH[] = "/.crosspoint/rss_news.tmp";

  using UiApp = freeink::ui::FreeInkApp<32, 4>;

  static constexpr std::array<Source, SOURCE_COUNT> SOURCES = {{
      {"Le Figaro", "https://rss.lefigaro.fr/lefigaro/laune"},
      {"iGeneration", "https://www.igen.fr/rss"},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft"},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml"},
      {"Numerama", "https://www.numerama.com/feed/"},
      {"Frandroid", "https://www.frandroid.com/feed"},
      {"Science & Vie", "https://www.science-et-vie.com/feed"},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml"},
  }};
''',
    '''  struct Source {
    std::string name;
    std::string url;
  };

  struct DefaultSource {
    const char* name;
    const char* url;
  };

  // Keep the existing eight-feed memory ceiling: each source may preserve up
  // to 100 offline articles and RssItem includes a large cached body. The SD
  // configuration can contain fewer sources without increasing PSRAM usage.
  static constexpr size_t MAX_SOURCES = 8;
  static constexpr size_t DEFAULT_SOURCE_COUNT = 6;
  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr size_t MAX_ARTICLES = MAX_SOURCES * ITEMS_PER_SOURCE;
  static constexpr size_t FEED_ITEM_CAPACITY = ITEMS_PER_SOURCE;
  static constexpr size_t FEED_CONFIG_MAX_BYTES = 4096;
  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2
  // V4 binds the binary article cache to the current feeds.txt content so
  // reordering/replacing sources can never relabel old articles incorrectly.
  static constexpr uint16_t CACHE_VERSION = 4;
  static constexpr char CACHE_PATH[] = "/.crosspoint/rss_news.bin";
  static constexpr char CACHE_TMP_PATH[] = "/.crosspoint/rss_news.tmp";
  static constexpr char FEEDS_DIR[] = "/RSS";
  static constexpr char FEEDS_PATH[] = "/RSS/feeds.txt";

  using UiApp = freeink::ui::FreeInkApp<32, 4>;

  static constexpr std::array<DefaultSource, DEFAULT_SOURCE_COUNT> DEFAULT_SOURCES = {{
      {"iGeneration", "https://www.igen.fr/rss"},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft"},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml"},
      {"Frandroid", "https://www.frandroid.com/feed"},
      {"Science & Vie", "https://www.science-et-vie.com/feed"},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml"},
  }};
''',
    "RSS configurable source definitions",
)

header = replace_once(
    header,
    '''  std::vector<std::string> articleTitleLines;
  std::vector<std::string> articleSummaryLines;

  freeink::ui::GfxRendererTarget uiTarget;
''',
    '''  std::vector<std::string> articleTitleLines;
  std::vector<std::string> articleSummaryLines;
  std::array<Source, MAX_SOURCES> sources{};
  size_t sourceCount = 0;

  freeink::ui::GfxRendererTarget uiTarget;
''',
    "RSS runtime source storage",
)

header = replace_once(
    header,
    '''  bool ensureBuffers();
  bool loadCache();
''',
    '''  bool ensureBuffers();
  void loadSources();
  bool ensureFeedConfigFile();
  uint32_t sourceConfigHash() const;
  bool loadCache();
''',
    "RSS source config methods",
)

header_path.write_text(header)


cpp_path = Path("src/activities/home/RssNewsActivity.cpp")
cpp = cpp_path.read_text()

cpp = replace_once(
    cpp,
    '''struct CacheHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t count;
};
''',
    '''struct CacheHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t count;
  uint32_t sourceHash;
};
''',
    "RSS cache source hash",
)

cpp = replace_once(
    cpp,
    '''Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {
''',
    '''std::string trimFeedField(std::string value) {
  const auto notSpace = [](const unsigned char c) { return !std::isspace(c); };
  const auto first = std::find_if(value.begin(), value.end(), notSpace);
  if (first == value.end()) return {};
  const auto last = std::find_if(value.rbegin(), value.rend(), notSpace).base();
  return std::string(first, last);
}

Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {
''',
    "RSS feed field trimming helper",
)

cpp = replace_once(
    cpp,
    '''  if (!ensureBuffers()) {
    statusMessage = tr(STR_MEMORY_ERROR);
  } else {
''',
    '''  loadSources();
  if (!ensureBuffers()) {
    statusMessage = tr(STR_MEMORY_ERROR);
  } else {
''',
    "RSS load sources on entry",
)

source_methods = '''void RssNewsActivity::loadSources() {
  sourceCount = 0;
  for (const auto& source : DEFAULT_SOURCES) {
    if (sourceCount >= MAX_SOURCES) break;
    sources[sourceCount++] = Source{source.name, source.url};
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
      const size_t separator = line.find('|');
      if (separator != std::string::npos) {
        std::string name = trimFeedField(line.substr(0, separator));
        std::string url = trimFeedField(line.substr(separator + 1));
        const bool supportedUrl = url.rfind("https://", 0) == 0 || url.rfind("http://", 0) == 0;
        if (!name.empty() && supportedUrl) {
          parsed[parsedCount++] = Source{std::move(name), std::move(url)};
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
  content.reserve(768);
  content += "# CrossInk RSS feeds\\n";
  content += "# Format: Name|URL\\n";
  content += "# One feed per line; blank lines and lines beginning with # are ignored.\\n";
  content += "# Maximum: 8 feeds. Changes are loaded next time the RSS app opens.\\n";
  for (const auto& source : DEFAULT_SOURCES) {
    content += source.name;
    content += '|';
    content += source.url;
    content += '\\n';
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

uint32_t RssNewsActivity::sourceConfigHash() const {
  uint32_t hash = UINT32_C(2166136261);
  const auto mix = [&hash](const char c) {
    hash ^= static_cast<uint8_t>(c);
    hash *= UINT32_C(16777619);
  };
  for (size_t i = 0; i < sourceCount; ++i) {
    for (const char c : sources[i].name) mix(c);
    mix('|');
    for (const char c : sources[i].url) mix(c);
    mix('\\n');
  }
  return hash;
}

'''
cpp = replace_once(
    cpp,
    '''bool RssNewsActivity::loadCache() {
''',
    source_methods + '''bool RssNewsActivity::loadCache() {
''',
    "RSS source config implementation",
)

cpp = replace_once(
    cpp,
    '''  if (!headerOk || header.magic != CACHE_MAGIC || header.version != CACHE_VERSION || header.count > MAX_ARTICLES) {
''',
    '''  if (!headerOk || header.magic != CACHE_MAGIC || header.version != CACHE_VERSION || header.count > MAX_ARTICLES ||
      header.sourceHash != sourceConfigHash()) {
''',
    "RSS invalidate cache when feed config changes",
)

cpp = replace_once(
    cpp,
    '''  const CacheHeader header{CACHE_MAGIC, CACHE_VERSION, static_cast<uint16_t>(articleCount)};
''',
    '''  const CacheHeader header{CACHE_MAGIC, CACHE_VERSION, static_cast<uint16_t>(articleCount), sourceConfigHash()};
''',
    "RSS persist feed config hash",
)

# Runtime operations must use the number of feeds actually loaded from the SD
# file rather than the compile-time maximum.
cpp = cpp.replace("SOURCE_COUNT", "sourceCount")
cpp = cpp.replace("SOURCES[article.sourceIndex].name", "sources[article.sourceIndex].name.c_str()")
cpp = cpp.replace("SOURCES[sourceIndex].url", "sources[sourceIndex].url.c_str()")
cpp = cpp.replace("SOURCES[sourceIndex].name", "sources[sourceIndex].name.c_str()")
cpp = cpp.replace("SOURCES[0].name", "sources[0].name.c_str()")

if "SOURCES[" in cpp or "SOURCE_COUNT" in cpp:
    raise RuntimeError("RSS still contains hard-coded runtime source access")
if "sourceCount == 0" not in cpp:
    # Guard refresh even though loadSources always leaves built-ins available.
    cpp = replace_once(
        cpp,
        '''void RssNewsActivity::refreshFeeds() {
  usedNetwork = true;
''',
        '''void RssNewsActivity::refreshFeeds() {
  if (sourceCount == 0) {
    refreshHadError = true;
    state = State::LIST;
    statusMessage = "Aucun flux RSS";
    requestUpdate();
    return;
  }
  usedNetwork = true;
''',
        "RSS empty source guard",
    )

cpp_path.write_text(cpp)

if 'static constexpr char FEEDS_PATH[] = "/RSS/feeds.txt";' not in header:
    raise RuntimeError("RSS feeds.txt path missing")
if "Le Figaro" in header or "Numerama" in header:
    raise RuntimeError("Removed RSS defaults are still present")
if "header.sourceHash != sourceConfigHash()" not in cpp:
    raise RuntimeError("RSS cache is not bound to feed configuration")
if "Loaded %zu feeds from %s" not in cpp:
    raise RuntimeError("RSS SD feed loading implementation missing")

print("Applied editable SD RSS feed configuration with six cleaned defaults and cache invalidation.")
