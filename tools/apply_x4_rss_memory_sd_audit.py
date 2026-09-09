from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("src/activities/home/RssNewsActivity.cpp")
text = path.read_text()

# This overlay intentionally runs AFTER apply_x4_rss_exit_lifecycle_fix.py.
# It records only RSS memory checkpoints to SD; it emits no serial audit logs.
text = replace_once(
    text,
    '''namespace {\nconstexpr fui::ActionId ACTION_ROW = 1;\n''',
    '''namespace {\nconstexpr fui::ActionId ACTION_ROW = 1;\nconstexpr const char* RSS_MEM_AUDIT_PATH = "/rss_mem_audit.txt";\n\nvoid writeRssMemoryAudit(const char* phase) {\n#ifndef SIMULATOR\n  // Sample memory BEFORE opening/writing the SD file so the measurement does\n  // not include the audit I/O itself. No heap allocation is needed here.\n  const size_t heapFree = ESP.getFreeHeap();\n  const size_t heapLargest = ESP.getMaxAllocHeap();\n  const size_t psramFree = ESP.getFreePsram();\n  const size_t psramLargest = ESP.getMaxAllocPsram();\n\n  static bool sessionHeaderWritten = false;\n  FsFile file = Storage.open(RSS_MEM_AUDIT_PATH, O_WRONLY | O_CREAT | O_APPEND);\n  if (!file) return;\n\n  if (!sessionHeaderWritten) {\n    static constexpr char header[] = "\\n--- RSS MEM AUDIT SESSION ---\\n";\n    file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);\n    sessionHeaderWritten = true;\n  }\n\n  char line[176];\n  const int length = std::snprintf(\n      line, sizeof(line),\n      "[%lu] %s: heap=%zu largest=%zu psram=%zu psramLargest=%zu\\n",\n      static_cast<unsigned long>(millis()), phase ? phase : "?",\n      heapFree, heapLargest, psramFree, psramLargest);\n  if (length > 0) {\n    const size_t bytes = std::min(static_cast<size_t>(length), sizeof(line) - 1);\n    file.write(reinterpret_cast<const uint8_t*>(line), bytes);\n  }\n  file.close();\n#else\n  (void)phase;\n#endif\n}\n''',
    "RSS SD memory audit helper",
)

text = replace_once(
    text,
    '''void RssNewsActivity::onEnter() {\n  Activity::onEnter();\n  sdFontSystem.releaseLoadedFont(renderer);\n''',
    '''void RssNewsActivity::onEnter() {\n  writeRssMemoryAudit("before-enter");\n  Activity::onEnter();\n  sdFontSystem.releaseLoadedFont(renderer);\n''',
    "RSS before-enter audit",
)

text = replace_once(
    text,
    '''  sdFontSystem.ensureLoaded(renderer);\n''',
    '''  sdFontSystem.ensureLoaded(renderer);\n  writeRssMemoryAudit("after-font-load");\n''',
    "RSS post-font-load audit",
)

text = replace_once(
    text,
    '''void RssNewsActivity::onExit() {\n  // Match the EPUB reader's proven low-memory cleanup path. The glyph/advance\n  // caches that affect contiguous PSRAM belong to the renderer, not merely to\n  // SdCardFontSystem's loader/registry state.\n  const int readerFontId = SETTINGS.getReaderFontId();\n  if (renderer.isSdCardFont(readerFontId)) {\n    renderer.releaseSdCardFontForLowMemory(readerFontId);\n  }\n  sdFontSystem.releaseRegistry();\n\n  Activity::onExit();\n''',
    '''void RssNewsActivity::onExit() {\n  writeRssMemoryAudit("before-renderer-font-release");\n\n  // Match the EPUB reader's proven low-memory cleanup path. The glyph/advance\n  // caches that affect contiguous PSRAM belong to the renderer, not merely to\n  // SdCardFontSystem's loader/registry state.\n  const int readerFontId = SETTINGS.getReaderFontId();\n  if (renderer.isSdCardFont(readerFontId)) {\n    renderer.releaseSdCardFontForLowMemory(readerFontId);\n  }\n  sdFontSystem.releaseRegistry();\n\n  writeRssMemoryAudit("after-renderer-font-release");\n  Activity::onExit();\n''',
    "RSS renderer cleanup A/B audit",
)

path.write_text(text)

checks = {
    "SD-only audit path": 'RSS_MEM_AUDIT_PATH = "/rss_mem_audit.txt"',
    "append mode": "O_WRONLY | O_CREAT | O_APPEND",
    "before enter": 'writeRssMemoryAudit("before-enter");',
    "font loaded": 'writeRssMemoryAudit("after-font-load");',
    "before renderer release": 'writeRssMemoryAudit("before-renderer-font-release");',
    "after renderer release": 'writeRssMemoryAudit("after-renderer-font-release");',
}
for label, needle in checks.items():
    if needle not in text:
        raise RuntimeError(f"{label}: verification failed")

# Deliberately forbid serial audit logging in this diagnostic overlay.
if 'LOG_ERR("RSSMEM"' in text or 'LOG_INF("RSSMEM"' in text or 'LOG_DBG("RSSMEM"' in text:
    raise RuntimeError("RSS memory audit must be SD-only")

print("Applied RSS memory audit: renderer font-cache A/B to /rss_mem_audit.txt only.")
