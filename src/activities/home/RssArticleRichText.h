#pragma once

#include <FreeInkUICore.h>

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <string>
#include <vector>

// RSS-only lightweight rich text. The article cache stores two private-use UTF-8
// sentinels around the visible label of an HTML <a>. No href is persisted. The
// reader strips those sentinels from measurement/display and draws one 1px line
// below the visible label, so linked words keep their semantic cue even though
// the X4 Pro has no browser.
namespace RssArticleRichText {
inline constexpr char LINK_START[] = "\xEE\x80\x80";  // U+E000
inline constexpr char LINK_END[] = "\xEE\x80\x81";    // U+E001
inline constexpr size_t LINK_MARKER_BYTES = 3;

struct Span {
  size_t begin = 0;
  size_t end = 0;
};

inline bool markerAt(const std::string& text, const size_t pos, const char* marker) {
  return pos + LINK_MARKER_BYTES <= text.size() &&
         std::memcmp(text.data() + pos, marker, LINK_MARKER_BYTES) == 0;
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
  std::string plain;
  std::vector<Span> spans;
  decode(marked, plain, spans);
  return plain;
}

inline size_t nextUtf8(const std::string& text, const size_t pos) {
  if (pos >= text.size()) return text.size();
  const unsigned char lead = static_cast<unsigned char>(text[pos]);
  size_t bytes = 1;
  if ((lead & 0xE0U) == 0xC0U) bytes = 2;
  else if ((lead & 0xF0U) == 0xE0U) bytes = 3;
  else if ((lead & 0xF8U) == 0xF0U) bytes = 4;
  return std::min(text.size(), pos + bytes);
}

inline std::string markedLine(const std::string& plain, const std::vector<Span>& spans,
                              const size_t begin, const size_t end) {
  std::string line;
  line.reserve(end - begin + 12);
  size_t cursor = begin;
  for (const Span& span : spans) {
    if (span.end <= begin) continue;
    if (span.begin >= end) break;
    const size_t overlapBegin = std::max(begin, span.begin);
    const size_t overlapEnd = std::min(end, span.end);
    if (overlapBegin > cursor) line.append(plain, cursor, overlapBegin - cursor);
    if (overlapEnd > overlapBegin) {
      line.append(LINK_START, LINK_MARKER_BYTES);
      line.append(plain, overlapBegin, overlapEnd - overlapBegin);
      line.append(LINK_END, LINK_MARKER_BYTES);
    }
    cursor = std::max(cursor, overlapEnd);
  }
  if (cursor < end) line.append(plain, cursor, end - cursor);
  return line;
}

inline std::vector<std::string> wrap(const freeink::ui::DrawTarget& target,
                                     const freeink::ui::FontId font,
                                     const std::string& marked,
                                     const int maxWidth,
                                     const size_t maxLines) {
  std::string plain;
  std::vector<Span> spans;
  decode(marked, plain, spans);

  std::vector<std::string> lines;
  if (plain.empty() || maxWidth <= 0 || maxLines == 0) return lines;
  lines.reserve(std::min<size_t>(maxLines, 128));

  freeink::ui::TextStyle style;
  style.font = font;
  style.maxLines = 1;
  const auto fits = [&](const size_t begin, const size_t end) {
    if (end <= begin) return true;
    const std::string candidate = plain.substr(begin, end - begin);
    return target.measureText(font, candidate.c_str(), style).width <= maxWidth;
  };

  size_t pos = 0;
  while (pos < plain.size() && lines.size() < maxLines) {
    while (pos < plain.size() && plain[pos] == ' ') ++pos;
    if (pos >= plain.size()) break;
    if (plain[pos] == '\n') {
      lines.emplace_back();
      ++pos;
      continue;
    }

    const size_t lineStart = pos;
    size_t bestEnd = lineStart;
    size_t scan = lineStart;
    while (scan < plain.size() && plain[scan] != '\n') {
      size_t wordEnd = scan;
      while (wordEnd < plain.size() && plain[wordEnd] != ' ' && plain[wordEnd] != '\n') ++wordEnd;
      if (wordEnd == scan) break;
      if (!fits(lineStart, wordEnd)) break;
      bestEnd = wordEnd;
      scan = wordEnd;
      while (scan < plain.size() && plain[scan] == ' ') ++scan;
    }

    if (bestEnd == lineStart) {
      size_t cursor = lineStart;
      size_t lastFit = lineStart;
      while (cursor < plain.size() && plain[cursor] != ' ' && plain[cursor] != '\n') {
        const size_t next = nextUtf8(plain, cursor);
        if (!fits(lineStart, next)) break;
        lastFit = next;
        cursor = next;
      }
      bestEnd = lastFit > lineStart ? lastFit : nextUtf8(plain, lineStart);
    }

    lines.push_back(markedLine(plain, spans, lineStart, bestEnd));
    pos = bestEnd;
    while (pos < plain.size() && plain[pos] == ' ') ++pos;
    if (pos < plain.size() && plain[pos] == '\n') ++pos;
  }
  return lines;
}

inline void drawLine(freeink::ui::DrawTarget& target, const freeink::ui::Rect rect,
                     const std::string& marked, freeink::ui::TextStyle style) {
  if (marked.find(LINK_START) == std::string::npos && marked.find(LINK_END) == std::string::npos) {
    target.text(rect, marked.c_str(), style);
    return;
  }

  style.align = freeink::ui::TextAlign::Left;
  style.maxLines = 1;
  int16_t x = rect.x;
  bool underlined = false;
  size_t pos = 0;
  while (pos < marked.size() && x < rect.right()) {
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
    const int16_t measured = target.measureText(style.font, segment.c_str(), style).width;
    const int16_t width = std::max<int16_t>(0, std::min<int16_t>(measured, rect.right() - x));
    if (width > 0) {
      target.text(freeink::ui::Rect{x, rect.y, width, rect.height}, segment.c_str(), style);
      if (underlined) {
        const int16_t y = static_cast<int16_t>(rect.bottom() - 1);
        target.line(freeink::ui::Point{x, y}, freeink::ui::Point{static_cast<int16_t>(x + width - 1), y}, 1,
                    freeink::ui::Paint::solid(style.color));
      }
      x = static_cast<int16_t>(x + width);
    }
    pos = end;
  }
}
}  // namespace RssArticleRichText
