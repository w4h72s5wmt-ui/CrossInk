#pragma once

#include <GfxRenderer.h>

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <string>
#include <vector>

// RSS-only lightweight link markup for X4 Pro articles.
// HTML href values are never persisted. Two private-use UTF-8 markers surround
// only the visible <a> label in the article cache. The reader removes those
// markers before wrapping and draws a 1px underline under the corresponding
// visible text. This preserves meaning without pretending links are actionable.
namespace RssArticleRichText {
inline constexpr char LINK_START[] = "\xEE\x80\x80";  // U+E000
inline constexpr char LINK_END[] = "\xEE\x80\x81";    // U+E001
inline constexpr size_t LINK_MARKER_BYTES = 3;

struct Span {
  size_t begin = 0;
  size_t end = 0;
};

inline bool markerAt(const char* data, const size_t length, const size_t pos, const char* marker) {
  return data && pos + LINK_MARKER_BYTES <= length &&
         std::memcmp(data + pos, marker, LINK_MARKER_BYTES) == 0;
}

inline bool markerAt(const std::string& text, const size_t pos, const char* marker) {
  return markerAt(text.data(), text.size(), pos, marker);
}

inline bool containsMarkup(const std::string& text) {
  return text.find(LINK_START) != std::string::npos || text.find(LINK_END) != std::string::npos;
}

inline void decode(const std::string& marked, std::string& plain, std::vector<Span>& spans) {
  plain.clear();
  spans.clear();
  plain.reserve(marked.size());
  bool inLink = false;
  size_t linkStart = 0;
  size_t pos = 0;
  while (pos < marked.size()) {
    if (markerAt(marked, pos, LINK_START)) {
      if (!inLink) {
        inLink = true;
        linkStart = plain.size();
      }
      pos += LINK_MARKER_BYTES;
      continue;
    }
    if (markerAt(marked, pos, LINK_END)) {
      if (inLink && plain.size() > linkStart) spans.push_back(Span{linkStart, plain.size()});
      inLink = false;
      pos += LINK_MARKER_BYTES;
      continue;
    }
    plain.push_back(marked[pos++]);
  }
  if (inLink && plain.size() > linkStart) spans.push_back(Span{linkStart, plain.size()});
}

inline std::string visibleText(const std::string& marked) {
  if (!containsMarkup(marked)) return marked;
  std::string plain;
  std::vector<Span> spans;
  decode(marked, plain, spans);
  return plain;
}

inline std::string markedRange(const std::string& plain, const std::vector<Span>& spans,
                               const size_t begin, const size_t end) {
  std::string out;
  out.reserve(end - begin + 12);
  size_t cursor = begin;
  for (const Span& span : spans) {
    if (span.end <= begin) continue;
    if (span.begin >= end) break;
    const size_t overlapBegin = std::max(begin, span.begin);
    const size_t overlapEnd = std::min(end, span.end);
    if (overlapBegin > cursor) out.append(plain, cursor, overlapBegin - cursor);
    if (overlapEnd > overlapBegin) {
      out.append(LINK_START, LINK_MARKER_BYTES);
      out.append(plain, overlapBegin, overlapEnd - overlapBegin);
      out.append(LINK_END, LINK_MARKER_BYTES);
    }
    cursor = std::max(cursor, overlapEnd);
  }
  if (cursor < end) out.append(plain, cursor, end - cursor);
  return out;
}

// Keep the existing renderer.wrappedText() result byte-for-byte, then reattach
// the link spans to the visual lines. Ordinary prose therefore keeps exactly
// the same wrapping and pagination as before.
inline void decorateWrappedLines(const std::string& marked, std::vector<std::string>& lines) {
  if (!containsMarkup(marked) || lines.empty()) return;
  std::string plain;
  std::vector<Span> spans;
  decode(marked, plain, spans);
  if (spans.empty()) return;

  size_t searchFrom = 0;
  for (std::string& line : lines) {
    if (line.empty()) continue;
    size_t begin = plain.find(line, searchFrom);
    if (begin == std::string::npos) begin = plain.find(line);
    if (begin == std::string::npos) continue;
    const size_t end = begin + line.size();
    line = markedRange(plain, spans, begin, end);
    searchFrom = end;
  }
}

// Render with the same GfxRenderer/font path as the normal RSS body. This is
// important for the user's selected SD reader font: width and drawing must use
// identical metrics or the underline would drift away from the linked words.
inline void drawLine(GfxRenderer& renderer, const int fontId, const int x, const int y,
                     const std::string& marked, const bool black = true) {
  if (!containsMarkup(marked)) {
    renderer.drawText(fontId, x, y, marked.c_str(), black);
    return;
  }

  int cursorX = x;
  bool underlined = false;
  size_t pos = 0;
  while (pos < marked.size()) {
    if (markerAt(marked, pos, LINK_START)) {
      underlined = true;
      pos += LINK_MARKER_BYTES;
      continue;
    }
    if (markerAt(marked, pos, LINK_END)) {
      underlined = false;
      pos += LINK_MARKER_BYTES;
      continue;
    }

    size_t end = pos;
    while (end < marked.size() && !markerAt(marked, end, LINK_START) && !markerAt(marked, end, LINK_END)) ++end;
    if (end == pos) {
      ++pos;
      continue;
    }

    const std::string segment = marked.substr(pos, end - pos);
    renderer.drawText(fontId, cursorX, y, segment.c_str(), black);
    // Link markup splits one visual line into independently drawn segments.
    // getTextWidth() is a visual bbox for flash fonts and can omit a trailing
    // space, making the following underlined segment look glued. Advance by the
    // same metric drawText() uses instead.
    const int width = renderer.getTextAdvanceX(fontId, segment.c_str(), EpdFontFamily::REGULAR);
    if (underlined && width > 0) {
      const int underlineY = y + std::max(1, renderer.getLineHeight(fontId) - 2);
      renderer.drawLine(cursorX, underlineY, cursorX + width - 1, underlineY, black);
    }
    cursorX += width;
    pos = end;
  }
}
}  // namespace RssArticleRichText
