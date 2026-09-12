from pathlib import Path

path = Path("tools/x4_rss_metadata_opt_candidate.py")
text = path.read_text()

targets = [
    ("cache body-state helpers", "size_t sanitizeFallbackMarkup(char* text, const size_t length) {\n"),
    ("cache identity API", '#include "RssArticleCachePolicy.inc"\n'),
    ("runtime RSS buffers", "void RssNewsActivity::loadSources() {\n"),
    ("lightweight history merge", "void RssNewsActivity::rebuildDisplayOrder() {\n"),
    ("cache/metadata tests", "std::string readFile(const char* path) {\n"),
]

for label, signature in targets:
    marker = f'"{label}")'
    marker_pos = text.find(marker)
    if marker_pos < 0:
        raise SystemExit(f"generator label missing: {label}")
    signature_pos = text.rfind(signature, 0, marker_pos)
    if signature_pos < 0:
        raise SystemExit(f"generator duplicate signature missing before {label}: {signature}")
    text = text[:signature_pos] + text[signature_pos + len(signature):]

old_version_anchor = '''  // V4 binds the binary article cache to the full feeds.txt configuration,
  // including sync/history limits, so capacity changes invalidate metadata cleanly.
  static constexpr uint16_t CACHE_VERSION = 4;
'''
actual_version_anchor = '''  // V4 binds the binary article cache to the current feeds.txt content so
  // reordering/replacing sources can never relabel old articles incorrectly.
  static constexpr uint16_t CACHE_VERSION = 4;
'''
count = text.count(old_version_anchor)
if count != 1:
    raise SystemExit(f"generator cache-version anchor expected one match, got {count}")
text = text.replace(old_version_anchor, actual_version_anchor, 1)

# These checks live inside a Python raw string that emits C++ source. The C++
# literal needs one backslash before n, not two literal backslashes.
for marker in ("XRSSF1", "XRSS11"):
    old = f'{marker}\\\\n'
    new = f'{marker}\\n'
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"generated test marker escape missing: {marker}")
    text = text.replace(old, new)

path.write_text(text)
print("Fixed candidate generator boundaries, cache-version anchor and marker assertions.")
