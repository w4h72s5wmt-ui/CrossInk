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

if "bodyStyle.font = readerFontId" in rss:
    raise RuntimeError("RSS reader font is still being passed as a FreeInkUI font slot")
if "renderer.drawText(readerFontId, lineRect.x, lineRect.y" not in rss:
    raise RuntimeError("RSS direct reader-font drawing is missing")

rss_path.write_text(rss)
print("Applied RSS global reader font-size rendering fix.")
