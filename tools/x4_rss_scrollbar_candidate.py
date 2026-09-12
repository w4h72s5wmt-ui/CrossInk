from pathlib import Path

# Validation retry after increasing checkout depth.
path = Path("src/activities/home/RssNewsActivity.cpp")
text = path.read_text()
old = '''  size_t displayedLines = 0;
  for (size_t i = articleLineOffset; i < articleSummaryLines.size(); ++i) {
    if (screen.body().height < bodyHeight) break;
    fui::Rect lineRect = screen.takeTop(bodyHeight);
    lineRect.x = static_cast<int16_t>(readerMargin);
    lineRect.width = static_cast<int16_t>(readerWidth);
    RssArticleRichText::drawLine(renderer, readerFontId, lineRect.x, lineRect.y, articleSummaryLines[i], true);
    ++displayedLines;
  }
  articlePageLines = std::max<size_t>(1, displayedLines);
}
'''
new = '''  const fui::Rect articleViewport = screen.body();
  size_t displayedLines = 0;
  for (size_t i = articleLineOffset; i < articleSummaryLines.size(); ++i) {
    if (screen.body().height < bodyHeight) break;
    fui::Rect lineRect = screen.takeTop(bodyHeight);
    lineRect.x = static_cast<int16_t>(readerMargin);
    lineRect.width = static_cast<int16_t>(readerWidth);
    RssArticleRichText::drawLine(renderer, readerFontId, lineRect.x, lineRect.y, articleSummaryLines[i], true);
    ++displayedLines;
  }
  articlePageLines = std::max<size_t>(1, displayedLines);

  // Keep the progress indicator entirely inside the reader's right margin so
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
}
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one article render block, found {count}")
path.write_text(text.replace(old, new, 1))
print("Applied app-local RSS article scrollbar")
