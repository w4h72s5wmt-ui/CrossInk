from pathlib import Path

path = Path("src/activities/home/RssNewsActivity.cpp")
text = path.read_text()
old = '''  // Keep the progress indicator entirely inside the reader's right margin so
  // it never steals text width. A one-pixel rail plus a thicker thumb remains
  // legible on e-ink without adding any persistent state or allocation.
  const size_t totalLines = articleSummaryLines.size();
  if (displayedLines > 0 && totalLines > displayedLines && articleViewport.height > 0) {
    const int trackHeight = articleViewport.height;
    const int trackX = renderer.getScreenWidth() - std::max(3, readerMargin / 2);
    const int minThumbHeight = std::min(14, trackHeight);
    int thumbHeight = static_cast<int>((static_cast<uint64_t>(trackHeight) * displayedLines) / totalLines);
    thumbHeight = std::clamp(thumbHeight, minThumbHeight, trackHeight);

    const size_t maxOffset = totalLines - displayedLines;
    const size_t clampedOffset = std::min(articleLineOffset, maxOffset);
    const int thumbTravel = trackHeight - thumbHeight;
    const int thumbY = articleViewport.y +
                       (maxOffset == 0 ? 0 : static_cast<int>((static_cast<uint64_t>(thumbTravel) * clampedOffset) /
                                                              maxOffset));

    screen.target().fill(
        fui::Rect{static_cast<int16_t>(trackX), articleViewport.y, 1, static_cast<int16_t>(trackHeight)},
        fui::Paint::solid(fui::Color::Black));
    screen.target().fill(
        fui::Rect{static_cast<int16_t>(trackX - 1), static_cast<int16_t>(thumbY), 3,
                  static_cast<int16_t>(thumbHeight)},
        fui::Paint::solid(fui::Color::Black));
  }
'''
new = '''  // Match the native RSS list scroll indicator exactly: same themed width,
  // bezel inset, dithered rail and black thumb. Keep it outside reader text.
  const size_t totalLines = articleSummaryLines.size();
  if (displayedLines > 0 && totalLines > displayedLines && articleViewport.height > 0) {
    const int trackHeight = articleViewport.height;
    const int trackWidth = std::max(1, static_cast<int>(theme.listScrollWidth));
    const int trackInset = std::max(0, static_cast<int>(theme.listScrollInset));
    const int trackX = articleViewport.x + articleViewport.width - trackWidth - trackInset;
    const int minThumbHeight = std::min(12, trackHeight);
    int thumbHeight = static_cast<int>((static_cast<uint64_t>(trackHeight) * displayedLines) / totalLines);
    thumbHeight = std::clamp(thumbHeight, minThumbHeight, trackHeight);

    const size_t maxOffset = totalLines - displayedLines;
    const size_t clampedOffset = std::min(articleLineOffset, maxOffset);
    const int thumbTravel = trackHeight - thumbHeight;
    const int thumbY = articleViewport.y +
                       (maxOffset == 0 ? 0 : static_cast<int>((static_cast<uint64_t>(thumbTravel) * clampedOffset) /
                                                              maxOffset));

    screen.target().fill(
        fui::Rect{static_cast<int16_t>(trackX), articleViewport.y, static_cast<int16_t>(trackWidth),
                  static_cast<int16_t>(trackHeight)},
        fui::Paint::dither(fui::Color::LightGray));
    screen.target().fill(
        fui::Rect{static_cast<int16_t>(trackX), static_cast<int16_t>(thumbY), static_cast<int16_t>(trackWidth),
                  static_cast<int16_t>(thumbHeight)},
        fui::Paint::solid(fui::Color::Black));
  }
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one RSS article scrollbar block, found {count}")
path.write_text(text.replace(old, new, 1))
print("Applied native-width RSS article scrollbar")
