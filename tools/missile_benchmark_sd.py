from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def one(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)


cpp = CPP.read_text()

cpp = one(
    cpp,
    'constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";\n',
    'constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";\n'
    'constexpr const char BENCHMARK_PATH[] = "/missile-command-benchmark.csv";\n',
    "benchmark path",
)
cpp = one(
    cpp,
    'constexpr int64_t GAME_FRAME_US = 100000;\nconstexpr int EXPLOSION_PHASE_TICKS = 1;\n',
    'constexpr int64_t GAME_FRAME_US = 100000;\n'
    'constexpr uint32_t BENCHMARK_BATCH_FRAMES = 100;\n'
    'constexpr int EXPLOSION_PHASE_TICKS = 1;\n',
    "benchmark batch",
)
cpp = one(
    cpp,
    'constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};\n',
    'constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};\n'
    'FsFile benchmarkLogFile;\n',
    "benchmark file",
)

cpp = one(
    cpp,
    '''  cycleRenderPending_.store(false);\n  pendingTap_ = false;\n  pendingBack_ = false;\n  loadHighScore();''',
    '''  cycleRenderPending_.store(false);\n  pendingTap_ = false;\n  pendingBack_ = false;\n  benchmarkSampleArmed_.store(false);\n  benchmarkFlushPending_.store(false);\n  lastLogicUs_.store(0);\n  lastCycleIntervalUs_.store(0);\n  resetBenchmarkAccumulator();\n  benchmarkLogFile.close();\n  benchmarkLogOpen_ = false;\n  benchmarkSessionStartUs_ = esp_timer_get_time();\n  openBenchmarkLog();\n  loadHighScore();''',
    "onEnter benchmark init",
)
cpp = one(
    cpp,
    '''void MissileCommandActivity::onExit() {\n  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n  saveHighScore();\n  Activity::onExit();\n}''',
    '''void MissileCommandActivity::onExit() {\n  if (benchmarkFlushPending_.load()) flushBenchmarkLog();\n  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n  saveHighScore();\n  closeBenchmarkLog();\n  Activity::onExit();\n}''',
    "onExit benchmark close",
)

cpp = one(
    cpp,
    '''  // A new world step is forbidden until the frame representing the previous\n  // step has finished on the panel. This is the core 1:1 game/display lock.\n  if (cycleRenderPending_.load()) return;\n\n  const int64_t now = esp_timer_get_time();\n  if (lastCycleUs_ == 0) lastCycleUs_ = now;\n  if (now - lastCycleUs_ < GAME_FRAME_US) return;\n  lastCycleUs_ = now;''',
    '''  // SD writes happen only between measured frames. Pausing here and resetting\n  // the cadence afterwards keeps filesystem latency out of the timing samples.\n  if (benchmarkFlushPending_.load() && !cycleRenderPending_.load()) {\n    flushBenchmarkLog();\n    lastCycleUs_ = esp_timer_get_time();\n    return;\n  }\n\n  // A new world step is forbidden until the frame representing the previous\n  // step has finished on the panel. This is the core 1:1 game/display lock.\n  if (cycleRenderPending_.load()) return;\n\n  const int64_t now = esp_timer_get_time();\n  if (lastCycleUs_ == 0) lastCycleUs_ = now;\n  if (now - lastCycleUs_ < GAME_FRAME_US) return;\n  const uint32_t cycleIntervalUs = static_cast<uint32_t>(now - lastCycleUs_);\n  lastCycleUs_ = now;''',
    "loop flush and cycle interval",
)

cpp = one(
    cpp,
    '''  if (pendingTap_) {\n    launchPlayerMissile(pendingTapX_, pendingTapY_);\n    pendingTap_ = false;\n  }\n\n  tickGame(now);\n  if (viewMode_ != ViewMode::Playing) return;\n\n  cycleRenderPending_.store(true);\n  requestUpdate();''',
    '''  const int64_t logicStartUs = esp_timer_get_time();\n  if (pendingTap_) {\n    launchPlayerMissile(pendingTapX_, pendingTapY_);\n    pendingTap_ = false;\n  }\n\n  tickGame(now);\n  const uint32_t logicUs = static_cast<uint32_t>(esp_timer_get_time() - logicStartUs);\n  lastLogicUs_.store(logicUs);\n  lastCycleIntervalUs_.store(cycleIntervalUs);\n  if (viewMode_ != ViewMode::Playing) return;\n\n  benchmarkSampleArmed_.store(true);\n  cycleRenderPending_.store(true);\n  requestUpdate();''',
    "logic timing",
)

cpp = one(
    cpp,
    '''void MissileCommandActivity::renderPlaying() {\n  if (sceneNeedsFullRedraw_) drawFullPlayingScene();\n  drawPlayingFrame();\n\n  // Blocking FAST refresh is deliberate: the next 100 ms simulation/input\n  // cycle cannot begin until this exact frame has completed on the panel.\n  renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n  cycleRenderPending_.store(false);\n}''',
    '''void MissileCommandActivity::renderPlaying() {\n  const int64_t drawStartUs = esp_timer_get_time();\n  if (sceneNeedsFullRedraw_) drawFullPlayingScene();\n  drawPlayingFrame();\n  const int64_t refreshStartUs = esp_timer_get_time();\n\n  // Blocking FAST refresh is deliberate: the next 100 ms simulation/input\n  // cycle cannot begin until this exact frame has completed on the panel.\n  renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n  const int64_t refreshEndUs = esp_timer_get_time();\n\n  if (benchmarkSampleArmed_.exchange(false)) {\n    recordBenchmarkSample(lastLogicUs_.load(),\n                          static_cast<uint32_t>(refreshStartUs - drawStartUs),\n                          static_cast<uint32_t>(refreshEndUs - refreshStartUs),\n                          lastCycleIntervalUs_.load());\n  }\n  cycleRenderPending_.store(false);\n}''',
    "render timing",
)

benchmark_methods = r'''
void MissileCommandActivity::resetBenchmarkAccumulator() {
  benchmarkAccum_ = {};
  benchmarkAccum_.logicMinUs = 0xFFFFFFFFu;
  benchmarkAccum_.drawMinUs = 0xFFFFFFFFu;
  benchmarkAccum_.refreshMinUs = 0xFFFFFFFFu;
  benchmarkAccum_.cycleMinUs = 0xFFFFFFFFu;
}

bool MissileCommandActivity::openBenchmarkLog() {
  if (benchmarkLogOpen_) return true;
  if (!Storage.openFileForWrite("MISSILE BENCH", BENCHMARK_PATH, benchmarkLogFile)) return false;

  static constexpr char HEADER[] =
      "elapsed_ms,target_ms,wave,score,frames,cycle_min_us,cycle_avg_us,cycle_max_us,"
      "logic_min_us,logic_avg_us,logic_max_us,draw_min_us,draw_avg_us,draw_max_us,"
      "refresh_min_us,refresh_avg_us,refresh_max_us,work_avg_us,work_max_us,"
      "over_budget_frames,panel_fps,real_fps\n";
  const size_t expected = sizeof(HEADER) - 1;
  if (benchmarkLogFile.write(reinterpret_cast<const uint8_t*>(HEADER), expected) != expected) {
    benchmarkLogFile.close();
    return false;
  }
  benchmarkLogFile.sync();
  benchmarkLogOpen_ = true;
  return true;
}

void MissileCommandActivity::closeBenchmarkLog() {
  if (!benchmarkLogOpen_) return;
  benchmarkLogFile.sync();
  benchmarkLogFile.close();
  benchmarkLogOpen_ = false;
}

void MissileCommandActivity::recordBenchmarkSample(uint32_t logicUs, uint32_t drawUs,
                                                   uint32_t refreshUs, uint32_t cycleUs) {
  auto& b = benchmarkAccum_;
  ++b.frames;
  b.logicSumUs += logicUs;
  b.drawSumUs += drawUs;
  b.refreshSumUs += refreshUs;
  b.cycleSumUs += cycleUs;
  const uint32_t workUs = logicUs + drawUs + refreshUs;
  b.workSumUs += workUs;

  b.logicMinUs = std::min(b.logicMinUs, logicUs);
  b.logicMaxUs = std::max(b.logicMaxUs, logicUs);
  b.drawMinUs = std::min(b.drawMinUs, drawUs);
  b.drawMaxUs = std::max(b.drawMaxUs, drawUs);
  b.refreshMinUs = std::min(b.refreshMinUs, refreshUs);
  b.refreshMaxUs = std::max(b.refreshMaxUs, refreshUs);
  b.cycleMinUs = std::min(b.cycleMinUs, cycleUs);
  b.cycleMaxUs = std::max(b.cycleMaxUs, cycleUs);
  b.workMaxUs = std::max(b.workMaxUs, workUs);
  if (workUs > static_cast<uint32_t>(GAME_FRAME_US)) ++b.overBudgetFrames;

  if (b.frames < BENCHMARK_BATCH_FRAMES || benchmarkFlushPending_.load()) return;

  benchmarkSnapshot_.elapsedMs = static_cast<uint32_t>((esp_timer_get_time() - benchmarkSessionStartUs_) / 1000);
  benchmarkSnapshot_.wave = wave_;
  benchmarkSnapshot_.score = score_;
  benchmarkSnapshot_.frames = b.frames;
  benchmarkSnapshot_.cycleMinUs = b.cycleMinUs;
  benchmarkSnapshot_.cycleAvgUs = static_cast<uint32_t>(b.cycleSumUs / b.frames);
  benchmarkSnapshot_.cycleMaxUs = b.cycleMaxUs;
  benchmarkSnapshot_.logicMinUs = b.logicMinUs;
  benchmarkSnapshot_.logicAvgUs = static_cast<uint32_t>(b.logicSumUs / b.frames);
  benchmarkSnapshot_.logicMaxUs = b.logicMaxUs;
  benchmarkSnapshot_.drawMinUs = b.drawMinUs;
  benchmarkSnapshot_.drawAvgUs = static_cast<uint32_t>(b.drawSumUs / b.frames);
  benchmarkSnapshot_.drawMaxUs = b.drawMaxUs;
  benchmarkSnapshot_.refreshMinUs = b.refreshMinUs;
  benchmarkSnapshot_.refreshAvgUs = static_cast<uint32_t>(b.refreshSumUs / b.frames);
  benchmarkSnapshot_.refreshMaxUs = b.refreshMaxUs;
  benchmarkSnapshot_.workAvgUs = static_cast<uint32_t>(b.workSumUs / b.frames);
  benchmarkSnapshot_.workMaxUs = b.workMaxUs;
  benchmarkSnapshot_.overBudgetFrames = b.overBudgetFrames;

  resetBenchmarkAccumulator();
  benchmarkFlushPending_.store(true);
}

void MissileCommandActivity::flushBenchmarkLog() {
  if (!benchmarkFlushPending_.exchange(false)) return;
  if (!benchmarkLogOpen_ && !openBenchmarkLog()) return;

  const auto& b = benchmarkSnapshot_;
  const uint32_t panelFpsX100 = b.refreshAvgUs > 0 ? 100000000u / b.refreshAvgUs : 0;
  const uint32_t realFpsX100 = b.cycleAvgUs > 0 ? 100000000u / b.cycleAvgUs : 0;
  char row[384];
  const int length = std::snprintf(
      row, sizeof(row),
      "%lu,100,%u,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu.%02lu,%lu.%02lu\n",
      static_cast<unsigned long>(b.elapsedMs), static_cast<unsigned>(b.wave),
      static_cast<unsigned long>(b.score), static_cast<unsigned long>(b.frames),
      static_cast<unsigned long>(b.cycleMinUs), static_cast<unsigned long>(b.cycleAvgUs),
      static_cast<unsigned long>(b.cycleMaxUs), static_cast<unsigned long>(b.logicMinUs),
      static_cast<unsigned long>(b.logicAvgUs), static_cast<unsigned long>(b.logicMaxUs),
      static_cast<unsigned long>(b.drawMinUs), static_cast<unsigned long>(b.drawAvgUs),
      static_cast<unsigned long>(b.drawMaxUs), static_cast<unsigned long>(b.refreshMinUs),
      static_cast<unsigned long>(b.refreshAvgUs), static_cast<unsigned long>(b.refreshMaxUs),
      static_cast<unsigned long>(b.workAvgUs), static_cast<unsigned long>(b.workMaxUs),
      static_cast<unsigned long>(b.overBudgetFrames),
      static_cast<unsigned long>(panelFpsX100 / 100), static_cast<unsigned long>(panelFpsX100 % 100),
      static_cast<unsigned long>(realFpsX100 / 100), static_cast<unsigned long>(realFpsX100 % 100));

  if (length <= 0 || length >= static_cast<int>(sizeof(row)) ||
      benchmarkLogFile.write(reinterpret_cast<const uint8_t*>(row), static_cast<size_t>(length)) !=
          static_cast<size_t>(length)) {
    closeBenchmarkLog();
    return;
  }
  benchmarkLogFile.sync();
}

'''
cpp = one(cpp, "bool MissileCommandActivity::saveGame() {\n", benchmark_methods + "bool MissileCommandActivity::saveGame() {\n", "benchmark methods")

CPP.write_text(cpp)

hdr = HDR.read_text()

structs = r'''
  struct BenchmarkAccumulator {
    uint32_t frames = 0;
    uint64_t logicSumUs = 0;
    uint64_t drawSumUs = 0;
    uint64_t refreshSumUs = 0;
    uint64_t cycleSumUs = 0;
    uint64_t workSumUs = 0;
    uint32_t logicMinUs = 0xFFFFFFFFu;
    uint32_t logicMaxUs = 0;
    uint32_t drawMinUs = 0xFFFFFFFFu;
    uint32_t drawMaxUs = 0;
    uint32_t refreshMinUs = 0xFFFFFFFFu;
    uint32_t refreshMaxUs = 0;
    uint32_t cycleMinUs = 0xFFFFFFFFu;
    uint32_t cycleMaxUs = 0;
    uint32_t workMaxUs = 0;
    uint32_t overBudgetFrames = 0;
  };

  struct BenchmarkSnapshot {
    uint32_t elapsedMs = 0;
    uint16_t wave = 0;
    uint32_t score = 0;
    uint32_t frames = 0;
    uint32_t cycleMinUs = 0;
    uint32_t cycleAvgUs = 0;
    uint32_t cycleMaxUs = 0;
    uint32_t logicMinUs = 0;
    uint32_t logicAvgUs = 0;
    uint32_t logicMaxUs = 0;
    uint32_t drawMinUs = 0;
    uint32_t drawAvgUs = 0;
    uint32_t drawMaxUs = 0;
    uint32_t refreshMinUs = 0;
    uint32_t refreshAvgUs = 0;
    uint32_t refreshMaxUs = 0;
    uint32_t workAvgUs = 0;
    uint32_t workMaxUs = 0;
    uint32_t overBudgetFrames = 0;
  };
'''
hdr = one(hdr, "  struct Explosion {\n", structs + "\n  struct Explosion {\n", "benchmark structs")

hdr = one(
    hdr,
    '''  bool pendingBack_ = false;\n\n  static void menuScreen''',
    '''  bool pendingBack_ = false;\n\n  // Timing samples cross the main gameplay task and the render task. Only a\n  // completed, synchronized frame becomes a benchmark sample.\n  std::atomic<uint32_t> lastLogicUs_{0};\n  std::atomic<uint32_t> lastCycleIntervalUs_{0};\n  std::atomic<bool> benchmarkSampleArmed_{false};\n  std::atomic<bool> benchmarkFlushPending_{false};\n  BenchmarkAccumulator benchmarkAccum_{};\n  BenchmarkSnapshot benchmarkSnapshot_{};\n  int64_t benchmarkSessionStartUs_ = 0;\n  bool benchmarkLogOpen_ = false;\n\n  static void menuScreen''',
    "benchmark state",
)

hdr = one(
    hdr,
    '''  void drawFullPlayingScene();\n  void drawPlayingFrame();\n\n  void newGame();''',
    '''  void drawFullPlayingScene();\n  void drawPlayingFrame();\n\n  void resetBenchmarkAccumulator();\n  bool openBenchmarkLog();\n  void closeBenchmarkLog();\n  void recordBenchmarkSample(uint32_t logicUs, uint32_t drawUs, uint32_t refreshUs, uint32_t cycleUs);\n  void flushBenchmarkLog();\n\n  void newGame();''',
    "benchmark declarations",
)

HDR.write_text(hdr)
print("Missile Command SD benchmark instrumentation staged")
