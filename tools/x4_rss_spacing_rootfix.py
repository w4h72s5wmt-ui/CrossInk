from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


html_path = Path("src/activities/home/RssArticleHtml.inc")
html = html_path.read_text()

helper_anchor = '''bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {'''
helper_insert = '''bool inlineBoundaryGlueTag(const char* name) {
  // These tags commonly decorate a word/value itself. Crossing them must not
  // manufacture a word boundary (x<sup>2</sup>, H<sub>2</sub>O, ruby, ...).
  return tagEquals(name, "sup") || tagEquals(name, "sub") || tagEquals(name, "wbr") ||
         tagEquals(name, "ruby") || tagEquals(name, "rt") || tagEquals(name, "rp");
}

bool rawStructuralBoundaryTag(const char* name) {
  // Strong structural fields may touch raw prose in source even though CSS
  // renders them as separate cells/rows. Plain <span> is intentionally NOT in
  // this list: <span>mot</span>s must remain "mots".
  return tagEquals(name, "label") || tagEquals(name, "time") || tagEquals(name, "figcaption") ||
         tagEquals(name, "figure") || tagEquals(name, "summary") || tagEquals(name, "data") ||
         tagEquals(name, "output") || std::strchr(name, '-') != nullptr;
}

bool pendingInlineNeedsRawBoundary(const char* text, const size_t length) {
  if (!text || length == 0) return false;
  size_t pos = length;
  while (pos > 0 && (text[pos - 1] == RSS_REMOVAL_BOUNDARY ||
                     std::isspace(static_cast<unsigned char>(text[pos - 1])))) --pos;
  if (pos == 0) return false;
  return cleanupPunctuationNeedsFollowingSpace(text[pos - 1]);
}

''' + helper_anchor
html = replace_once(html, helper_anchor, helper_insert, "insert boundary helpers")

html = replace_once(
    html,
    '''  bool inAnchor = false;\n  bool closedSemanticInline = false;''',
    '''  bool inAnchor = false;\n  bool pendingElementBoundary = false;\n  bool pendingRawBoundary = false;''',
    "replace inline boundary state",
)

html = replace_once(
    html,
    '''      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {\n        closedSemanticInline = false;\n        pos = next;\n        continue;\n      }\n      const bool semanticInline = semanticInlineBoundaryTag(tag.name);\n      if (!tag.closing && semanticInline && closedSemanticInline && !inAnchor && textLength > 0 &&\n          !anchorBoundaryGluesAfterText(text, textLength)) {\n        // Adjacent wrappers are commonly independent CSS cells despite having\n        // no literal whitespace in source: </span><strong>, </span><span>, …\n        appendRemovalBoundary(text, textLength);\n      }\n      if (!tag.closing) closedSemanticInline = false;''',
    '''      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {\n        pendingElementBoundary = false;\n        pendingRawBoundary = false;\n        pos = next;\n        continue;\n      }\n      const bool semanticInline = semanticInlineBoundaryTag(tag.name);\n      const bool structuralInline = rawStructuralBoundaryTag(tag.name);\n      const bool glueTag = inlineBoundaryGlueTag(tag.name);\n      if (!tag.closing) {\n        // Keep a semantic seam alive through closing parent wrappers. This is\n        // the real-page case missed by the old immediate </span><span> rule:\n        // </span></data><data><span> must still separate the two cells.\n        if ((pendingElementBoundary || structuralInline) && !glueTag && !inAnchor && textLength > 0 &&\n            !anchorBoundaryGluesAfterText(text, textLength)) {\n          appendRemovalBoundary(text, textLength);\n        }\n        pendingElementBoundary = false;\n        pendingRawBoundary = false;\n      }''',
    "replace opening boundary logic",
)

html = replace_once(
    html,
    '''      if (tag.closing && semanticInline && !inAnchor) closedSemanticInline = true;''',
    '''      if (tag.closing && !inAnchor && !tagEquals(tag.name, "a") && !glueTag &&\n          (semanticInline || structuralInline)) {\n        // Closing parents must not erase the fact that visible text just ended.\n        pendingElementBoundary = true;\n        pendingRawBoundary = pendingRawBoundary || structuralInline;\n      }''',
    "replace closing boundary logic",
)

html = replace_once(
    html,
    '''    if (html[pos] == '&') {\n      closedSemanticInline = false;\n      pos = decodeEntityUtf8(html, end, pos, text, textLength);\n      continue;\n    }\n    closedSemanticInline = false;\n    const unsigned char c = static_cast<unsigned char>(html[pos++]);''',
    '''    if (html[pos] == '&') {\n      if ((pendingRawBoundary || (pendingElementBoundary && pendingInlineNeedsRawBoundary(text, textLength))) &&\n          !inAnchor && textLength > 0 && !anchorBoundaryGluesAfterText(text, textLength) &&\n          !anchorBoundaryGluesBeforeSource(html, end, pos)) {\n        appendRemovalBoundary(text, textLength);\n      }\n      pendingElementBoundary = false;\n      pendingRawBoundary = false;\n      pos = decodeEntityUtf8(html, end, pos, text, textLength);\n      continue;\n    }\n    if ((pendingRawBoundary || (pendingElementBoundary && pendingInlineNeedsRawBoundary(text, textLength))) &&\n        !inAnchor && textLength > 0 && !anchorBoundaryGluesAfterText(text, textLength) &&\n        !anchorBoundaryGluesBeforeSource(html, end, pos)) {\n      appendRemovalBoundary(text, textLength);\n    }\n    pendingElementBoundary = false;\n    pendingRawBoundary = false;\n    const unsigned char c = static_cast<unsigned char>(html[pos++]);''',
    "replace raw/entity boundary consumption",
)

# Whitespace entities already provide their own separation. Treat them as a
# source-side glue condition so no synthetic boundary is added before decoding.
html = replace_once(
    html,
    '''  static constexpr const char* GLUE_ENTITIES[] = {\n      "&apos;", "&rsquo;", "&#39;", "&#x27;", "&#8217;", "&#x2019;",\n  };''',
    '''  static constexpr const char* GLUE_ENTITIES[] = {\n      "&apos;", "&rsquo;", "&#39;", "&#x27;", "&#8217;", "&#x2019;",\n      "&nbsp;", "&#32;", "&#x20;", "&#160;", "&#xa0;",\n  };''',
    "extend source glue entities",
)

html_path.write_text(html)

rich_path = Path("src/activities/home/RssArticleRichText.h")
rich = rich_path.read_text()
rich = replace_once(
    rich,
    '''    const int width = renderer.getTextWidth(fontId, segment.c_str());''',
    '''    // Link markup splits one visual line into independently drawn segments.\n    // getTextWidth() is a visual bbox for flash fonts and can omit a trailing\n    // space, making the following underlined segment look glued. Advance by the\n    // same metric drawText() uses instead.\n    const int width = renderer.getTextAdvanceX(fontId, segment.c_str(), EpdFontFamily::REGULAR);''',
    "use text advance for rich segments",
)
rich_path.write_text(rich)

cache_path = Path("src/activities/home/RssArticleCache.cpp")
cache = cache_path.read_text()
if cache.count('XRSS15\\n') != 1:
    raise SystemExit(f"cache marker: expected 1 XRSS15 marker, found {cache.count('XRSS15\\n')}")
cache = cache.replace('XRSS15\\n', 'XRSS16\\n', 1)
cache_path.write_text(cache)

test_path = Path("tests/rss/test_article_cache.cpp")
test = test_path.read_text()
insert_before = '''  // Ordinary inline formatting is not a cell boundary and must not split words.\n'''
new_tests = r'''  // Real screenshot shapes missed by the direct-sibling-only implementation:
  // cells can be nested, and a structural field can touch raw prose/entities.
  text = extract("<article><p>" + longBody +
                 "</p><p><data><span>très chaud.</span></data><data><span>Une vapeur très chaude</span></data>"
                 "<data><span>classiques.</span></data><data>Dans le sous-sol</data></p></article>");
  check(text.find("très chaud. Une vapeur très chaude classiques. Dans le sous-sol") != std::string::npos,
        "nested Science-style fields preserve prose boundaries");

  text = extract("<article><p>" + longBody +
                 "</p><p><data><span>Fiche technique</span></data><data>Modèle</data><data><span>Oppo Pad 5</span></data>"
                 "<data>Dimensions</data><data><span>266,01 x 192,77 mm</span></data></p></article>");
  check(text.find("Fiche technique Modèle Oppo Pad 5 Dimensions 266,01 x 192,77 mm") != std::string::npos,
        "nested Frandroid spec fields preserve cell boundaries");

  text = extract("<article><p>" + longBody +
                 "</p><p><span>Trois conditions se cumulent dans une</span>&eacute;ponge de cuisine "
                 "<span>stable.</span>Le contraste reste lisible.</p></article>");
  check(text.find("dans uneéponge de cuisine stable. Le contraste") != std::string::npos,
        "plain span does not invent a space before entity, sentence seam remains readable");

  text = extract("<article><p>" + longBody +
                 "</p><p><span>Futura</span>Secrétaire de rédaction<data>14 min.</data>Publié le 6 juillet. "
                 "<figcaption>iStock</figcaption>Jusqu'à présent.</p></article>");
  check(text.find("FuturaSecrétaire de rédaction 14 min. Publié le 6 juillet. iStock Jusqu'à présent.") !=
            std::string::npos,
        "strong metadata/caption boundaries survive raw text transitions");

  text = extract("<article><p>" + longBody +
                 "</p><p><span>Bastié.</span>La valeur du texte doit rester lisible. "
                 "<span>aboutir.</span>En route vers la suite.</p></article>");
  check(text.find("Bastié. La valeur du texte doit rester lisible. aboutir. En route") != std::string::npos,
        "sentence punctuation across plain spans preserves following space");

  text = extract("<article><p>" + longBody +
                 "</p><p><span>mot</span>s, l'<span>Europe</span> et e-<span>mail</span>.</p></article>");
  check(text.find("mots, l'Europe et e-mail.") != std::string::npos,
        "plain span suffix/apostrophe/hyphen grammar stays untouched");

'''
test = replace_once(test, insert_before, new_tests + insert_before, "insert screenshot regression tests")
marker_count = test.count('XRSS15\\n')
if marker_count < 2:
    raise SystemExit(f"test marker: expected >=2 XRSS15 references, found {marker_count}")
test = test.replace('XRSS15\\n', 'XRSS16\\n')
test_path.write_text(test)

print("RSS spacing root fix applied")
