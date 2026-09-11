from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"{label}: expected unique section boundaries")
    first = text.index(start)
    last = text.index(end, first)
    return text[:first] + replacement + text[last:]


# Existing RSS integration step. Implementations live in the app's .inc files;
# replace old generated implementations, do not layer wrappers around them.
path = Path("src/activities/home/RssArticleCache.cpp")
text = path.read_text()
duplicate = (
    "bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n" * 2
)
text = replace_once(text, duplicate, duplicate[:len(duplicate) // 2], "RSS duplicate signature")
text = replace_once(
    text, '#include "network/HttpDownloader.h"\n',
    '#include "network/HttpDownloader.h"\n#include "RssFigaroAuth.h"\n#include "RssFetchDiagnostics.h"\n', "RSS Figaro auth include",
)
text = replace_once(text, 'constexpr char BODY_MAGIC[] = "XRSS4\\n";',
                    'constexpr char BODY_MAGIC[] = "XRSS10\\n";', "RSS rich-link article cache version")
text = replace_once(text, 'constexpr size_t MAX_TEXT_BYTES = 48U * 1024U;',
                    'constexpr size_t MAX_TEXT_BYTES = 64U * 1024U;', "RSS X4 Pro article text capacity")

text = replace_section(text, "bool isNoiseContainer(", "size_t decodeEntity(", "", "remove substring HTML filter")
text = replace_section(
    text, "bool extractReadableText(", "bool normalizedLineEquals(",
    '#include "RssArticleHtml.inc"\n\n', "RSS bounded HTML extraction",
)
text = replace_once(
    text, '  const bool valid = file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES) &&\n',
    '  const bool valid = file.size() > BODY_MAGIC_BYTES && file.size() <= BODY_MAGIC_BYTES + MAX_TEXT_BYTES &&\n'
    '                     file.read(marker, BODY_MAGIC_BYTES) == static_cast<int>(BODY_MAGIC_BYTES) &&\n',
    "RSS reject empty/oversized cached bodies",
)
text = replace_section(text, "bool persistFallback(const RssItem& item,", "}  // namespace\n",
                       "", "remove summary file persistence")

old_body_path = '''std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  char name[64];
'''
new_body_path = '''std::string bodyPath(const RssItem& item) {
  uint64_t hash = fnv1a64(item.link);
  if (!item.link[0]) {
    hash = fnv1a64(item.title, hash);
    hash = fnv1a64(item.published, hash);
  }
  const uint64_t authKey = RssFigaroAuth::cacheKeyFor(item.link);
  for (size_t i = 0; authKey != 0 && i < sizeof(authKey); ++i) {
    hash ^= static_cast<uint8_t>(authKey >> (i * 8U));
    hash *= 1099511628211ULL;
  }
  char name[64];
'''
text = replace_once(text, old_body_path, new_body_path, "RSS authenticated cache namespace")
text = replace_section(
    text, "CacheResult ensureCached(", "}  // namespace RssArticleCache",
    '#include "RssArticleCachePolicy.inc"\n\n', "RSS body-only cache and explicit fallback policy",
)
if duplicate in text or "bool persistFallback(" in text:
    raise RuntimeError("RSS obsolete generated implementation remains")
for name in ("RssArticleHtml.inc", "RssArticleCachePolicy.inc", "RssHtmlEntities.inc", "RssArticleRichText.h"):
    if not (path.parent / name).is_file():
        raise RuntimeError(f"Missing RSS-local implementation: {name}")
for name in ("RssArticleHtml.inc", "RssArticleCachePolicy.inc"):
    if f'#include "{name}"' not in text:
        raise RuntimeError(f"Missing generated RSS include: {name}")
path.write_text(text)

# The HTML parser is app-owned source. Wire UTF-8 decoding and RSS-local inert
# link markup directly into extraction. href values are never copied. A visible
# URL used as the anchor label is dropped; normal linked words are marker-wrapped
# so the reader can underline them without retaining the destination.
html_path = path.parent / "RssArticleHtml.inc"
html = html_path.read_text()
html_space = """bool htmlSpace(const char c) {
  return c == ' ' || c == '\\t' || c == '\\n' || c == '\\r' || c == '\\f';
}
"""
html = replace_once(html, html_space,
                    html_space + '\n#include "RssHtmlEntities.inc"\n#include "RssArticleRichText.h"\n',
                    "RSS UTF-8/link markup includes")
html = replace_once(html, "decodeEntity(html, end, pos, text, textLength)",
                    "decodeEntityUtf8(html, end, pos, text, textLength)",
                    "RSS UTF-8 HTML entity decoder call")
html = replace_once(
    html,
    "  size_t anchorTextStart = 0;\n  bool inAnchor = false;\n",
    "  size_t anchorTextStart = 0;\n  size_t anchorMarkerStart = 0;\n  bool inAnchor = false;\n",
    "RSS link marker state",
)
old_anchor = '''      if (tagEquals(tag.name, "a")) {
        if (!tag.closing && !tag.selfClosing && !inAnchor) {
          inAnchor = true;
          anchorTextStart = textLength;
        } else if (tag.closing && inAnchor) {
          if (looksLikeVisibleUrl(text + anchorTextStart, textLength - anchorTextStart)) {
            textLength = anchorTextStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
          }
          inAnchor = false;
        }
      }
'''
new_anchor = '''      if (tagEquals(tag.name, "a")) {
        if (!tag.closing && !tag.selfClosing && !inAnchor) {
          inAnchor = true;
          anchorMarkerStart = textLength;
          for (size_t i = 0; i < RssArticleRichText::LINK_MARKER_BYTES; ++i)
            appendChar(text, textLength, RssArticleRichText::LINK_START[i]);
          anchorTextStart = textLength;
        } else if (tag.closing && inAnchor) {
          if (looksLikeVisibleUrl(text + anchorTextStart, textLength - anchorTextStart)) {
            textLength = anchorMarkerStart;
            while (textLength > 0 && text[textLength - 1] == ' ' &&
                   (next < end && htmlSpace(html[next]))) {
              --textLength;
            }
          } else if (textLength > anchorTextStart) {
            for (size_t i = 0; i < RssArticleRichText::LINK_MARKER_BYTES; ++i)
              appendChar(text, textLength, RssArticleRichText::LINK_END[i]);
          } else {
            textLength = anchorMarkerStart;
          }
          inAnchor = false;
        }
      }
'''
html = replace_once(html, old_anchor, new_anchor, "RSS inert link label markup")
html_path.write_text(html)

header_path = path.with_suffix(".h")
header = header_path.read_text()
header = replace_once(
    header, "// If extraction/networking fails, the feed-provided body is persisted instead.\n",
    "// A failure leaves no body file; the feed summary remains in RSS metadata\n"
    "// and a subsequent manual refresh retries this article.\n", "RSS cache contract",
)
header = replace_once(
    header,
    "// Loads the cached offline body. Returns false when no dedicated body file is\n"
    "// available; callers can still fall back to item.summary for legacy entries.\n"
    "bool load(const RssItem& item, std::string& outText);\n",
    "// Loads a current body (READY), or prepares the feed summary (FALLBACK_READY)\n"
    "// without persisting it. AUTH never substitutes a public summary.\n"
    "CacheResult load(const RssItem& item, const char* sourceName, const char* dropRules,\n"
    "                 const char* dropStartRules, const char* stopRules, std::string& outText);\n",
    "RSS explicit offline result API",
)
header_path.write_text(header)

news_path = path.parent / "RssNewsActivity.cpp"
news = news_path.read_text()
news = replace_once(
    news, '#include "RssArticleCache.h"\n',
    '#include "RssArticleCache.h"\n#include "RssArticleRichText.h"\n#include "RssFigaroAuth.h"\n#include "RssFetchDiagnostics.h"\n',
    "RSS Figaro refresh and rich-link includes",
)
news = replace_once(
    news, 'void RssNewsActivity::refreshFeeds() {\n',
    '''void RssNewsActivity::refreshFeeds() {
  RssFetchDiagnostics::begin();
  RssFigaroAuth::resetSession();
  struct FigaroSessionScope {
    ~FigaroSessionScope() {
      RssFigaroAuth::resetSession();
      RssFetchDiagnostics::end();
    }
  } figaroSessionScope;
''', "RSS Figaro refresh session scope",
)
news = replace_once(
    news, '  if (!RssArticleCache::load(article.item, offlineBody)) offlineBody = article.item.summary;\n',
    r'''  const Source& source = sources[article.sourceIndex];
  const auto bodyResult = RssArticleCache::load(article.item, source.name.c_str(), source.dropRules.c_str(),
                                              source.dropStartRules.c_str(), source.stopRules.c_str(), offlineBody);
  if (bodyResult == RssArticleCache::CacheResult::FALLBACK_READY) {
    offlineBody.insert(0, "R\u00e9sum\u00e9 du flux uniquement.\nActualise RSS pour r\u00e9essayer l'article.\n\n");
  } else if (bodyResult != RssArticleCache::CacheResult::READY) {
    offlineBody = "Article indisponible hors ligne.\nActualise RSS pour r\u00e9essayer.";
  }
''', "RSS distinguish article/summary/failure on opening",
)
news = replace_once(
    news,
    "  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {\n"
    "    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);\n"
    "  }\n\n"
    "  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);\n"
    "  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);\n",
    "  const std::string visibleBody = RssArticleRichText::visibleText(offlineBody);\n"
    "  if (renderer.isSdCardFont(readerFontId) && !visibleBody.empty()) {\n"
    "    renderer.ensureSdCardFontReady(readerFontId, visibleBody.c_str(), /*styleMask=*/0x01);\n"
    "  }\n\n"
    "  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);\n"
    "  articleSummaryLines = renderer.wrappedText(readerFontId, visibleBody.c_str(), maxWidth, 2000);\n"
    "  RssArticleRichText::decorateWrappedLines(offlineBody, articleSummaryLines);\n",
    "RSS preserve wrapping while decorating linked words",
)
news = replace_once(
    news,
    "    screen.target().text(lineRect, articleSummaryLines[i].c_str(), bodyStyle);\n",
    "    RssArticleRichText::drawLine(screen.target(), lineRect, articleSummaryLines[i], bodyStyle);\n",
    "RSS underline inert link labels",
)
news = replace_once(
    news, '        if (cacheResult == RssArticleCache::CacheResult::FAILED) refreshHadError = true;\n',
    '        if (cacheResult == RssArticleCache::CacheResult::FAILED ||\n'
    '            cacheResult == RssArticleCache::CacheResult::FALLBACK_READY) refreshHadError = true;\n',
    "RSS summary-only refresh is not a complete fetch",
)
news_path.write_text(news)
print("Applied RSS-local UTF-8 extraction, strict Figaro AUTH, XRSS10 inert-link markup and bounded SD diagnostics.")