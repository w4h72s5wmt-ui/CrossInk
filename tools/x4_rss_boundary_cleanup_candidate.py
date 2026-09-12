from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

cache_path = root / "src/activities/home/RssArticleCache.cpp"
cache = cache_path.read_text()
cache = replace_once(cache, 'constexpr char BODY_MAGIC[] = "XRSS14\\n";',
                     'constexpr char BODY_MAGIC[] = "XRSS15\\n";', "body cache generation")
cache_path.write_text(cache)

html_path = root / "src/activities/home/RssArticleHtml.inc"
html = html_path.read_text()
needle = '''bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'''
helper = '''bool semanticInlineBoundaryTag(const char* name) {
  // Modern news templates often build flex/grid rows from adjacent inline
  // wrappers. We only separate sibling wrappers; ordinary inline emphasis is
  // deliberately left untouched so <strong>mot</strong>s stays "mots".
  return tagEquals(name, "span") || tagEquals(name, "strong") || tagEquals(name, "b") ||
         tagEquals(name, "em") || tagEquals(name, "i") || tagEquals(name, "u") ||
         tagEquals(name, "small") || tagEquals(name, "mark") || tagEquals(name, "label") ||
         tagEquals(name, "time") || tagEquals(name, "abbr") || tagEquals(name, "cite");
}

bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'''
html = replace_once(html, needle, helper, "semantic inline helper")
html = replace_once(html, '''  bool inAnchor = false;
  while (pos < end && textLength < MAX_TEXT_BYTES) {''',
'''  bool inAnchor = false;
  bool closedSemanticInline = false;
  while (pos < end && textLength < MAX_TEXT_BYTES) {''', "inline sibling state")
old_after_parse = '''      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {
        pos = next;
        continue;
      }
'''
new_after_parse = '''      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {
        closedSemanticInline = false;
        pos = next;
        continue;
      }
      const bool semanticInline = semanticInlineBoundaryTag(tag.name);
      if (!tag.closing && semanticInline && closedSemanticInline && !inAnchor && textLength > 0 &&
          !anchorBoundaryGluesAfterText(text, textLength)) {
        // Adjacent wrappers are commonly independent CSS cells despite having
        // no literal whitespace in source: </span><strong>, </span><span>, …
        appendRemovalBoundary(text, textLength);
      }
      if (!tag.closing) closedSemanticInline = false;
'''
html = replace_once(html, old_after_parse, new_after_parse, "detect adjacent inline siblings")
old_anchor_end = '''          inAnchor = false;
        }
      }
      if (tagEquals(tag.name, "br") || tagEquals(tag.name, "tr") || tagEquals(tag.name, "dt") || tagEquals(tag.name, "dd")) {'''
new_anchor_end = '''          inAnchor = false;
        }
      }
      if (tag.closing && semanticInline && !inAnchor) closedSemanticInline = true;
      if (tagEquals(tag.name, "br") || tagEquals(tag.name, "tr") || tagEquals(tag.name, "dt") || tagEquals(tag.name, "dd")) {'''
html = replace_once(html, old_anchor_end, new_anchor_end, "remember closed inline sibling")
html = replace_once(html, '''    if (html[pos] == '&') { pos = decodeEntityUtf8(html, end, pos, text, textLength); continue; }
    const unsigned char c = static_cast<unsigned char>(html[pos++]);
    if (htmlSpace(static_cast<char>(c))) appendSpace(text, textLength);
    else if (c >= 0x20) appendChar(text, textLength, static_cast<char>(c));
''',
'''    if (html[pos] == '&') {
      closedSemanticInline = false;
      pos = decodeEntityUtf8(html, end, pos, text, textLength);
      continue;
    }
    closedSemanticInline = false;
    const unsigned char c = static_cast<unsigned char>(html[pos++]);
    if (htmlSpace(static_cast<char>(c))) appendSpace(text, textLength);
    else if (c >= 0x20) appendChar(text, textLength, static_cast<char>(c));
''', "clear sibling state on source text")
html_path.write_text(html)

test_path = root / "tests/rss/test_article_cache.cpp"
test = test_path.read_text()
insert_before = '''  bool ok = true;
  extract("<article><p>" + std::string(RC::MAX_TEXT_BYTES + 100, 'x') + "</p></article>", &ok);'''
new_tests = r'''  // Screenshot regressions: modern news templates use adjacent inline wrappers
  // as flex/grid cells. Browsers separate those cells even with no whitespace
  // in source, so preserve a seam specifically between sibling wrappers.
  text = extract("<article><p>" + longBody +
                 "</p><p><span>technique</span><strong>Modèle</strong><span>Suunto Run 2</span>"
                 "<span>Dimensions</span><span>46 mm x 46 mm x 11,7 mm</span>"
                 "<span>Définition de l’écran</span><span>466 x 466 pixels</span>"
                 "<span>Dalle AMOLED</span><span>Mémoire interne</span><span>4,64 Go</span></p></article>");
  check(text.find("technique Modèle Suunto Run 2 Dimensions 46 mm x 46 mm x 11,7 mm "
                  "Définition de l’écran 466 x 466 pixels Dalle AMOLED Mémoire interne 4,64 Go") !=
            std::string::npos,
        "Frandroid spec cells keep semantic spaces");

  text = extract("<article><p>" + longBody +
                 "</p><p><span>sélection que l'on n'attendait pas.</span>"
                 "<strong>Un environnement taillé pour les bactéries</strong>"
                 "<span>Trois conditions se cumulent dans une</span><span>éponge de cuisine</span>"
                 "<span>stable.</span><strong>Le contraste reste lisible.</strong></p></article>");
  check(text.find("pas. Un environnement taillé pour les bactéries Trois conditions") != std::string::npos &&
            text.find("dans une éponge de cuisine stable. Le contraste") != std::string::npos,
        "Futura sibling wrappers do not concatenate prose");

  text = extract("<article><p>" + longBody +
                 "</p><p>Pour être vendu ce prix-là, même sans<a href='https://example.test/darty'>"
                 "la réduction de 50 euros sur Darty</a>pendant les<a href='https://example.test/french-days'>"
                 "French Days</a>, il faut une offre solide.</p></article>");
  check(text.find(std::string("même sans ") + linkStart + "la réduction de 50 euros sur Darty" + linkEnd +
                  " pendant les " + linkStart + "French Days" + linkEnd + ", il faut") != std::string::npos,
        "Frandroid adjacent links keep boundaries on both sides");

  text = extract("<article><p>" + longBody +
                 "</p><p>Mouammar.<a href='https://example.test/discover'>À découvrir</a> "
                 "- PODCAST - <a href='https://example.test/club'>Écoutez le club Le Figaro International</a>"
                 "L’armée n’était pas prête.</p></article>");
  check(text.find(std::string("Mouammar. ") + linkStart + "À découvrir" + linkEnd + " - PODCAST - " +
                  linkStart + "Écoutez le club Le Figaro International" + linkEnd + " L’armée") !=
            std::string::npos,
        "Figaro adjacent links keep screenshot boundaries");

  // Ordinary inline formatting is not a cell boundary and must not split words.
  text = extract("<article><p>" + longBody +
                 "</p><p>l'<strong>Europe</strong> et e-<span>mail</span> puis <strong>mot</strong>s.</p></article>");
  check(text.find("l'Europe et e-mail puis mots.") != std::string::npos,
        "inline formatting preserves apostrophe, hyphen and suffix grammar");

  bool ok = true;
  extract("<article><p>" + std::string(RC::MAX_TEXT_BYTES + 100, 'x') + "</p></article>", &ok);'''
test = replace_once(test, insert_before, new_tests, "screenshot regression tests")
test_path.write_text(test)

print("Applied sibling-boundary RSS candidate and body cache generation XRSS15")
