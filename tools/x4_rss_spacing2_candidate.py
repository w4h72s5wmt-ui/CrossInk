from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))


# Old cleaned article bodies already contain the bad seams, so invalidate them
# cleanly. No migration/compatibility layer by project policy.
replace_once(
    "src/activities/home/RssArticleCache.cpp",
    'constexpr char BODY_MAGIC[] = "XRSS12\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF2\\n";',
    'constexpr char BODY_MAGIC[] = "XRSS13\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF3\\n";',
    "RSS body generation",
)

html_path = Path("src/activities/home/RssArticleHtml.inc")
html = html_path.read_text()

anchor_state_old = '''  size_t anchorTextStart = 0;
  size_t anchorMarkerStart = 0;
  bool inAnchor = false;
'''
anchor_state_new = '''  size_t anchorTextStart = 0;
  size_t anchorMarkerStart = 0;
  bool anchorLeadingBoundary = false;
  bool inAnchor = false;
'''
if html.count(anchor_state_old) != 1:
    raise SystemExit(f"anchor state: expected one match, found {html.count(anchor_state_old)}")
html = html.replace(anchor_state_old, anchor_state_new, 1)

helper_anchor = '''bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {
'''
helper_code = '''bool anchorBoundaryGluesAfterText(const char* text, const size_t length) {
  if (!text || length == 0) return true;
  const unsigned char last = static_cast<unsigned char>(text[length - 1]);
  if (std::isspace(last) || text[length - 1] == RSS_REMOVAL_BOUNDARY) return true;
  switch (text[length - 1]) {
    case '\\'':
    case '"':
    case '-':
    case '/':
    case '(':
    case '[':
    case '{':
      return true;
    default:
      break;
  }
  if (length >= 3) {
    const unsigned char a = static_cast<unsigned char>(text[length - 3]);
    const unsigned char b = static_cast<unsigned char>(text[length - 2]);
    const unsigned char c = static_cast<unsigned char>(text[length - 1]);
    // Curly apostrophes/opening quote can legitimately bind directly to the
    // following linked phrase. A closing quote is intentionally not included:
    // a card following quoted prose still needs a separator.
    if (a == 0xe2 && b == 0x80 && (c == 0x98 || c == 0x99 || c == 0x9c)) return true;
  }
  return false;
}

bool anchorBoundaryGluesBeforeSource(const char* html, const size_t length, const size_t pos) {
  if (!html || pos >= length) return true;
  const unsigned char c = static_cast<unsigned char>(html[pos]);
  if (htmlSpace(static_cast<char>(c))) return true;
  if (html[pos] == '\\'' || html[pos] == '"' || html[pos] == '-' || html[pos] == '/') return true;
  if (pos + 3 <= length && c == 0xe2 && static_cast<unsigned char>(html[pos + 1]) == 0x80) {
    const unsigned char tail = static_cast<unsigned char>(html[pos + 2]);
    if (tail == 0x99 || tail == 0x9d) return true;  // closing curly quote/apostrophe
  }
  static constexpr const char* GLUE_ENTITIES[] = {
      "&apos;", "&rsquo;", "&#39;", "&#x27;", "&#8217;", "&#x2019;",
  };
  for (const char* entity : GLUE_ENTITIES) {
    if (startsWithInsensitive(html, length, pos, entity)) return true;
  }
  return false;
}

bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {
'''
if html.count(helper_anchor) != 1:
    raise SystemExit(f"helper insertion: expected one match, found {html.count(helper_anchor)}")
html = html.replace(helper_anchor, helper_code, 1)

noise_block = '''      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        if (textLength > 0 && pos < end) appendRemovalBoundary(text, textLength);
        continue;
      }
      if (tagEquals(tag.name, "a")) {
'''
media_block = '''      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        if (textLength > 0 && pos < end) appendRemovalBoundary(text, textLength);
        continue;
      }
      // Images and <source> nodes contribute no visible text to our reader.
      // Preserve a seam when they sit directly between prose/caption text so
      // "phrase.<img>© Crédit" cannot collapse into "phrase.© Crédit".
      if (!tag.closing && (tagEquals(tag.name, "img") || tagEquals(tag.name, "source"))) {
        if (!inAnchor && textLength > 0 && next < end) appendRemovalBoundary(text, textLength);
        pos = next;
        continue;
      }
      if (tagEquals(tag.name, "a")) {
'''
if html.count(noise_block) != 1:
    raise SystemExit(f"media seam insertion: expected one match, found {html.count(noise_block)}")
html = html.replace(noise_block, media_block, 1)

anchor_old = '''      if (tagEquals(tag.name, "a")) {
        if (!tag.closing && !tag.selfClosing && !inAnchor) {
          inAnchor = true;
          anchorMarkerStart = textLength;
          for (size_t i = 0; i < RSS_LINK_MARKER_BYTES; ++i) appendChar(text, textLength, RSS_LINK_START[i]);
          anchorTextStart = textLength;
        } else if (tag.closing && inAnchor) {
          if (looksLikeVisibleUrl(text + anchorTextStart, textLength - anchorTextStart)) {
            textLength = anchorMarkerStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
            if (next < end) appendRemovalBoundary(text, textLength);
          } else if (textLength > anchorTextStart) {
            for (size_t i = 0; i < RSS_LINK_MARKER_BYTES; ++i) appendChar(text, textLength, RSS_LINK_END[i]);
          } else {
            textLength = anchorMarkerStart;
            if (next < end) appendRemovalBoundary(text, textLength);
          }
          inAnchor = false;
        }
      }
'''
anchor_new = '''      if (tagEquals(tag.name, "a")) {
        if (!tag.closing && !tag.selfClosing && !inAnchor) {
          inAnchor = true;
          anchorMarkerStart = textLength;
          anchorLeadingBoundary = textLength > 0 && !anchorBoundaryGluesAfterText(text, textLength);
          for (size_t i = 0; i < RSS_LINK_MARKER_BYTES; ++i) appendChar(text, textLength, RSS_LINK_START[i]);
          anchorTextStart = textLength;
        } else if (tag.closing && inAnchor) {
          const size_t anchorTextBytes = textLength > anchorTextStart ? textLength - anchorTextStart : 0;
          if (looksLikeVisibleUrl(text + anchorTextStart, anchorTextBytes)) {
            textLength = anchorMarkerStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
            if (next < end) appendRemovalBoundary(text, textLength);
          } else if (anchorTextBytes > 0) {
            // Long linked labels are frequently CSS cards/teasers. Their HTML
            // often has no literal whitespace around the <a>, even though the
            // browser lays them out as separate blocks. Only repair these long
            // labels; short inline links keep their exact grammar.
            const bool cardLikeAnchor = anchorTextBytes >= 24;
            if (cardLikeAnchor && anchorLeadingBoundary && textLength < MAX_TEXT_BYTES) {
              std::memmove(text + anchorMarkerStart + 1, text + anchorMarkerStart,
                           textLength - anchorMarkerStart);
              text[anchorMarkerStart] = RSS_REMOVAL_BOUNDARY;
              ++textLength;
            }
            for (size_t i = 0; i < RSS_LINK_MARKER_BYTES; ++i) appendChar(text, textLength, RSS_LINK_END[i]);
            if (cardLikeAnchor && next < end && !anchorBoundaryGluesBeforeSource(html, end, next)) {
              appendRemovalBoundary(text, textLength);
            }
          } else {
            textLength = anchorMarkerStart;
            if (next < end) appendRemovalBoundary(text, textLength);
          }
          anchorLeadingBoundary = false;
          inAnchor = false;
        }
      }
'''
if html.count(anchor_old) != 1:
    raise SystemExit(f"anchor seam logic: expected one match, found {html.count(anchor_old)}")
html = html.replace(anchor_old, anchor_new, 1)
html_path.write_text(html)

# Add exact regressions based on the user's Futura screenshots.
test_path = Path("tests/rss/test_article_cache.cpp")
tests = test_path.read_text()
insert_after = '''  text = extract("<article><p>" + longBody + "</p><p>Avant<!-- parasite -->Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos, "removed HTML comment keeps a word boundary");
'''
new_tests = insert_after + '''

  text = extract("<article><p>" + longBody +
                 "</p><p>bilan médical.<img src='apple.jpg'>© Apple suite.</p></article>");
  check(text.find("bilan médical. © Apple suite.") != std::string::npos,
        "discarded image keeps caption boundary after punctuation");

  const std::string futuraCardTitle =
      "À quel âge commence-t-on vraiment à vieillir ? Une étude de Stanford nous donne la réponse";
  text = extract("<article><p>" + longBody +
                 "</p><p>© Apple<a href='https://example.test/card'>" + futuraCardTitle +
                 "</a>44 ans, 60 ans : deux moments clés.</p></article>");
  check(text.find(std::string("© Apple ") + "\\xEE\\x80\\x80" + futuraCardTitle) != std::string::npos &&
            text.find(futuraCardTitle + std::string("\\xEE\\x80\\x81") + " 44 ans, 60 ans") != std::string::npos,
        "long Futura-style card link keeps boundaries on both sides");

  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/card'>" +
                 futuraCardTitle + "</a>.Suite.</p></article>");
  check(text.find(futuraCardTitle + std::string("\\xEE\\x80\\x81") + ". Suite.") != std::string::npos,
        "long card link keeps punctuation attached then separates following prose");

  text = extract("<article><p>" + longBody +
                 "</p><p>l'<a href='https://example.test/apple'>Apple</a> reste un lien inline.</p></article>");
  check(text.find(std::string("l'") + "\\xEE\\x80\\x80" + "Apple" + "\\xEE\\x80\\x81" +
                  " reste un lien inline.") != std::string::npos,
        "short inline anchor keeps apostrophe grammar unchanged");
'''
if tests.count(insert_after) != 1:
    raise SystemExit(f"spacing regression insertion: expected one match, found {tests.count(insert_after)}")
tests = tests.replace(insert_after, new_tests, 1)

replacements = {
    '"XRSSF2\\n"': '"XRSSF3\\n"',
    '"XRSS12\\n"': '"XRSS13\\n"',
    '"fallback has distinct SD marker"': '"fallback has current SD marker"',
    'testFiles[RC::bodyPath(item)] = "XRSS11\\\\nAncien corps de developpement";':
        'testFiles[RC::bodyPath(item)] = "XRSS12\\nAncien corps de developpement";',
    '"obsolete marker rejected"': '"previous body generation rejected"',
    '"refetched full body version"': '"refetched current full body version"',
}
for old, new in replacements.items():
    if old not in tests:
        raise SystemExit(f"test marker replacement missing: {old}")
    tests = tests.replace(old, new)

test_path.write_text(tests)
print("Applied structural RSS spacing fix and XRSS13/XRSSF3 invalidation")
