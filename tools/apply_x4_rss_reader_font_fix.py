from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()

# FreeInkUI TextStyle::font is a small UI slot (small/body/title), not a raw
# GfxRenderer font id. Passing SETTINGS.getReaderFontId() there makes any id
# outside those slots fall back to the UI body font, so reader font-size
# changes appear to do nothing. Keep UI chrome in FreeInkUI, but render the
# pre-wrapped article body directly through GfxRenderer just like Notes does.
rss = replace_once(
    rss,
    '''  const int readerFontId = SETTINGS.getReaderFontId();
  bodyStyle.font = readerFontId;
''',
    '''  const int readerFontId = SETTINGS.getReaderFontId();
''',
    "RSS remove raw reader font id from FreeInkUI slot",
)

rss = replace_once(
    rss,
    '''    screen.target().text(lineRect, articleSummaryLines[i].c_str(), bodyStyle);
''',
    '''    renderer.drawText(readerFontId, lineRect.x, lineRect.y, articleSummaryLines[i].c_str(), true);
''',
    "RSS draw article body with real reader font",
)

# The sort selector used to be vertically centered in the whole touch target,
# while TouchHeaderBackButton positions the title in its 52px visual lane with
# TITLE_VERTICAL_OFFSET. Align the selector's actual font baseline with the
# title baseline. The touch rectangle itself is deliberately left unchanged.
rss = replace_once(
    rss,
    '''      fui::TextStyle sortStyle = screen.theme().smallText;
      sortStyle.align = fui::TextAlign::Center;
      sortStyle.maxLines = 1;
      const Rect touch = sortTouchRect(renderer, mappedInput);
      screen.target().text(fui::Rect{static_cast<int16_t>(touch.x), static_cast<int16_t>(touch.y),
                                     static_cast<int16_t>(touch.width), static_cast<int16_t>(touch.height)},
                           sortMode == SortMode::DATE_DESC ? "D v" : "SRC", sortStyle);
''',
    '''      fui::TextStyle sortStyle = screen.theme().smallText;
      sortStyle.align = fui::TextAlign::Center;
      sortStyle.maxLines = 1;
      const Rect touch = sortTouchRect(renderer, mappedInput);
      const auto headerLayout = TouchHeaderBackButton::layout(headerRect);
      const int iconBottom = headerLayout.iconRect.y +
                             (headerLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2;
      const int availableOffset = std::max(0, headerRect.y + headerRect.height - iconBottom);
      const int titleOffset = std::clamp(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET, 0, availableOffset);
      const auto scale = uiScaleSpec();
      const int titleBaselineY =
          headerLayout.iconRect.y + titleOffset +
          std::max(0, (headerLayout.iconRect.height - renderer.getLineHeight(scale.titleFontId)) / 2) +
          renderer.getFontAscenderSize(scale.titleFontId);
      const int sortLineHeight = renderer.getLineHeight(scale.smallFontId);
      const int sortTop = titleBaselineY - renderer.getFontAscenderSize(scale.smallFontId);
      screen.target().text(fui::Rect{static_cast<int16_t>(touch.x), static_cast<int16_t>(sortTop),
                                     static_cast<int16_t>(touch.width), static_cast<int16_t>(sortLineHeight)},
                           sortMode == SortMode::DATE_DESC ? "D v" : "SRC", sortStyle);
''',
    "RSS sort selector title-baseline alignment",
)

if "bodyStyle.font = readerFontId" in rss:
    raise RuntimeError("RSS reader font is still being passed as a FreeInkUI font slot")
if "renderer.drawText(readerFontId, lineRect.x, lineRect.y" not in rss:
    raise RuntimeError("RSS direct reader-font drawing is missing")
if "const int sortTop = titleBaselineY - renderer.getFontAscenderSize(scale.smallFontId);" not in rss:
    raise RuntimeError("RSS sort selector baseline alignment is missing")

rss_path.write_text(rss)
print("Applied RSS reader font-size and header sort baseline fixes.")
