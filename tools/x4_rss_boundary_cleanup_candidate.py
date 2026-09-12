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
cache = replace_once(cache, 'constexpr char FALLBACK_MAGIC[] = "XRSSF4\\n";',
                     'constexpr char FALLBACK_MAGIC[] = "XRSSF5\\n";', "fallback cache generation")
old_fallback = '''      if (tagLength > 0) {
        if (tagEquals(tagName, "br") || tagEquals(tagName, "li") || tagEquals(tagName, "tr") ||
            tagEquals(tagName, "dt") || tagEquals(tagName, "dd")) {
          appendLineBreak(text, write);
        } else if (isParagraphTag(tagName)) {
          appendParagraphBreak(text, write);
        }
      }
'''
new_fallback = '''      if (tagLength > 0) {
        if (tagEquals(tagName, "br") || tagEquals(tagName, "li") || tagEquals(tagName, "tr") ||
            tagEquals(tagName, "dt") || tagEquals(tagName, "dd")) {
          appendLineBreak(text, write);
        } else if (isParagraphTag(tagName)) {
          appendParagraphBreak(text, write);
        } else if (tagEquals(tagName, "a") || semanticInlineBoundaryTag(tagName)) {
          // Feed summaries use the same CSS-style inline wrappers as full
          // articles. Keep their semantic seams when stripping markup too.
          appendRemovalBoundary(text, write);
        }
      }
'''
cache = replace_once(cache, old_fallback, new_fallback, "fallback inline boundaries")
old_fallback_tail = '''  while (write > 0 && (text[write - 1] == ' ' || text[write - 1] == '\\n')) --write;
  text[write] = '\\0';
  return write;
}

size_t removeFallbackUrls'''
new_fallback_tail = '''  write = normalizeRemovalBoundaries(text, write);
  while (write > 0 && (text[write - 1] == ' ' || text[write - 1] == '\\n')) --write;
  text[write] = '\\0';
  return write;
}

size_t removeFallbackUrls'''
cache = replace_once(cache, old_fallback_tail, new_fallback_tail, "fallback boundary normalization")
cache_path.write_text(cache)

html_path = root / "src/activities/home/RssArticleHtml.inc"
html = html_path.read_text()
needle = '''bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'''
helper = '''bool semanticInlineBoundaryTag(const char* name) {
  // Modern news templates often use inline elements as CSS grid/flex cells.
  // Their visual separation can exist without any literal whitespace in the
  // HTML source. Preserve that semantic seam, while deliberately excluding
  // sub/sup/code where character-level attachment is commonly meaningful.
  return tagEquals(name, "span") || tagEquals(name, "strong") || tagEquals(name, "b") ||
         tagEquals(name, "em") || tagEquals(name, "i") || tagEquals(name, "u") ||
         tagEquals(name, "small") || tagEquals(name, "mark") || tagEquals(name, "label") ||
         tagEquals(name, "time") || tagEquals(name, "abbr") || tagEquals(name, "cite");
}

bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'''
html = replace_once(html, needle, helper, "semantic inline helper")
old_anchor_end = '''          inAnchor = false;
        }
      }
      if (tagEquals(tag.name, "br") || tagEquals(tag.name, "tr") || tagEquals(tag.name, "dt") || tagEquals(tag.name, "dd")) {'''
new_anchor_end = '''          inAnchor = false;
        }
      }
      if (!tagEquals(tag.name, "a") && semanticInlineBoundaryTag(tag.name) && !inAnchor) {
        // CSS wrappers can be visually separate text cells even when their raw
        // HTML is adjacent. Mark both sides as semantic seams; the final
        // normalizer still keeps apostrophes, slashes, brackets and hyphens
        // attached when they are genuine grammar rather than missing spaces.
        if (!tag.closing) {
          if (textLength > 0 && !anchorBoundaryGluesAfterText(text, textLength)) {
            appendRemovalBoundary(text, textLength);
          }
        } else if (textLength > 0 && next < end && !anchorBoundaryGluesBeforeSource(html, end, next)) {
          appendRemovalBoundary(text, textLength);
        }
      }
      if (tagEquals(tag.name, "br") || tagEquals(tag.name, "tr") || tagEquals(tag.name, "dt") || tagEquals(tag.name, "dd")) {'''
html = replace_once(html, old_anchor_end, new_anchor_end, "semantic inline extraction boundaries")
html_path.write_text(html)

test_path = root / "tests/rss/test_article_cache.cpp"
test = test_path.read_text()
insert_before = '''  bool ok = true;
  extract("<article><p>" + std::string(RC::MAX_TEXT_BYTES + 100, 'x') + "</p></article>", &ok);'''
new_tests = r'''  // Screenshot regressions: news sites increasingly use inline wrappers as
  // CSS grid/flex cells. The browser shows separation even when the raw HTML
  // contains no literal whitespace between those cells.
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
        "Futura inline wrappers do not concatenate prose");

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

  // Inline emphasis inside real grammar must stay attached.
  text = extract("<article><p>" + longBody +
                 "</p><p>l'<strong>Europe</strong> et e-<span>mail</span> restent corrects.</p></article>");
  check(text.find("l'Europe et e-mail restent corrects.") != std::string::npos,
        "semantic wrapper spacing preserves apostrophe and hyphen grammar");

  bool ok = true;
  extract("<article><p>" + std::string(RC::MAX_TEXT_BYTES + 100, 'x') + "</p></article>", &ok);'''
test = replace_once(test, insert_before, new_tests, "screenshot regression tests")
test_path.write_text(test)

print("Applied RSS semantic-boundary candidate and cache generation XRSS15/XRSSF5")
