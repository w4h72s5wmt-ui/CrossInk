from pathlib import Path

path = Path("tools/x4_rss_metadata_opt_candidate.py")
text = path.read_text()

targets = [
    ("cache body-state helpers", "size_t sanitizeFallbackMarkup(char* text, const size_t length) {\n"),
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

path.write_text(text)
print("Fixed candidate generator section boundaries.")
