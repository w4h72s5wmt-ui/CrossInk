from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


BUS_H = "freeink-sdk/libs/display/FreeInkDisplay/src/bus/EpdBus.h"
DISPLAY_H = "freeink-sdk/libs/display/FreeInkDisplay/include/FreeInkDisplay.h"
DISPLAY_CPP = "freeink-sdk/libs/display/FreeInkDisplay/src/FreeInkDisplay.cpp"
HAL_H = "lib/hal/HalDisplay.h"
HAL_CPP = "lib/hal/HalDisplay.cpp"
MISSILE_H = "src/activities/home/MissileCommandActivity.h"
MISSILE_CPP = "src/activities/home/MissileCommandActivity.cpp"

# Keep the faster SPI clock scoped to a single call. EpdBus uses SPISettings for
# every individual command/data transaction, so changing this value before the
# Missile window call and restoring it immediately afterward leaves every other
# CrossInk screen at the board/controller default.
replace_once(
    BUS_H,
    "  const EpdPins& pins() const { return _pins; }\n"
    "  uint32_t spiHz() const { return _spiHz; }\n",
    "  const EpdPins& pins() const { return _pins; }\n"
    "  // Experimental per-operation clock override. Call only between SPI transactions.\n"
    "  void setSpiHz(uint32_t spiHz) {\n"
    "    if (spiHz == 0 || spiHz == _spiHz) return;\n"
    "    _spiHz = spiHz;\n"
    "    _spi = SPISettings(spiHz, MSBFIRST, SPI_MODE0);\n"
    "  }\n"
    "  uint32_t spiHz() const { return _spiHz; }\n",
)

replace_once(
    DISPLAY_H,
    "  // EXPERIMENTAL: Windowed update - display only a rectangular region\n"
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n",
    "  // EXPERIMENTAL: Windowed update - display only a rectangular region\n"
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n"
    "  // Same operation with a temporary SPI clock. The prior bus clock is restored\n"
    "  // before returning, so callers cannot leak the experiment into other screens.\n"
    "  void displayWindowAtSpiHz(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint32_t spiHz,\n"
    "                            bool turnOffScreen = false);\n",
)

scoped_display_impl = r'''
void FreeInkDisplay::displayWindowAtSpiHz(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint32_t spiHz,
                                         bool turnOffScreen) {
  // Drain any previous operation at its original clock before touching the bus
  // setting. displayWindow() is blocking, so restoration happens only after all
  // window DTM writes, LUT setup, waveform wait and DTM1 re-sync have completed.
  syncPendingAsync();
  const uint32_t previousSpiHz = _bus.spiHz();
  if (spiHz != 0) _bus.setSpiHz(spiHz);
  displayWindow(x, y, w, h, turnOffScreen);
  if (spiHz != 0) _bus.setSpiHz(previousSpiHz);
}

'''
replace_once(
    DISPLAY_CPP,
    "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n",
    scoped_display_impl
    + "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n",
)

replace_once(
    HAL_H,
    "  // Experimental UC8279 window path: physical panel coordinates, byte-aligned X.\n"
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n",
    "  // Experimental UC8279 window path: physical panel coordinates, byte-aligned X.\n"
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n"
    "  // Missile-only experiment: temporarily run this one window transfer at the\n"
    "  // requested SPI clock and restore the display bus clock before returning.\n"
    "  void displayWindowAtSpiHz(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint32_t spiHz,\n"
    "                            bool turnOffScreen = false);\n",
)

hal_scoped_impl = r'''void HalDisplay::displayWindowAtSpiHz(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint32_t spiHz,
                                        bool turnOffScreen) {
  HalSpiBus::Lock spiLock;
  einkDisplay.displayWindowAtSpiHz(x, y, w, h, spiHz, turnOffScreen);
}

'''
replace_once(
    HAL_CPP,
    "void HalDisplay::setInverted(bool inverted) {\n",
    hal_scoped_impl + "void HalDisplay::setInverted(bool inverted) {\n",
)

# Frame-by-frame dirty-window telemetry is buffered in PSRAM so the SD write
# cannot pollute the refresh_us measurement. It is flushed once after 200 real
# window refreshes (or on activity exit when a shorter sample was collected).
replace_once(
    MISSILE_H,
    "  uint8_t* windowShadow_ = nullptr;\n"
    "  bool windowShadowValid_ = false;\n",
    "  uint8_t* windowShadow_ = nullptr;\n"
    "  bool windowShadowValid_ = false;\n"
    "\n"
    "  struct DirtyWindowBenchSample {\n"
    "    uint32_t frame = 0;\n"
    "    uint16_t x = 0;\n"
    "    uint16_t y = 0;\n"
    "    uint16_t w = 0;\n"
    "    uint16_t h = 0;\n"
    "    uint32_t bboxPixels = 0;\n"
    "    uint32_t changedPixels = 0;\n"
    "    uint32_t whiteToBlack = 0;\n"
    "    uint32_t blackToWhite = 0;\n"
    "    uint32_t refreshUs = 0;\n"
    "    uint32_t frameCycleUs = 0;\n"
    "  };\n"
    "  static constexpr uint16_t kDirtyWindowBenchTargetSamples = 200;\n"
    "  DirtyWindowBenchSample* dirtyWindowBenchSamples_ = nullptr;\n"
    "  uint16_t dirtyWindowBenchSampleCount_ = 0;\n"
    "  uint32_t dirtyWindowBenchFrame_ = 0;\n"
    "  int64_t dirtyWindowBenchLastFrameUs_ = 0;\n"
    "  bool dirtyWindowBenchSaved_ = false;\n",
)
replace_once(
    MISSILE_H,
    "  void refreshPlayingWindow(bool forceFullRefresh);\n"
    "  void releaseWindowShadow();\n",
    "  void refreshPlayingWindow(bool forceFullRefresh);\n"
    "  void appendDirtyWindowBenchSample(uint16_t x, uint16_t y, uint16_t w, uint16_t h,\n"
    "                                    uint32_t changedPixels, uint32_t whiteToBlack,\n"
    "                                    uint32_t blackToWhite, uint32_t refreshUs, uint32_t frameCycleUs);\n"
    "  void saveDirtyWindowBenchmark();\n"
    "  void releaseWindowShadow();\n",
)

replace_once(
    MISSILE_CPP,
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";\n',
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";\n'
    'constexpr const char DIRTY_WINDOW_BENCH_PATH[] = "/missile-command-hybrida-spi30-dirty.csv";\n'
    'constexpr uint32_t MISSILE_WINDOW_SPI_HZ = 30000000;\n',
)

old_release = r'''void MissileCommandActivity::releaseWindowShadow() {
  if (windowShadow_ != nullptr) {
    heap_caps_free(windowShadow_);
    windowShadow_ = nullptr;
  }
  windowShadowValid_ = false;
}
'''
new_release_and_bench = r'''void MissileCommandActivity::saveDirtyWindowBenchmark() {
  if (dirtyWindowBenchSaved_ || dirtyWindowBenchSampleCount_ == 0 || dirtyWindowBenchSamples_ == nullptr) return;

  FsFile file;
  if (!Storage.openFileForWrite("MISSILE-DIRTY", DIRTY_WINDOW_BENCH_PATH, file)) return;

  const char header[] =
      "frame,x,y,w,h,bbox_pixels,changed_pixels,white_to_black,black_to_white,refresh_us,frame_cycle_us,spi_hz\n";
  file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
  for (uint16_t i = 0; i < dirtyWindowBenchSampleCount_; ++i) {
    const DirtyWindowBenchSample& s = dirtyWindowBenchSamples_[i];
    char line[192];
    const int n = std::snprintf(
        line, sizeof(line), "%lu,%u,%u,%u,%u,%lu,%lu,%lu,%lu,%lu,%lu,%lu\n",
        static_cast<unsigned long>(s.frame), static_cast<unsigned>(s.x), static_cast<unsigned>(s.y),
        static_cast<unsigned>(s.w), static_cast<unsigned>(s.h), static_cast<unsigned long>(s.bboxPixels),
        static_cast<unsigned long>(s.changedPixels), static_cast<unsigned long>(s.whiteToBlack),
        static_cast<unsigned long>(s.blackToWhite), static_cast<unsigned long>(s.refreshUs),
        static_cast<unsigned long>(s.frameCycleUs), static_cast<unsigned long>(MISSILE_WINDOW_SPI_HZ));
    if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
  }
  file.close();
  dirtyWindowBenchSaved_ = true;
  heap_caps_free(dirtyWindowBenchSamples_);
  dirtyWindowBenchSamples_ = nullptr;
}

void MissileCommandActivity::appendDirtyWindowBenchSample(uint16_t x, uint16_t y, uint16_t w, uint16_t h,
                                                           uint32_t changedPixels, uint32_t whiteToBlack,
                                                           uint32_t blackToWhite, uint32_t refreshUs,
                                                           uint32_t frameCycleUs) {
  if (dirtyWindowBenchSaved_) return;
  if (dirtyWindowBenchSamples_ == nullptr) {
    const size_t bytes = sizeof(DirtyWindowBenchSample) * kDirtyWindowBenchTargetSamples;
    dirtyWindowBenchSamples_ = static_cast<DirtyWindowBenchSample*>(
        heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (dirtyWindowBenchSamples_ == nullptr) return;
  }
  if (dirtyWindowBenchSampleCount_ >= kDirtyWindowBenchTargetSamples) {
    saveDirtyWindowBenchmark();
    return;
  }

  DirtyWindowBenchSample& s = dirtyWindowBenchSamples_[dirtyWindowBenchSampleCount_++];
  s.frame = dirtyWindowBenchFrame_;
  s.x = x;
  s.y = y;
  s.w = w;
  s.h = h;
  s.bboxPixels = static_cast<uint32_t>(w) * h;
  s.changedPixels = changedPixels;
  s.whiteToBlack = whiteToBlack;
  s.blackToWhite = blackToWhite;
  s.refreshUs = refreshUs;
  s.frameCycleUs = frameCycleUs;

  if (dirtyWindowBenchSampleCount_ >= kDirtyWindowBenchTargetSamples) saveDirtyWindowBenchmark();
}

void MissileCommandActivity::releaseWindowShadow() {
  // Persist a partial run too; saveDirtyWindowBenchmark() is a no-op after the
  // normal 200-sample flush.
  saveDirtyWindowBenchmark();
  if (dirtyWindowBenchSamples_ != nullptr) {
    heap_caps_free(dirtyWindowBenchSamples_);
    dirtyWindowBenchSamples_ = nullptr;
  }
  if (windowShadow_ != nullptr) {
    heap_caps_free(windowShadow_);
    windowShadow_ = nullptr;
  }
  windowShadowValid_ = false;
}
'''
replace_once(MISSILE_CPP, old_release, new_release_and_bench)

old_scan = r'''  uint16_t minByte = wb;
  uint16_t maxByte = 0;
  uint16_t minY = panelH;
  uint16_t maxY = 0;
  bool changed = false;

  for (uint16_t y = 0; y < panelH; ++y) {
    const uint32_t rowOffset = static_cast<uint32_t>(y) * wb;
    for (uint16_t bx = 0; bx < wb; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      changed = true;
      if (bx < minByte) minByte = bx;
      if (bx > maxByte) maxByte = bx;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  if (!changed) return;

  const uint16_t x = static_cast<uint16_t>(minByte * 8);
  const uint16_t y = minY;
  const uint16_t w = static_cast<uint16_t>((maxByte - minByte + 1) * 8);
  const uint16_t h = static_cast<uint16_t>(maxY - minY + 1);

  display.displayWindow(x, y, w, h, false);
'''
new_scan = r'''  const int64_t benchFrameStartUs = esp_timer_get_time();
  ++dirtyWindowBenchFrame_;
  uint32_t frameCycleUs = 0;
  if (dirtyWindowBenchLastFrameUs_ != 0) {
    const int64_t rawCycleUs = benchFrameStartUs - dirtyWindowBenchLastFrameUs_;
    if (rawCycleUs > 0 && rawCycleUs <= 0xFFFFFFFFLL) frameCycleUs = static_cast<uint32_t>(rawCycleUs);
  }
  dirtyWindowBenchLastFrameUs_ = benchFrameStartUs;

  uint16_t minByte = wb;
  uint16_t maxByte = 0;
  uint16_t minY = panelH;
  uint16_t maxY = 0;
  uint32_t changedPixels = 0;
  uint32_t whiteToBlack = 0;
  uint32_t blackToWhite = 0;
  bool changed = false;

  for (uint16_t y = 0; y < panelH; ++y) {
    const uint32_t rowOffset = static_cast<uint32_t>(y) * wb;
    for (uint16_t bx = 0; bx < wb; ++bx) {
      const uint32_t offset = rowOffset + bx;
      const uint8_t oldByte = windowShadow_[offset];
      const uint8_t newByte = fb[offset];
      const uint8_t diff = static_cast<uint8_t>(oldByte ^ newByte);
      if (diff == 0) continue;

      changed = true;
      changedPixels += static_cast<uint32_t>(__builtin_popcount(static_cast<unsigned>(diff)));
      // Framebuffer convention is 1=white, 0=black.
      whiteToBlack +=
          static_cast<uint32_t>(__builtin_popcount(static_cast<unsigned>(static_cast<uint8_t>(oldByte & diff))));
      blackToWhite +=
          static_cast<uint32_t>(__builtin_popcount(static_cast<unsigned>(static_cast<uint8_t>(newByte & diff))));
      if (bx < minByte) minByte = bx;
      if (bx > maxByte) maxByte = bx;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  if (!changed) return;

  const uint16_t x = static_cast<uint16_t>(minByte * 8);
  const uint16_t y = minY;
  const uint16_t w = static_cast<uint16_t>((maxByte - minByte + 1) * 8);
  const uint16_t h = static_cast<uint16_t>(maxY - minY + 1);

  const int64_t refreshStartUs = esp_timer_get_time();
  display.displayWindowAtSpiHz(x, y, w, h, MISSILE_WINDOW_SPI_HZ, false);
  const int64_t rawRefreshUs = esp_timer_get_time() - refreshStartUs;
  const uint32_t refreshUs = rawRefreshUs > 0 && rawRefreshUs <= 0xFFFFFFFFLL
                                 ? static_cast<uint32_t>(rawRefreshUs)
                                 : 0;

  appendDirtyWindowBenchSample(x, y, w, h, changedPixels, whiteToBlack, blackToWhite, refreshUs, frameCycleUs);
'''
replace_once(MISSILE_CPP, old_scan, new_scan)

print("Hybrid-A Missile-only SPI30 + frame-by-frame dirty-window benchmark applied")
