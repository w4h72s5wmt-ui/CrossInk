from pathlib import Path


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_pos] + replacement + text[end_pos:]


rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()

# X4 Pro RSS only: parse feeds.txt directly from the fixed 4 KiB input buffer.
# This preserves the current file syntax and semantics while avoiding the
# temporary config/line/parameter/key/value std::string graph created on every
# RSS entry. The final Source strings remain owned exactly as before.
optimized_load_sources = r'''void RssNewsActivity::loadSources() {
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
        bool builtInProfile = true;

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
            } else if (rangeEquals(keyBegin, keyEnd, "profile")) {
              builtInProfile = !rangeEquals(valueBegin, valueEnd, "generic") &&
                               !rangeEquals(valueBegin, valueEnd, "none") &&
                               !rangeEquals(valueBegin, valueEnd, "file");
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
          if (dropStartBegin) {
            target.dropStartRules.assign(dropStartBegin, static_cast<size_t>(dropStartEnd - dropStartBegin));
          } else {
            target.dropStartRules.clear();
          }
          if (stopBegin) target.stopRules.assign(stopBegin, static_cast<size_t>(stopEnd - stopBegin));
          else target.stopRules.clear();
          target.builtInProfile = builtInProfile;
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

rss = replace_section(
    rss,
    "void RssNewsActivity::loadSources() {\n",
    "bool RssNewsActivity::ensureFeedConfigFile() {\n",
    optimized_load_sources,
    "RSS direct feeds.txt parser",
)

load_start = rss.find("void RssNewsActivity::loadSources() {\n")
load_end = rss.find("bool RssNewsActivity::ensureFeedConfigFile() {\n", load_start)
load_body = rss[load_start:load_end]
if "const std::string config(" in load_body or ".substr(" in load_body:
    raise RuntimeError("RSS direct parser still contains temporary config/substr strings")
for marker in ('rangeEquals(keyBegin, keyEnd, "drop")', 'rangeEquals(keyBegin, keyEnd, "dropstart")',
               'rangeEquals(keyBegin, keyEnd, "stop")', 'rangeEquals(keyBegin, keyEnd, "profile")'):
    if marker not in load_body:
        raise RuntimeError(f"RSS direct parser lost required field: {marker}")
if "target.name.assign(" not in load_body or "target.url.assign(" not in load_body:
    raise RuntimeError("RSS direct parser does not commit parsed source ranges")

rss_path.write_text(rss)
print("Optimized RSS feeds.txt parser to parse directly from the fixed input buffer.")
