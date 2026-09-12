from pathlib import Path


def replace_once(path, old, new, label):
    path = Path(path)
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_after(path, marker, old, new, label):
    path = Path(path)
    text = path.read_text()
    pos = text.find(marker)
    if pos < 0:
        raise SystemExit(f"{label}: marker missing")
    before = text[:pos]
    tail = text[pos:]
    count = tail.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match after marker, found {count}")
    path.write_text(before + tail.replace(old, new, 1))


# Cleaner generation bump: existing XRSS11 / XRSSF1 text can contain the
# missing-boundary artifacts this pass fixes, so invalidate it cleanly instead
# of carrying compatibility logic.
replace_once(
    "src/activities/home/RssArticleCache.cpp",
    'constexpr char BODY_MAGIC[] = "XRSS11\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF1\\n";',
    'constexpr char BODY_MAGIC[] = "XRSS12\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF2\\n";',
    "RSS body generation markers",
)

html = "src/activities/home/RssArticleHtml.inc"
replace_once(
    html,
    'constexpr size_t RSS_LINK_MARKER_BYTES = 3;\n',
    'constexpr size_t RSS_LINK_MARKER_BYTES = 3;\n'
    '// Internal one-byte marker used only while extracting. Whenever a block of\n'
    '// non-editorial inline content is removed, keep the seam explicit until a\n'
    '// final pass can decide whether the separator belongs before or after\n'
    '// punctuation. Source HTML control bytes are never copied into output, so\n'
    '// 0x1e cannot collide with real article text or the UTF-8 link markers.\n'
    "constexpr char RSS_REMOVAL_BOUNDARY = '\\x1e';\n",
    "removal boundary marker",
)

helper = r'''bool cleanupPunctuationAttachesLeft(const char value) {
  switch (value) {
    case '.':
    case ',':
    case ';':
    case ':':
    case '!':
    case '?':
    case '%':
    case ')':
    case ']':
    case '}':
      return true;
    default:
      return false;
  }
}

bool cleanupPunctuationNeedsFollowingSpace(const char value) {
  switch (value) {
    case '.':
    case ',':
    case ';':
    case ':':
    case '!':
    case '?':
    case '%':
    case ')':
    case ']':
    case '}':
      return true;
    default:
      return false;
  }
}

void appendRemovalBoundary(char* text, size_t& length) {
  if (!text || length == 0 || length >= MAX_TEXT_BYTES) return;
  const unsigned char previous = static_cast<unsigned char>(text[length - 1]);
  if (std::isspace(previous) || text[length - 1] == RSS_REMOVAL_BOUNDARY) return;
  appendChar(text, length, RSS_REMOVAL_BOUNDARY);
}

size_t normalizeRemovalBoundaries(char* text, const size_t length) {
  if (!text || length == 0) return 0;
  size_t read = 0;
  size_t write = 0;
  bool pendingBoundary = false;
  while (read < length) {
    const char value = text[read++];
    if (value == RSS_REMOVAL_BOUNDARY) {
      pendingBoundary = true;
      continue;
    }

    if (pendingBoundary) {
      const unsigned char c = static_cast<unsigned char>(value);
      if (std::isspace(c)) {
        // Real source whitespace/newline already separates both editorial sides.
        pendingBoundary = false;
      } else if (write == 0 || std::isspace(static_cast<unsigned char>(text[write - 1]))) {
        pendingBoundary = false;
      } else if (cleanupPunctuationAttachesLeft(value)) {
        // "phrase [removed].Suite" becomes "phrase. Suite" rather than either
        // "phrase .Suite" or "phrase.Suite".
        text[write++] = value;
        pendingBoundary = cleanupPunctuationNeedsFollowingSpace(value);
        continue;
      } else {
        text[write++] = ' ';
        pendingBoundary = false;
      }
    }
    text[write++] = value;
  }
  while (write > 0 && text[write - 1] == ' ') --write;
  text[write] = '\0';
  return write;
}

'''
replace_once(
    html,
    'bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {\n',
    helper + 'bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {\n',
    "boundary normalizer helpers",
)

extract_marker = 'bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'
replace_after(
    html,
    extract_marker,
    '''      if (startsWithInsensitive(html, end, pos, "<!--")) {
        const size_t close = findInsensitive(html, end, "-->", pos + 4);
        pos = close == std::string::npos ? end : close + 3;
        continue;
      }
''',
    '''      if (startsWithInsensitive(html, end, pos, "<!--")) {
        const size_t close = findInsensitive(html, end, "-->", pos + 4);
        const size_t afterRemoved = close == std::string::npos ? end : close + 3;
        if (textLength > 0 && afterRemoved < end) appendRemovalBoundary(text, textLength);
        pos = afterRemoved;
        continue;
      }
''',
    "comment removal boundary",
)
replace_after(
    html,
    extract_marker,
    '''      if (!tag.closing && htmlRawText(tag.name)) {
        pos = skipHtmlRaw(html, end, tag);
        continue;
      }
''',
    '''      if (!tag.closing && htmlRawText(tag.name)) {
        const size_t afterRemoved = skipHtmlRaw(html, end, tag);
        if (textLength > 0 && afterRemoved < end) appendRemovalBoundary(text, textLength);
        pos = afterRemoved;
        continue;
      }
''',
    "raw-text removal boundary",
)
replace_after(
    html,
    extract_marker,
    '''      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        continue;
      }
''',
    '''      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        if (textLength > 0 && pos < end) appendRemovalBoundary(text, textLength);
        continue;
      }
''',
    "noise-container removal boundary",
)
replace_after(
    html,
    extract_marker,
    '''          if (looksLikeVisibleUrl(text + anchorTextStart, textLength - anchorTextStart)) {
            textLength = anchorMarkerStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
          } else if (textLength > anchorTextStart) {
''',
    '''          if (looksLikeVisibleUrl(text + anchorTextStart, textLength - anchorTextStart)) {
            textLength = anchorMarkerStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
            if (next < end) appendRemovalBoundary(text, textLength);
          } else if (textLength > anchorTextStart) {
''',
    "visible-url anchor boundary",
)
replace_after(
    html,
    extract_marker,
    '''          } else {
            textLength = anchorMarkerStart;
          }
          inAnchor = false;
''',
    '''          } else {
            textLength = anchorMarkerStart;
            if (next < end) appendRemovalBoundary(text, textLength);
          }
          inAnchor = false;
''',
    "empty-anchor boundary",
)
replace_after(
    html,
    extract_marker,
    '''  const bool atCapacity = textLength >= MAX_TEXT_BYTES;
  while (textLength > 0 && (text[textLength - 1] == ' ' || text[textLength - 1] == '\n')) --textLength;
''',
    '''  const bool atCapacity = textLength >= MAX_TEXT_BYTES;
  textLength = normalizeRemovalBoundaries(text, textLength);
  while (textLength > 0 && (text[textLength - 1] == ' ' || text[textLength - 1] == '\n')) --textLength;
''',
    "final removal-boundary normalization",
)

# Fallback plain-URL removal uses the same seam marker. Consume only horizontal
# whitespace after a removed URL so paragraph/newline structure is preserved.
replace_once(
    "src/activities/home/RssArticleCache.cpp",
    '''    if (url) {
      while (read < length && !std::isspace(static_cast<unsigned char>(text[read]))) ++read;
      while (write > 0 && text[write - 1] == ' ') --write;
      if (read < length && write > 0) appendSpace(text, write);
      continue;
    }
''',
    '''    if (url) {
      while (read < length && !std::isspace(static_cast<unsigned char>(text[read]))) ++read;
      while (read < length && (text[read] == ' ' || text[read] == '\t')) ++read;
      while (write > 0 && text[write - 1] == ' ') --write;
      if (read < length && write > 0) appendRemovalBoundary(text, write);
      continue;
    }
''',
    "fallback URL boundary",
)
replace_once(
    "src/activities/home/RssArticleCache.cpp",
    '''  while (write > 0 && std::isspace(static_cast<unsigned char>(text[write - 1]))) --write;
  text[write] = '\0';
  return write;
}

size_t fallbackRuleCutoff''',
    '''  write = normalizeRemovalBoundaries(text, write);
  while (write > 0 && std::isspace(static_cast<unsigned char>(text[write - 1]))) --write;
  text[write] = '\0';
  return write;
}

size_t fallbackRuleCutoff''',
    "fallback URL final normalization",
)

# The Figaro mid-line share cleaner already used a literal space; replace that
# with the same seam marker so punctuation can attach to the previous sentence
# and still receive a following separator.
policy = "src/activities/home/RssArticleCachePolicy.inc"
replace_after(
    policy,
    'size_t stripFigaroShareControls(char* text, size_t length, const char* articleUrl) {',
    "      text[eraseStart] = ' ';\n",
    "      text[eraseStart] = RSS_REMOVAL_BOUNDARY;\n",
    "Figaro share seam marker",
)
replace_after(
    policy,
    'size_t stripFigaroShareControls(char* text, size_t length, const char* articleUrl) {',
    '''  return length;
}

bool buildFallbackText''',
    '''  return normalizeRemovalBoundaries(text, length);
}

bool buildFallbackText''',
    "Figaro share seam normalization",
)

# Host tests: protect word/word seams, punctuation seams, script/comment/noise
# removals, and both cache-generation markers.
test = "tests/rss/test_article_cache.cpp"
insert_after = '''  check(text.find("https://example.test/page") == std::string::npos && text.find("Source") != std::string::npos &&
            text.find("fin.") != std::string::npos,
        "URL used as anchor label is removed");
'''
extra = r'''

  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/page'>https://example.test/page</a>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos,
        "removed visible URL keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/page'>https://example.test/page</a>.Apres.</p></article>");
  check(text.find("Avant. Apres.") != std::string::npos,
        "removed visible URL moves the separator after punctuation");
  text = extract("<article><p>" + longBody + "</p><p>Avant<div class='share'>PARASITE</div>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos && text.find("PARASITE") == std::string::npos,
        "removed noise container keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<div class='share'>PARASITE</div>.Apres.</p></article>");
  check(text.find("Avant. Apres.") != std::string::npos,
        "removed noise container preserves punctuation spacing");
  text = extract("<article><p>" + longBody + "</p><p>Avant<script>parasite()</script>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos,
        "removed raw script keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<!-- parasite -->Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos,
        "removed HTML comment keeps a word boundary");
'''
replace_once(test, insert_after, insert_after + extra, "HTML removal seam tests")

figaro_anchor = '''  check(sharedMiddleOut == "Avant Apres", "Figaro mid-article share controls removed without losing prose");
'''
figaro_extra = r'''

  std::string sharedPunctuation = "Avant -Lien copie- Mail- X- Messenger.Apres";
  std::vector<char> sharedPunctuationBuffer(sharedPunctuation.begin(), sharedPunctuation.end());
  sharedPunctuationBuffer.push_back('\0');
  const size_t sharedPunctuationLength = RC::stripFigaroShareControls(
      sharedPunctuationBuffer.data(), sharedPunctuation.size(), "https://www.lefigaro.fr/test");
  check(std::string(sharedPunctuationBuffer.data(), sharedPunctuationLength) == "Avant. Apres",
        "Figaro share removal keeps punctuation readable");
'''
replace_once(test, figaro_anchor, figaro_anchor + figaro_extra, "Figaro punctuation seam test")

# Cache marker expectations move as one generation; previous XRSS11 is now the
# explicitly obsolete body generation.
path = Path(test)
text = path.read_text()
text = text.replace('XRSSF1\\n', 'XRSSF2\\n')
text = text.replace('XRSS11\\n', 'XRSS12\\n')
text = text.replace('full body keeps XRSS11 marker', 'full body keeps XRSS12 marker')
# After the expectation replacements, rewrite the explicit obsolete fixture to
# the immediately previous generation without changing the current checks.
text = text.replace('testFiles[RC::bodyPath(item)] = "XRSS10\\\\nAncien corps de developpement";',
                    'testFiles[RC::bodyPath(item)] = "XRSS11\\\\nAncien corps de developpement";')
path.write_text(text)

# A small direct fallback test catches raw URL seams outside HTML extraction.
replace_once(
    test,
    '''void cacheTests() {
  auto item = makeItem();
''',
    '''void cacheTests() {
  {
    char fallback[] = "Avant https://example.test/page Apres";
    const size_t cleaned = RC::removeFallbackUrls(fallback, std::strlen(fallback));
    check(std::string(fallback, cleaned) == "Avant Apres", "fallback URL removal keeps word boundary");
  }
  {
    char fallback[] = "Avant https://example.test/page .Apres";
    const size_t cleaned = RC::removeFallbackUrls(fallback, std::strlen(fallback));
    check(std::string(fallback, cleaned) == "Avant. Apres", "fallback URL removal fixes punctuation seam");
  }
  auto item = makeItem();
''',
    "fallback URL seam tests",
)

# Ensure no old current-generation marker is left in production and the new
# boundary normalizer is actually used by the three deletion paths.
production = Path("src/activities/home/RssArticleCache.cpp").read_text() + Path(html).read_text() + Path(policy).read_text()
checks = {
    "XRSS12 current body": 'BODY_MAGIC[] = "XRSS12\\n"' in production,
    "XRSSF2 current fallback": 'FALLBACK_MAGIC[] = "XRSSF2\\n"' in production,
    "old XRSS11 not current": 'BODY_MAGIC[] = "XRSS11\\n"' not in production,
    "boundary normalizer present": "normalizeRemovalBoundaries" in production,
    "noise seam protected": "noise-container removal boundary" not in production and "appendRemovalBoundary(text, textLength)" in Path(html).read_text(),
    "Figaro uses seam marker": "text[eraseStart] = RSS_REMOVAL_BOUNDARY;" in Path(policy).read_text(),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("candidate validation failed: " + ", ".join(failed))

print("Applied RSS removal-boundary spacing cleanup and XRSS12/XRSSF2 cache generation.")
