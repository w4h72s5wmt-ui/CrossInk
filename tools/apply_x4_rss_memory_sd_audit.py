from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# RSS activity: deep SD-only memory trace.
# Runs after all functional RSS overlays, so use small stable insertion anchors
# instead of replacing whole functions that other overlays already reshape.
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
    '''namespace {\nconstexpr fui::ActionId ACTION_ROW = 1;\nconstexpr const char* RSS_MEM_AUDIT_PATH = "/rss_mem_audit.txt";\n\nstruct RssMemSnapshot {\n  size_t heapFree = 0;\n  size_t heapLargest = 0;\n  size_t psramFree = 0;\n  size_t psramLargest = 0;\n  size_t psramAllocated = 0;\n  size_t psramMinimumFree = 0;\n  size_t psramAllocatedBlocks = 0;\n  size_t psramFreeBlocks = 0;\n  size_t psramTotalBlocks = 0;\n};\n\nRssMemSnapshot captureRssMemory() {\n  RssMemSnapshot snapshot;\n#ifndef SIMULATOR\n  snapshot.heapFree = ESP.getFreeHeap();\n  snapshot.heapLargest = ESP.getMaxAllocHeap();\n  snapshot.psramFree = ESP.getFreePsram();\n  snapshot.psramLargest = ESP.getMaxAllocPsram();\n  multi_heap_info_t info{};\n  heap_caps_get_info(&info, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);\n  snapshot.psramAllocated = info.total_allocated_bytes;\n  snapshot.psramMinimumFree = info.minimum_free_bytes;\n  snapshot.psramAllocatedBlocks = info.allocated_blocks;\n  snapshot.psramFreeBlocks = info.free_blocks;\n  snapshot.psramTotalBlocks = info.total_blocks;\n#endif\n  return snapshot;\n}\n\nvoid appendRssMemorySnapshot(const char* phase, const RssMemSnapshot& snapshot,\n                             const size_t meta1 = 0, const size_t meta2 = 0,\n                             const size_t meta3 = 0, const size_t meta4 = 0) {\n#ifndef SIMULATOR\n  static bool sessionHeaderWritten = false;\n  FsFile file = Storage.open(RSS_MEM_AUDIT_PATH, O_WRONLY | O_CREAT | O_APPEND);\n  if (!file) return;\n  if (!sessionHeaderWritten) {\n    static constexpr char header[] = "\\n--- RSS MEM DEEP AUDIT SESSION ---\\n";\n    file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);\n    sessionHeaderWritten = true;\n  }\n  char line[384];\n  const int length = std::snprintf(\n      line, sizeof(line),\n      "[%lu] %s: heap=%zu largest=%zu psram=%zu psramLargest=%zu pAlloc=%zu pMin=%zu "\n      "pAllocBlocks=%zu pFreeBlocks=%zu pTotalBlocks=%zu m1=%zu m2=%zu m3=%zu m4=%zu\\n",\n      static_cast<unsigned long>(millis()), phase ? phase : "?", snapshot.heapFree, snapshot.heapLargest,\n      snapshot.psramFree, snapshot.psramLargest, snapshot.psramAllocated, snapshot.psramMinimumFree,\n      snapshot.psramAllocatedBlocks, snapshot.psramFreeBlocks, snapshot.psramTotalBlocks,\n      meta1, meta2, meta3, meta4);\n  if (length > 0) {\n    const size_t bytes = std::min(static_cast<size_t>(length), sizeof(line) - 1);\n    file.write(reinterpret_cast<const uint8_t*>(line), bytes);\n  }\n  file.close();\n#else\n  (void)phase;\n  (void)snapshot;\n  (void)meta1;\n  (void)meta2;\n  (void)meta3;\n  (void)meta4;\n#endif\n}\n\nvoid writeRssMemoryAudit(const char* phase, const size_t meta1 = 0, const size_t meta2 = 0,\n                         const size_t meta3 = 0, const size_t meta4 = 0) {\n#ifndef SIMULATOR\n  // Measure first, write second. The first call also records the lazy FAT/SD\n  // cache cost of creating/appending this diagnostic file itself.\n  static bool firstWriteChecked = false;\n  const RssMemSnapshot beforeIo = captureRssMemory();\n  appendRssMemorySnapshot(phase, beforeIo, meta1, meta2, meta3, meta4);\n  if (!firstWriteChecked) {\n    firstWriteChecked = true;\n    appendRssMemorySnapshot("audit-io-after-first-write", captureRssMemory());\n  }\n#else\n  (void)phase;\n  (void)meta1;\n  (void)meta2;\n  (void)meta3;\n  (void)meta4;\n#endif\n}\n''',
    "RSS deep audit helpers",
)

# Entry lifecycle.
rss = replace_once(
    rss,
    '''void RssNewsActivity::onEnter() {\n  Activity::onEnter();\n  sdFontSystem.releaseLoadedFont(renderer);\n''',
    '''void RssNewsActivity::onEnter() {\n  writeRssMemoryAudit("enter.00-before-activity");\n  Activity::onEnter();\n  writeRssMemoryAudit("enter.01-after-activity");\n  sdFontSystem.releaseLoadedFont(renderer);\n  writeRssMemoryAudit("enter.02-after-loader-release");\n''',
    "RSS entry lifecycle trace",
)

rss = replace_once(
    rss,
    '''  loadSources();\n  if (!ensureBuffers()) {\n''',
    '''  writeRssMemoryAudit("enter.03-before-load-sources");\n  loadSources();\n  writeRssMemoryAudit("enter.04-after-load-sources", sourceCount);\n  writeRssMemoryAudit("enter.05-before-buffers");\n  if (!ensureBuffers()) {\n''',
    "RSS source/buffer entry trace",
)

rss = replace_once(
    rss,
    '''  } else {\n    loadCache();\n    rebuildDisplayOrder();\n  }\n  requestUpdate();\n}\n''',
    '''  } else {\n    writeRssMemoryAudit("enter.06-after-buffers");\n    loadCache();\n    writeRssMemoryAudit("enter.07-after-cache-load", articleCount);\n    rebuildDisplayOrder();\n    writeRssMemoryAudit("enter.08-after-display-order", articleCount);\n  }\n  writeRssMemoryAudit("enter.09-before-request-update");\n  requestUpdate();\n}\n''',
    "RSS post-buffer entry trace",
)

# Article opening, broken into small anchors so previous layout overlays cannot
# invalidate the diagnostic merely by changing unrelated lines.
rss = replace_once(
    rss,
    '''void RssNewsActivity::openArticle(const size_t articleIndex) {\n  if (!articles || articleIndex >= articleCount) return;\n  openArticleIndex = articleIndex;\n''',
    '''void RssNewsActivity::openArticle(const size_t articleIndex) {\n  if (!articles || articleIndex >= articleCount) return;\n  writeRssMemoryAudit("article.00-open-begin", articleIndex, articleCount);\n  openArticleIndex = articleIndex;\n''',
    "RSS article begin trace",
)

rss = replace_once(
    rss,
    '''  sdFontSystem.ensureLoaded(renderer);\n  const int readerFontId = SETTINGS.getReaderFontId();\n''',
    '''  writeRssMemoryAudit("article.01-before-font-loader");\n  sdFontSystem.ensureLoaded(renderer);\n  writeRssMemoryAudit("article.02-after-font-loader");\n  const int readerFontId = SETTINGS.getReaderFontId();\n''',
    "RSS font loader trace",
)

rss = replace_once(
    rss,
    '''  std::string offlineBody;\n  if (!RssArticleCache::load(article.item, offlineBody)) offlineBody = article.item.summary;\n''',
    '''  std::string offlineBody;\n  writeRssMemoryAudit("article.03-before-body-load");\n  const bool bodyLoaded = RssArticleCache::load(article.item, offlineBody);\n  writeRssMemoryAudit("article.04-after-body-load", offlineBody.size(), offlineBody.capacity(), bodyLoaded ? 1 : 0);\n  if (!bodyLoaded) {\n    offlineBody = article.item.summary;\n    writeRssMemoryAudit("article.05-after-summary-fallback", offlineBody.size(), offlineBody.capacity());\n  }\n''',
    "RSS body load trace",
)

rss = replace_once(
    rss,
    '''  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {\n    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);\n  }\n''',
    '''  if (renderer.isSdCardFont(readerFontId) && !offlineBody.empty()) {\n    writeRssMemoryAudit("article.06-before-font-ready", offlineBody.size(), offlineBody.capacity());\n    renderer.ensureSdCardFontReady(readerFontId, offlineBody.c_str(), /*styleMask=*/0x01);\n    writeRssMemoryAudit("article.07-after-font-ready", offlineBody.size(), offlineBody.capacity());\n  } else {\n    writeRssMemoryAudit("article.07-font-ready-skipped", offlineBody.size(), offlineBody.capacity());\n  }\n''',
    "RSS font ready trace",
)

# The readability overlay intentionally changed the title cap from 4 to 3.
rss = replace_once(
    rss,
    '''  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 3);\n''',
    '''  writeRssMemoryAudit("article.08-before-title-wrap", articleTitleLines.size(), articleTitleLines.capacity());\n  articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 3);\n  writeRssMemoryAudit("article.09-after-title-wrap", articleTitleLines.size(), articleTitleLines.capacity());\n''',
    "RSS title wrap trace",
)

rss = replace_once(
    rss,
    '''  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);\n''',
    '''  writeRssMemoryAudit("article.10-before-body-wrap", articleSummaryLines.size(), articleSummaryLines.capacity(),\n                      offlineBody.size(), offlineBody.capacity());\n  articleSummaryLines = renderer.wrappedText(readerFontId, offlineBody.c_str(), maxWidth, 2000);\n  writeRssMemoryAudit("article.11-after-body-wrap", articleSummaryLines.size(), articleSummaryLines.capacity(),\n                      offlineBody.size(), offlineBody.capacity());\n''',
    "RSS body wrap trace",
)

rss = replace_once(
    rss,
    '''  state = State::ARTICLE;\n  requestUpdate();\n}\n''',
    '''  state = State::ARTICLE;\n  writeRssMemoryAudit("article.12-before-request-update", articleTitleLines.size(), articleSummaryLines.size(),\n                      offlineBody.size(), offlineBody.capacity());\n  requestUpdate();\n  writeRssMemoryAudit("article.13-open-return", articleTitleLines.size(), articleSummaryLines.size(),\n                      offlineBody.size(), offlineBody.capacity());\n}\n''',
    "RSS article request trace",
)

# Article close: clear() preserves vector capacity, which is exactly what this
# audit needs to prove before we decide whether shrink/reset is worthwhile.
rss = replace_once(
    rss,
    '''void RssNewsActivity::closeArticle() {\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n''',
    '''void RssNewsActivity::closeArticle() {\n  writeRssMemoryAudit("close.00-before-clear", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  writeRssMemoryAudit("close.01-after-clear", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n''',
    "RSS article clear trace",
)

rss = replace_once(
    rss,
    '''  state = State::LIST;\n  requestUpdate();\n}\n\nvoid RssNewsActivity::scrollArticle''',
    '''  state = State::LIST;\n  writeRssMemoryAudit("close.02-before-request-update");\n  requestUpdate();\n}\n\nvoid RssNewsActivity::scrollArticle''',
    "RSS article close request trace",
)

# Exit lifecycle. Readability adds listMetaStorage/listMetaText, so instrument
# each resource independently rather than replacing the whole function.
rss = replace_once(
    rss,
    '''void RssNewsActivity::onExit() {\n  // Match the EPUB reader's proven low-memory cleanup path.''',
    '''void RssNewsActivity::onExit() {\n  writeRssMemoryAudit("exit.00-begin", articleTitleLines.size(), articleTitleLines.capacity(),\n                      articleSummaryLines.size(), articleSummaryLines.capacity());\n  // Match the EPUB reader's proven low-memory cleanup path.''',
    "RSS exit begin trace",
)

rss = replace_once(
    rss,
    '''  sdFontSystem.releaseRegistry();\n\n  Activity::onExit();\n''',
    '''  sdFontSystem.releaseRegistry();\n  writeRssMemoryAudit("exit.01-after-font-cleanup");\n\n  Activity::onExit();\n  writeRssMemoryAudit("exit.02-after-base-exit");\n''',
    "RSS exit font/base trace",
)

rss = replace_once(
    rss,
    '''  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  displayOrder = nullptr;\n''',
    '''  articleTitleLines.clear();\n  articleSummaryLines.clear();\n  writeRssMemoryAudit("exit.03-after-line-clear", articleTitleLines.capacity(), articleSummaryLines.capacity());\n  displayOrder = nullptr;\n''',
    "RSS exit line vector trace",
)

rss = replace_once(
    rss,
    '''  displayOrderStorage.reset();\n  listMetaStorage.reset();\n  listItemStorage.reset();\n  feedStorage.reset();\n  articleStorage.reset();\n''',
    '''  displayOrderStorage.reset();\n  writeRssMemoryAudit("exit.04-after-display-order-free");\n  listMetaStorage.reset();\n  writeRssMemoryAudit("exit.05-after-list-meta-free");\n  listItemStorage.reset();\n  writeRssMemoryAudit("exit.06-after-list-items-free");\n  feedStorage.reset();\n  writeRssMemoryAudit("exit.07-after-feed-free");\n  articleStorage.reset();\n  writeRssMemoryAudit("exit.08-after-article-free");\n''',
    "RSS buffer-by-buffer exit trace",
)

# Render checkpoints are sampled first and only written after displayBuffer so
# SD logging cannot perturb the measured renderer stages themselves.
rss = replace_once(
    rss,
    '''void RssNewsActivity::render(RenderLock&&) {\n  renderer.clearScreen();\n''',
    '''void RssNewsActivity::render(RenderLock&&) {\n  const State auditState = state;\n  const RssMemSnapshot renderBegin = captureRssMemory();\n  renderer.clearScreen();\n  const RssMemSnapshot renderAfterClear = captureRssMemory();\n''',
    "RSS render begin trace",
)

rss = replace_once(
    rss,
    '''  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);\n\n  uiReady = false;\n  app.render();\n  uiReady = true;\n  renderer.displayBuffer(screenTransitionRefresh.modeFor(static_cast<uint8_t>(state)));\n}\n''',
    '''  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);\n  const RssMemSnapshot renderAfterHints = captureRssMemory();\n\n  uiReady = false;\n  const RssMemSnapshot renderBeforeApp = captureRssMemory();\n  app.render();\n  const RssMemSnapshot renderAfterApp = captureRssMemory();\n  uiReady = true;\n  renderer.displayBuffer(screenTransitionRefresh.modeFor(static_cast<uint8_t>(state)));\n  const RssMemSnapshot renderAfterDisplay = captureRssMemory();\n\n  const char* prefix = auditState == State::ARTICLE ? "render-article"\n                       : auditState == State::LIST ? "render-list"\n                                                   : "render-status";\n  char phase[64];\n  std::snprintf(phase, sizeof(phase), "%s.00-begin", prefix);\n  appendRssMemorySnapshot(phase, renderBegin);\n  std::snprintf(phase, sizeof(phase), "%s.01-after-clear", prefix);\n  appendRssMemorySnapshot(phase, renderAfterClear);\n  std::snprintf(phase, sizeof(phase), "%s.02-after-hints", prefix);\n  appendRssMemorySnapshot(phase, renderAfterHints);\n  std::snprintf(phase, sizeof(phase), "%s.03-before-app", prefix);\n  appendRssMemorySnapshot(phase, renderBeforeApp);\n  std::snprintf(phase, sizeof(phase), "%s.04-after-app", prefix);\n  appendRssMemorySnapshot(phase, renderAfterApp);\n  std::snprintf(phase, sizeof(phase), "%s.05-after-display", prefix);\n  appendRssMemorySnapshot(phase, renderAfterDisplay);\n}\n''',
    "RSS render stage trace",
)

rss_path.write_text(rss)


# -----------------------------------------------------------------------------
# ActivityManager: capture after RssNews::onExit(), after actual destructor,
# after Home restoration and around Home's first render.
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
    '''      if (rssAuditAwaitHomeRender && currentActivity->isHomeActivity()) {\n        const RssManagerMemSnapshot beforeHomeRender = captureRssManagerMemory();\n        currentActivity->render(std::move(lock));\n        const RssManagerMemSnapshot afterHomeRender = captureRssManagerMemory();\n        appendRssManagerMemory("home-render-before", beforeHomeRender);\n        appendRssManagerMemory("home-render-after", afterHomeRender);\n        rssAuditAwaitHomeRender = false;\n      } else {\n        currentActivity->render(std::move(lock));\n      }\n      restoredActivityNeedsRender = false;\n''',
    "ActivityManager Home render trace",
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


combined = rss + "\n" + am
checks = {
    "deep audit header": "RSS MEM DEEP AUDIT SESSION",
    "audit self impact": "audit-io-after-first-write",
    "source load trace": "enter.04-after-load-sources",
    "article body trace": "article.04-after-body-load",
    "font ready trace": "article.07-after-font-ready",
    "body wrap trace": "article.11-after-body-wrap",
    "article render trace": "render-article",
    "close trace": "close.01-after-clear",
    "list meta free trace": "exit.05-after-list-meta-free",
    "article buffer free trace": "exit.08-after-article-free",
    "manager destroy trace": "after-destroy",
    "home render trace": "home-render-after",
}
for label, needle in checks.items():
    if needle not in combined:
        raise RuntimeError(f"{label}: verification failed")

if 'LOG_ERR("RSSMEM"' in combined or 'LOG_INF("RSSMEM"' in combined or 'LOG_DBG("RSSMEM"' in combined:
    raise RuntimeError("RSS deep memory audit must remain SD-only")

print("Applied robust deep RSS PSRAM audit to /rss_mem_audit.txt (SD-only).")
