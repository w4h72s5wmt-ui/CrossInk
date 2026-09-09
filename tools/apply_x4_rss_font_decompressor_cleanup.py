from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("src/activities/home/RssNewsActivity.cpp")
text = path.read_text()

text = replace_once(
    text,
    '#include <GfxRenderer.h>\n',
    '#include <FontCacheManager.h>\n#include <GfxRenderer.h>\n',
    "RSS FontCacheManager include",
)

text = replace_once(
    text,
    '''  writeRssMemoryAudit("exit.00-begin", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n  // Match the EPUB reader's proven low-memory cleanup path.''',
    '''  writeRssMemoryAudit("exit.00-begin", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n\n  // RSS's first article render can lazily allocate FontDecompressor's global\n  // compressed-font hot-group buffer (~12 KB on the X4 Pro). It is rebuildable\n  // and otherwise survives the Activity, splitting the largest PSRAM arena.\n  // This same cleanup API is already used by the EPUB reader and network flows.\n  if (auto* fcm = renderer.getFontCacheManager()) {\n    fcm->releaseSdFontCaches();\n  }\n  writeRssMemoryAudit("exit.00b-after-global-font-cache-release");\n\n  // Match the EPUB reader's proven low-memory cleanup path.''',
    "RSS global font cache cleanup",
)

if "fcm->releaseSdFontCaches();" not in text:
    raise RuntimeError("RSS FontCacheManager cleanup missing")
if 'writeRssMemoryAudit("exit.00b-after-global-font-cache-release")' not in text:
    raise RuntimeError("RSS cleanup audit checkpoint missing")

path.write_text(text)
print("Applied RSS FontDecompressor/global font-cache cleanup after deep audit instrumentation.")
