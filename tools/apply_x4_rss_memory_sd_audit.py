from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# RSS activity: fine-grained SD-only memory trace.
# This overlay intentionally runs AFTER apply_x4_rss_exit_lifecycle_fix.py.
# -----------------------------------------------------------------------------
rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()

rss = replace_once(
    rss,
    '#include <Arduino.h>\n',
    '#include <Arduino.h>\n#include <esp_heap_caps.h>\n',
    "RSS heap caps include",
)

rss = replace_once(
    rss,
    '''namespace {\nconstexpr fui::ActionId ACTION_ROW = 1;\n''',
    '''namespace {\nconstexpr fui::ActionId ACTION_ROW = 1;\nconstexpr const char* RSS_MEM_AUDIT_PATH = "/rss_mem_audit.txt";\n\nstruct RssMemSnapshot {\n  size_t heapFree = 0;\n  size_t heapLargest = 0;\n  size_t psramFree = 0;\n  size_t psramLargest = 0;\n  size_t psramAllocated = 0;\n  size_t psramMinimumFree = 0;\n  size_t psramAllocatedBlocks = 0;\n  size_t psramFreeBlocks = 0;\n  size_t psramTotalBlocks = 0;\n};\n\nRssMemSnapshot captureRssMemory() {\n  RssMemSnapshot snapshot;\n#ifndef SIMULATOR\n  snapshot.heapFree = ESP.getFreeHeap();\n  snapshot.heapLargest = ESP.getMaxAllocHeap();\n  snapshot.psramFree = ESP.getFreePsram();\n  snapshot.psramLargest = ESP.getMaxAllocPsram();\n\n  multi_heap_info_t psramInfo{};\n  heap_caps_get_info(&psramInfo, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);\n  snapshot.psramAllocated = psramInfo.total_allocated_bytes;\n  snapshot.psramMinimumFree = psramInfo.minimum_free_bytes;\n  snapshot.psramAllocatedBlocks = psramInfo.allocated_blocks;\n  snapshot.psramFreeBlocks = psramInfo.free_blocks;\n  snapshot.psramTotalBlocks = psramInfo.total_blocks;\n#endif\n  return snapshot;\n}\n\nvoid appendRssMemorySnapshot(const char* phase, const RssMemSnapshot& snapshot,\n                             const size_t meta1 = 0, const size_t meta2 = 0,\n                             const size_t meta3 = 0, const size_t meta4 = 0) {\n#ifndef SIMULATOR\n  static bool sessionHeaderWritten = false;\n  FsFile file = Storage.open(RSS_MEM_AUDIT_PATH, O_WRONLY | O_CREAT | O_APPEND);\n  if (!file) return;\n\n  if (!sessionHeaderWritten) {\n    static constexpr char header[] = "\\n--- RSS MEM DEEP AUDIT SESSION ---\\n";\n    file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);\n    sessionHeaderWritten = true;\n  }\n\n  char line[384];\n  const int length = std::snprintf(\n      line, sizeof(line),\n      "[%lu] %s: heap=%zu largest=%zu psram=%zu psramLargest=%zu pAlloc=%zu pMin=%zu "\n      "pAllocBlocks=%zu pFreeBlocks=%zu pTotalBlocks=%zu m1=%zu m2=%zu m3=%zu m4=%zu\\n",\n      static_cast<unsigned long>(millis()), phase ? phase : "?",\n      snapshot.heapFree, snapshot.heapLargest, snapshot.psramFree, snapshot.psramLargest,\n      snapshot.psramAllocated, snapshot.psramMinimumFree, snapshot.psramAllocatedBlocks,\n      snapshot.psramFreeBlocks, snapshot.psramTotalBlocks, meta1, meta2, meta3, meta4);\n  if (length > 0) {\n    const size_t bytes = std::min(static_cast<size_t>(length), sizeof(line) - 1);\n    file.write(reinterpret_cast<const uint8_t*>(line), bytes);\n  }\n  file.close();\n#else\n  (void)phase;\n  (void)snapshot;\n  (void)meta1;\n  (void)meta2;\n  (void)meta3;\n  (void)meta4;\n#endif\n}\n\nvoid writeRssMemoryAudit(const char* phase, const size_t meta1 = 0, const size_t meta2 = 0,\n                         const size_t meta3 = 0, const size_t meta4 = 0) {\n#ifndef SIMULATOR\n  // Always sample BEFORE SD I/O. The very first call additionally measures the\n  // audit file's own lazy SD/FAT cache impact so we can subtract diagnostic noise.\n  static bool firstWriteChecked = false;\n  const RssMemSnapshot beforeIo = captureRssMemory();\n  appendRssMemorySnapshot(phase, beforeIo, meta1, meta2, meta3, meta4);\n  if (!firstWriteChecked) {\n    firstWriteChecked = true;\n    const RssMemSnapshot afterIo = captureRssMemory();\n    appendRssMemorySnapshot("audit-io-after-first-write", afterIo);\n  }\n#else\n  (void)phase;\n  (void)meta1;\n  (void)meta2;\n  (void)meta3;\n  (void)meta4;\n#endif\n}\n''',
    "RSS deep SD audit helpers",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::onEnter() {\n  Activity::onEnter();\n  sdFontSystem.releaseLoadedFont(renderer);\n''',
    '''void RssNewsActivity::onEnter() {\n  writeRssMemoryAudit("enter.00-before-activity");\n  Activity::onEnter();\n  writeRssMemoryAudit("enter.01-after-activity");\n  sdFontSystem.releaseLoadedFont(renderer);\n  writeRssMemoryAudit("enter.02-after-loader-release");\n''',
    "RSS enter trace",
)

rss = replace_once(
    rss,
    '''  if (!ensureBuffers()) {\n    statusMessage = tr(STR_MEMORY_ERROR);\n  } else {\n    loadCache();\n    rebuildDisplayOrder();\n  }\n  requestUpdate();\n}\n''',
    '''  writeRssMemoryAudit("enter.03-before-buffers");\n  if (!ensureBuffers()) {\n    statusMessage = tr(STR_MEMORY_ERROR);\n  } else {\n    writeRssMemoryAudit("enter.04-after-buffers");\n    loadCache();\n    writeRssMemoryAudit("enter.05-after-cache-load", articleCount);\n    rebuildDisplayOrder();\n    writeRssMemoryAudit("enter.06-after-display-order", articleCount);\n  }\n  writeRssMemoryAudit("enter.07-before-request-update");\n  requestUpdate();\n}\n''',
    "RSS enter allocation stages",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::openArticle(const size_t articleIndex) {\n  if (!articles || articleIndex >= articleCount) return;\n  openArticleIndex = articleIndex;\n  const CachedArticle& article = articles[articleIndex];\n\n  sdFontSystem.ensureLoaded(renderer);\n  const int readerFontId = SETTINGS.getReaderFontId();\n  const int margin = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));\n  const int maxWidth = std::max(80, renderer.getScreenWidth() - margin * 2);\n  const auto scale = uiScaleSpec();\n\n  std::string offlineBody;\n  if (!RssArticleCache::load(article.item, offlineBody)) offlineBody = article.item.summary;\n  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {\n    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);\n  }\n\n  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);\n  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);\n  articleLineOffset = 0;\n  articlePageLines = 8;\n  state = State::ARTICLE;\n  requestUpdate();\n}\n''',
    '''void RssNewsActivity::openArticle(const size_t articleIndex) {\n  if (!articles || articleIndex >= articleCount) return;\n  writeRssMemoryAudit("article.00-open-begin", articleIndex, articleCount);\n  openArticleIndex = articleIndex;\n  const CachedArticle& article = articles[articleIndex];\n\n  writeRssMemoryAudit("article.01-before-font-loader");\n  sdFontSystem.ensureLoaded(renderer);\n  writeRssMemoryAudit("article.02-after-font-loader");\n  const int readerFontId = SETTINGS.getReaderFontId();\n  const int margin = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));\n  const int maxWidth = std::max(80, renderer.getScreenWidth() - margin * 2);\n  const auto scale = uiScaleSpec();\n\n  std::string offlineBody;\n  writeRssMemoryAudit("article.03-before-body-load");\n  const bool bodyLoaded = RssArticleCache::load(article.item, offlineBody);\n  writeRssMemoryAudit("article.04-after-body-load", offlineBody.size(), offlineBody.capacity(), bodyLoaded ? 1 : 0);\n  if (!bodyLoaded) {\n    offlineBody = article.item.summary;\n    writeRssMemoryAudit("article.05-after-summary-fallback", offlineBody.size(), offlineBody.capacity());\n  }\n\n  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {\n    writeRssMemoryAudit("article.06-before-font-ready", offlineBody.size(), offlineBody.capacity());\n    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);\n    writeRssMemoryAudit("article.07-after-font-ready", offlineBody.size(), offlineBody.capacity());\n  } else {\n    writeRssMemoryAudit("article.07-font-ready-skipped", offlineBody.size(), offlineBody.capacity());\n  }\n\n  writeRssMemoryAudit("article.08-before-title-wrap", articleTitleLines.size(), articleTitleLines.capacity());\n  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);\n  writeRssMemoryAudit("article.09-after-title-wrap", articleTitleLines.size(), articleTitleLines.capacity());\n\n  writeRssMemoryAudit("article.10-before-body-wrap", articleSummaryLines.size(), articleSummaryLines.capacity(),\n                      offlineBody.size(), offlineBody.capacity());\n  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);\n  writeRssMemoryAudit("article.11-after-body-wrap", articleSummaryLines.size(), articleSummaryLines.capacity(),\n                      offlineBody.size(), offlineBody.capacity());\n\n  articleLineOffset = 0;\n  articlePageLines = 8;\n  state = State::ARTICLE;\n  writeRssMemoryAudit("article.12-before-request-update", articleTitleLines.size(), articleSummaryLines.size(),\n                      offlineBody.size(), offlineBody.capacity());\n  requestUpdate();\n  writeRssMemoryAudit("article.13-open-return", articleTitleLines.size(), articleSummaryLines.size(),\n                      offlineBody.size(), offlineBody.capacity());\n}\n''',
    "RSS article deep trace",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::closeArticle() {\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  articleLineOffset = 0;\n  articlePageLines = 8;\n  openArticleIndex = MAX_ARTICLES;\n  state = State::LIST;\n  requestUpdate();\n}\n''',
    '''void RssNewsActivity::closeArticle() {\n  writeRssMemoryAudit("close.00-before-clear", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  writeRssMemoryAudit("close.01-after-clear", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n  articleLineOffset = 0;\n  articlePageLines = 8;\n  openArticleIndex = MAX_ARTICLES;\n  state = State::LIST;\n  writeRssMemoryAudit("close.02-before-request-update");\n  requestUpdate();\n}\n''',
    "RSS article close trace",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::onExit() {\n  // Match the EPUB reader's proven low-memory cleanup path. The glyph/advance\n  // caches that affect contiguous PSRAM belong to the renderer, not merely to\n  // SdCardFontSystem's loader/registry state.\n  const int readerFontId = SETTINGS.getReaderFontId();\n  if (renderer.isSdCardFont(readerFontId)) {\n    renderer.releaseSdCardFontForLowMemory(readerFontId);\n  }\n  sdFontSystem.releaseRegistry();\n\n  Activity::onExit();\n  uiReady = false;\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  displayOrder = nullptr;\n  listItems = nullptr;\n  feedItems = nullptr;\n  articles = nullptr;\n  displayOrderStorage.reset();\n  listItemStorage.reset();\n  feedStorage.reset();\n  articleStorage.reset();\n''',
    '''void RssNewsActivity::onExit() {\n  writeRssMemoryAudit("exit.00-begin", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n\n  // Keep the experimental renderer cleanup in this diagnostic build and measure\n  // it precisely; #184 showed it does not account for the persistent split.\n  const int readerFontId = SETTINGS.getReaderFontId();\n  if (renderer.isSdCardFont(readerFontId)) {\n    renderer.releaseSdCardFontForLowMemory(readerFontId);\n  }\n  sdFontSystem.releaseRegistry();\n  writeRssMemoryAudit("exit.01-after-font-cleanup");\n\n  Activity::onExit();\n  writeRssMemoryAudit("exit.02-after-base-exit");\n  uiReady = false;\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  writeRssMemoryAudit("exit.03-after-line-clear", articleTitleLines.capacity(), articleSummaryLines.capacity());\n  displayOrder = nullptr;\n  listItems = nullptr;\n  feedItems = nullptr;\n  articles = nullptr;\n\n  displayOrderStorage.reset();\n  writeRssMemoryAudit("exit.04-after-display-order-free");\n  listItemStorage.reset();\n  writeRssMemoryAudit("exit.05-after-list-items-free");\n  feedStorage.reset();\n  writeRssMemoryAudit("exit.06-after-feed-free");\n  articleStorage.reset();\n  writeRssMemoryAudit("exit.07-after-article-free");\n''',
    "RSS exit deep trace",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::render(RenderLock&&) {\n  renderer.clearScreen();\n\n  MappedInputManager::Labels labels;\n''',
    '''void RssNewsActivity::render(RenderLock&&) {\n  const State auditState = state;\n  const RssMemSnapshot renderBegin = captureRssMemory();\n  renderer.clearScreen();\n  const RssMemSnapshot renderAfterClear = captureRssMemory();\n\n  MappedInputManager::Labels labels;\n''',
    "RSS render begin trace",
)

rss = replace_once(
    rss,
    '''  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);\n\n  uiReady = false;\n  app.render();\n  uiReady = true;\n  renderer.displayBuffer(screenTransitionRefresh.modeFor(static_cast<uint8_t>(state)));\n}\n''',
    '''  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);\n  const RssMemSnapshot renderAfterHints = captureRssMemory();\n\n  uiReady = false;\n  const RssMemSnapshot renderBeforeApp = captureRssMemory();\n  app.render();\n  const RssMemSnapshot renderAfterApp = captureRssMemory();\n  uiReady = true;\n  renderer.displayBuffer(screenTransitionRefresh.modeFor(static_cast<uint8_t>(state)));\n  const RssMemSnapshot renderAfterDisplay = captureRssMemory();\n\n  // Capture all samples first, then write them. This prevents audit SD I/O from\n  // changing the memory state between the renderer checkpoints themselves.\n  const char* prefix = auditState == State::ARTICLE ? "render-article"\n                       : auditState == State::LIST ? "render-list"\n                                                   : "render-status";\n  char phase[64];\n  std::snprintf(phase, sizeof(phase), "%s.00-begin", prefix);\n  appendRssMemorySnapshot(phase, renderBegin);\n  std::snprintf(phase, sizeof(phase), "%s.01-after-clear", prefix);\n  appendRssMemorySnapshot(phase, renderAfterClear);\n  std::snprintf(phase, sizeof(phase), "%s.02-after-hints", prefix);\n  appendRssMemorySnapshot(phase, renderAfterHints);\n  std::snprintf(phase, sizeof(phase), "%s.03-before-app", prefix);\n  appendRssMemorySnapshot(phase, renderBeforeApp);\n  std::snprintf(phase, sizeof(phase), "%s.04-after-app", prefix);\n  appendRssMemorySnapshot(phase, renderAfterApp);\n  std::snprintf(phase, sizeof(phase), "%s.05-after-display", prefix);\n  appendRssMemorySnapshot(phase, renderAfterDisplay);\n}\n''',
    "RSS render stage trace",
)

rss_path.write_text(rss)


# -----------------------------------------------------------------------------
# ActivityManager: prove what happens after RssNews::onExit(), after destruction,
# after Home is restored, and across the first Home re-render.
# -----------------------------------------------------------------------------
am_path = Path("src/activities/ActivityManager.cpp")
am = am_path.read_text()

am = replace_once(
    am,
    '#include <Memory.h>\n',
    '#include <Memory.h>\n#include <esp_heap_caps.h>\n',
    "ActivityManager heap caps include",
)

am = replace_once(
    am,
    '''namespace {\nconstexpr uint32_t FILE_TRANSFER_MODE_MASK = 0xFF;\n''',
    '''namespace {\nconstexpr const char* RSS_MEM_AUDIT_PATH = "/rss_mem_audit.txt";\n\nstruct RssManagerMemSnapshot {\n  size_t heapFree = 0;\n  size_t heapLargest = 0;\n  size_t psramFree = 0;\n  size_t psramLargest = 0;\n  size_t psramAllocated = 0;\n  size_t psramAllocatedBlocks = 0;\n  size_t psramFreeBlocks = 0;\n};\n\nRssManagerMemSnapshot captureRssManagerMemory() {\n  RssManagerMemSnapshot s;\n#ifndef SIMULATOR\n  s.heapFree = ESP.getFreeHeap();\n  s.heapLargest = ESP.getMaxAllocHeap();\n  s.psramFree = ESP.getFreePsram();\n  s.psramLargest = ESP.getMaxAllocPsram();\n  multi_heap_info_t info{};\n  heap_caps_get_info(&info, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);\n  s.psramAllocated = info.total_allocated_bytes;\n  s.psramAllocatedBlocks = info.allocated_blocks;\n  s.psramFreeBlocks = info.free_blocks;\n#endif\n  return s;\n}\n\nvoid appendRssManagerMemory(const char* phase, const RssManagerMemSnapshot& s) {\n#ifndef SIMULATOR\n  FsFile file = Storage.open(RSS_MEM_AUDIT_PATH, O_WRONLY | O_CREAT | O_APPEND);\n  if (!file) return;\n  char line[288];\n  const int length = std::snprintf(\n      line, sizeof(line),\n      "[%lu] AM.%s: heap=%zu largest=%zu psram=%zu psramLargest=%zu pAlloc=%zu pAllocBlocks=%zu pFreeBlocks=%zu\\n",\n      static_cast<unsigned long>(millis()), phase ? phase : "?", s.heapFree, s.heapLargest, s.psramFree,\n      s.psramLargest, s.psramAllocated, s.psramAllocatedBlocks, s.psramFreeBlocks);\n  if (length > 0) {\n    const size_t bytes = std::min(static_cast<size_t>(length), sizeof(line) - 1);\n    file.write(reinterpret_cast<const uint8_t*>(line), bytes);\n  }\n  file.close();\n#else\n  (void)phase;\n  (void)s;\n#endif\n}\n\nbool rssAuditAwaitHomeRender = false;\n\nconstexpr uint32_t FILE_TRANSFER_MODE_MASK = 0xFF;\n''',
    "ActivityManager RSS audit helpers",
)

am = replace_once(
    am,
    '''      currentActivity->render(std::move(lock));\n      restoredActivityNeedsRender = false;\n''',
    '''      if (rssAuditAwaitHomeRender && currentActivity->isHomeActivity()) {\n        const RssManagerMemSnapshot beforeHomeRender = captureRssManagerMemory();\n        currentActivity->render(std::move(lock));\n        const RssManagerMemSnapshot afterHomeRender = captureRssManagerMemory();\n        // Write only after both samples were captured so logging cannot affect\n        // the Home-render A/B comparison.\n        appendRssManagerMemory("home-render-before", beforeHomeRender);\n        appendRssManagerMemory("home-render-after", afterHomeRender);\n        rssAuditAwaitHomeRender = false;\n      } else {\n        currentActivity->render(std::move(lock));\n      }\n      restoredActivityNeedsRender = false;\n''',
    "ActivityManager Home render A/B trace",
)

am = replace_once(
    am,
    '''void ActivityManager::exitActivity(const RenderLock& lock) {\n  // Note: lock must be held by the caller\n  if (currentActivity) {\n    TouchRegistry::getInstance().clear();\n    currentActivity->onExit();\n    currentActivity.reset();\n  }\n}\n''',
    '''void ActivityManager::exitActivity(const RenderLock& lock) {\n  // Note: lock must be held by the caller\n  if (currentActivity) {\n    const bool auditingRss = currentActivity->name == "RssNews";\n    if (auditingRss) appendRssManagerMemory("before-onExit", captureRssManagerMemory());\n    TouchRegistry::getInstance().clear();\n    currentActivity->onExit();\n    if (auditingRss) appendRssManagerMemory("after-onExit", captureRssManagerMemory());\n    currentActivity.reset();\n    if (auditingRss) {\n      appendRssManagerMemory("after-destroy", captureRssManagerMemory());\n      rssAuditAwaitHomeRender = true;\n    }\n  }\n}\n''',
    "ActivityManager RSS destruction trace",
)

am = replace_once(
    am,
    '''        currentActivity = std::move(stackActivities.back());\n        stackActivities.pop_back();\n        restoredActivityNeedsRender = true;\n''',
    '''        currentActivity = std::move(stackActivities.back());\n        stackActivities.pop_back();\n        restoredActivityNeedsRender = true;\n        if (rssAuditAwaitHomeRender && currentActivity && currentActivity->isHomeActivity()) {\n          appendRssManagerMemory("home-restored-before-render", captureRssManagerMemory());\n        }\n''',
    "ActivityManager Home restore trace",
)

am_path.write_text(am)


# Assertions: fail CI loudly if the diagnostic no longer matches the source.
combined = rss + "\n" + am
checks = {
    "deep audit header": "RSS MEM DEEP AUDIT SESSION",
    "audit self impact": 'audit-io-after-first-write',
    "article body load": 'article.04-after-body-load',
    "font ready": 'article.07-after-font-ready',
    "body wrapping": 'article.11-after-body-wrap',
    "article render": 'render-article',
    "close trace": 'close.01-after-clear',
    "buffer-by-buffer exit": 'exit.07-after-article-free',
    "manager after destroy": 'AM.%s',
    "home render A/B": 'home-render-after',
}
for label, needle in checks.items():
    if needle not in combined:
        raise RuntimeError(f"{label}: verification failed")

# SD-only diagnostic: never add RSSMEM serial output.
if 'LOG_ERR("RSSMEM"' in combined or 'LOG_INF("RSSMEM"' in combined or 'LOG_DBG("RSSMEM"' in combined:
    raise RuntimeError("RSS deep memory audit must remain SD-only")

print("Applied deep RSS PSRAM audit to /rss_mem_audit.txt (SD-only, including ActivityManager destruction/Home render).")
