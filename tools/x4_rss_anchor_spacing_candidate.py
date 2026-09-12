from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))


# Extraction semantics change again, so invalidate current cleaned bodies
# cleanly. No migration/compatibility layer by project policy.
replace_once(
    "src/activities/home/RssArticleCache.cpp",
    'constexpr char BODY_MAGIC[] = "XRSS13\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF3\\n";',
    'constexpr char BODY_MAGIC[] = "XRSS14\\n";\nconstexpr char FALLBACK_MAGIC[] = "XRSSF4\\n";',
    "RSS body generation",
)

html_path = Path("src/activities/home/RssArticleHtml.inc")
html = html_path.read_text()

state_old = '''  size_t anchorTextStart = 0;
  size_t anchorMarkerStart = 0;
  bool anchorLeadingBoundary = false;
  bool inAnchor = false;
'''
state_new = '''  size_t anchorTextStart = 0;
  size_t anchorMarkerStart = 0;
  bool inAnchor = false;
'''
if html.count(state_old) != 1:
    raise SystemExit(f"anchor state: expected one match, found {html.count(state_old)}")
html = html.replace(state_old, state_new, 1)

anchor_old = '''      if (tagEquals(tag.name, "a")) {
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
anchor_new = '''      if (tagEquals(tag.name, "a")) {
        if (!tag.closing && !tag.selfClosing && !inAnchor) {
          // HTML/CSS frequently makes links visually separate even when the
          // source omits literal whitespace. Keep a semantic seam for every
          // anchor, not only long teaser/card links. Grammar that genuinely
          // binds to the link (apostrophe, opening parenthesis, etc.) is kept.
          if (textLength > 0 && !anchorBoundaryGluesAfterText(text, textLength)) {
            appendRemovalBoundary(text, textLength);
          }
          inAnchor = true;
          anchorMarkerStart = textLength;
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
            for (size_t i = 0; i < RSS_LINK_MARKER_BYTES; ++i) appendChar(text, textLength, RSS_LINK_END[i]);
            if (next < end && !anchorBoundaryGluesBeforeSource(html, end, next)) {
              appendRemovalBoundary(text, textLength);
            }
          } else {
            textLength = anchorMarkerStart;
            if (next < end) appendRemovalBoundary(text, textLength);
          }
          inAnchor = false;
        }
      }
'''
if html.count(anchor_old) != 1:
    raise SystemExit(f"anchor spacing logic: expected one match, found {html.count(anchor_old)}")
html = html.replace(anchor_old, anchor_new, 1)
html_path.write_text(html)

# Regressions copied from the on-device Figaro screenshots: the missing spaces
# were at short/ordinary anchor boundaries, so the previous long-card threshold
# could never fix them.
test_path = Path("tests/rss/test_article_cache.cpp")
tests = test_path.read_text()
insert_after = '''  text = extract("<article><p>" + longBody +
                 "</p><p>l'<a href='https://example.test/apple'>Apple</a> reste un lien inline.</p></article>");
  check(text.find(std::string("l'") + "\\xEE\\x80\\x80" + "Apple" + "\\xEE\\x80\\x81" +
                  " reste un lien inline.") != std::string::npos,
        "short inline anchor keeps apostrophe grammar unchanged");
'''
new_tests = insert_after + '''

  const std::string linkStart = "\\xEE\\x80\\x80";
  const std::string linkEnd = "\\xEE\\x80\\x81";
  text = extract("<article><p>" + longBody +
                 "</p><p>du Sénat publié en 2024.<a href='https://example.test/discover'>À découvrir</a> "
                 "PODCAST - <a href='https://example.test/club'>Écoutez le club Le Figaro International</a>Pour éviter "
                 "cette route, voir le <a href='https://example.test/report'>rapport</a>du Sénat.</p></article>");
  check(text.find(std::string("2024. ") + linkStart + "À découvrir") != std::string::npos,
        "short/ordinary link gets a boundary after sentence punctuation");
  check(text.find(std::string("International") + linkEnd + " Pour éviter") != std::string::npos,
        "ordinary link gets a boundary before following prose");
  check(text.find(std::string("rapport") + linkEnd + " du Sénat") != std::string::npos,
        "short link gets a boundary before following prose");

  text = extract("<article><p>" + longBody +
                 "</p><p>Avant<a href='https://example.test/mot'>mot</a>.Suite.</p></article>");
  check(text.find(std::string("Avant ") + linkStart + "mot" + linkEnd + ". Suite.") != std::string::npos,
        "ordinary link keeps punctuation attached then separates next sentence");
'''
if tests.count(insert_after) != 1:
    raise SystemExit(f"Figaro anchor regression insertion: expected one match, found {tests.count(insert_after)}")
tests = tests.replace(insert_after, new_tests, 1)

# Current cache markers in host tests.
tests = tests.replace('"XRSSF3\\n"', '"XRSSF4\\n"')
tests = tests.replace('"XRSS13\\n"', '"XRSS14\\n"')
tests = tests.replace('"XRSS12\\nAncien corps de developpement"', '"XRSS13\\nAncien corps de developpement"')
tests = tests.replace('"full body keeps XRSS12 marker"', '"full body keeps current marker"')

test_path.write_text(tests)
print("Applied all-anchor RSS spacing fix and XRSS14/XRSSF4 invalidation")
