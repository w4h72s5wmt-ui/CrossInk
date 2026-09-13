from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# CrossInk bridge: expose the SDK's existing displayWindow() primitive through
# HalDisplay. No refresh policy lives here; it is only a locked passthrough.
# ---------------------------------------------------------------------------
replace_once(
    "lib/hal/HalDisplay.h",
    "  void displayBuffer(RefreshMode mode = RefreshMode::FAST_REFRESH, bool turnOffScreen = false);\n",
    "  void displayBuffer(RefreshMode mode = RefreshMode::FAST_REFRESH, bool turnOffScreen = false);\n"
    "  // Experimental UC8279 window path: physical panel coordinates, byte-aligned X.\n"
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n",
)

replace_once(
    "lib/hal/HalDisplay.cpp",
    "void HalDisplay::setInverted(bool inverted) {\n",
    "void HalDisplay::displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen) {\n"
    "  HalSpiBus::Lock spiLock;\n"
    "  einkDisplay.displayWindow(x, y, w, h, turnOffScreen);\n"
    "}\n\n"
    "void HalDisplay::setInverted(bool inverted) {\n",
)


# ---------------------------------------------------------------------------
# UC8279 X4 driver: genuine windowed DTM traffic.
#
# Safety boundary for this experiment:
#   * no LUT changes
#   * no voltage changes
#   * no PLL/TSSET/CDI changes
#   * normal display()/displayStart()/displayFinish() are untouched
# Only displayWindow() opts into this path.
# ---------------------------------------------------------------------------
replace_once(
    "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.h",
    "  void displayFinish(EpdBus& bus, const uint8_t* fb) override;\n"
    "  bool supportsAsyncDisplay() const override { return true; }\n",
    "  void displayFinish(EpdBus& bus, const uint8_t* fb) override;\n"
    "  void displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y,\n"
    "                     uint16_t w, uint16_t h, bool turnOff) override;\n"
    "  bool supportsAsyncDisplay() const override { return true; }\n",
)

replace_once(
    "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.h",
    "  void streamPlane(EpdBus& bus, uint8_t ramCmd, const uint8_t* fb, bool invert = false);\n",
    "  void streamPlane(EpdBus& bus, uint8_t ramCmd, const uint8_t* fb, bool invert = false);\n"
    "  // Stream only the currently selected PTL rectangle. x/w are visible-panel\n"
    "  // coordinates and must be byte aligned. Partial mode/window must already\n"
    "  // be active before this is called.\n"
    "  void streamWindowPlane(EpdBus& bus, uint8_t ramCmd, const uint8_t* fb, uint16_t x, uint16_t y,\n"
    "                         uint16_t w, uint16_t h, bool invert = false);\n",
)

window_stream_impl = r'''
void Uc8279X4Driver::streamWindowPlane(EpdBus& bus, uint8_t ramCmd, const uint8_t* fb, uint16_t x, uint16_t y,
                                       uint16_t w, uint16_t h, bool invert) {
  if (!fb || w == 0 || h == 0 || (x & 0x07) != 0 || (w & 0x07) != 0) return;
  const uint16_t windowBytes = static_cast<uint16_t>(w / 8);
  uint8_t row[128];
  if (windowBytes > sizeof(row)) return;

  static const uint8_t kBitRev[16] = {0x0, 0x8, 0x4, 0xC, 0x2, 0xA, 0x6, 0xE,
                                      0x1, 0x9, 0x5, 0xD, 0x3, 0xB, 0x7, 0xF};
  bus.cmd(ramCmd);
  for (uint16_t n = 0; n < h; ++n) {
    const uint16_t srcY = FREEINK_UC8279X4_ROWREV ? static_cast<uint16_t>(y + h - 1 - n)
                                                   : static_cast<uint16_t>(y + n);
    const uint8_t* src = fb + static_cast<uint32_t>(srcY) * _wb + x / 8;

    if (!FREEINK_UC8279X4_XMIRROR && !invert) {
      bus.data(src, windowBytes);
      continue;
    }

    for (uint16_t i = 0; i < windowBytes; ++i) {
      uint8_t b;
      if (FREEINK_UC8279X4_XMIRROR) {
        const uint8_t m = src[windowBytes - 1 - i];
        b = static_cast<uint8_t>((kBitRev[m & 0x0F] << 4) | kBitRev[m >> 4]);
      } else {
        b = src[i];
      }
      row[i] = invert ? static_cast<uint8_t>(~b) : b;
    }
    bus.data(row, windowBytes);
  }
}

'''
replace_once(
    "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp",
    "// Same geometry/mirroring as streamPlane, but each visible byte is lhs ^ rhs.\n",
    window_stream_impl + "// Same geometry/mirroring as streamPlane, but each visible byte is lhs ^ rhs.\n",
)

window_impl = r'''
void Uc8279X4Driver::displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y,
                                   uint16_t w, uint16_t h, bool turnOff) {
  if (!fb || w == 0 || h == 0 || x + w > _w || y + h > _h) return;
  if ((x & 0x07) != 0 || (w & 0x07) != 0) return;

  // A differential window requires a known OLD plane. First paint after boot,
  // resync, or grayscale therefore stays on the proven ordinary path.
  if (_needFullClear || !_oldPlaneValid || _redriveAfterGray) {
    display(bus, fb, prev, RefreshMode::Fast, turnOff);
    return;
  }

  _grayBaseValid = false;
  _absoluteGrayPlanes = false;
  if (_grayBase != nullptr) {
    memcpy(_grayBase, fb, _bufferSize);
    _grayBaseValid = true;
  }

  uint16_t xStart = x;
  uint16_t xEnd = static_cast<uint16_t>(x + w - 1);
  uint16_t yStartVisible = y;
  uint16_t yEndVisible = static_cast<uint16_t>(y + h - 1);
#if FREEINK_UC8279X4_XMIRROR
  xStart = static_cast<uint16_t>(_w - (x + w));
  xEnd = static_cast<uint16_t>(_w - 1 - x);
#endif
#if FREEINK_UC8279X4_ROWREV
  yStartVisible = static_cast<uint16_t>(_h - (y + h));
  yEndVisible = static_cast<uint16_t>(_h - 1 - y);
#endif
  const uint16_t yStart = static_cast<uint16_t>(_cfg.gateOffset + yStartVisible);
  const uint16_t yEnd = static_cast<uint16_t>(_cfg.gateOffset + yEndVisible);

  // UC81xx partial-data contract: enter partial mode and define PTL before the
  // DTM payload so the controller consumes only w/8 * h bytes for each plane.
  bus.cmd(CMD_PARTIAL_IN);
  bus.cmd(CMD_PARTIAL_WINDOW);
  bus.data(static_cast<uint8_t>(xStart >> 8));
  bus.data(static_cast<uint8_t>(xStart & 0xF8));
  bus.data(static_cast<uint8_t>(xEnd >> 8));
  bus.data(static_cast<uint8_t>(xEnd | 0x07));
  bus.data(static_cast<uint8_t>(yStart >> 8));
  bus.data(static_cast<uint8_t>(yStart & 0xFF));
  bus.data(static_cast<uint8_t>(yEnd >> 8));
  bus.data(static_cast<uint8_t>(yEnd & 0xFF));
  bus.data(0x01);

  // Dual-buffer callers may supply an explicit OLD plane. Single-buffer X4 Pro
  // leaves DTM1 resident in controller RAM from the previous update.
  if (prev != nullptr) streamWindowPlane(bus, CMD_DTM1, prev, x, y, w, h);
  streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);

  // Same known-good fast settings as the stock full-surface DU path.
  bus.cmd(CMD_VCOM_DATA_INTERVAL);
  bus.data(_cfg.cdiBwFast);
  bus.cmd(CMD_CCSET);
  bus.data(_cfg.ccset);
  bus.cmd(CMD_TSSET);
  bus.data(_cfg.tssetFast);
  bus.cmd(CMD_PFS);
  bus.data(_cfg.pfs);
  bus.cmd(CMD_GATE_SCAN);
  bus.data(_cfg.gateScan);

  powerOnIfNeeded(bus, " 8279x4_win_PON");
  bus.cmd(CMD_PANEL_SETTING);
  bus.data(static_cast<uint8_t>(_cfg.psr0 & 0xDF));
  bus.data(_cfg.psr1);
  bus.cmd(CMD_DISPLAY_REFRESH);
  {
    const int8_t busyPin = bus.pins().busy;
    const unsigned long t0 = millis();
    while (digitalRead(busyPin) == HIGH && millis() - t0 < 50) delay(1);
  }
  bus.waitRefreshComplete(" 8279x4_window_DRF");

  // Keep DTM1 synchronized only inside the region that actually changed. Pixels
  // outside PTL were not refreshed and their OLD data remains authoritative.
  streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h);
  bus.cmd(CMD_PARTIAL_OUT);
  _oldPlaneValid = true;
  _needFullClear = false;

  if (turnOff) {
    bus.cmd(CMD_POWER_OFF);
    bus.waitBusy(" 8279x4_window_POF");
    _isScreenOn = false;
  }
}

'''
replace_once(
    "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp",
    "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n",
    window_impl + "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n",
)


# ---------------------------------------------------------------------------
# Missile Command Stage-B integration.
#
# The app keeps a 48 KB PSRAM copy of the last displayed framebuffer. After
# composing the next synchronized game frame it byte-compares the two buffers,
# derives one exact byte-aligned dirty rectangle, and calls displayWindow().
# No simulation step runs ahead of the blocking physical update.
# ---------------------------------------------------------------------------
replace_once(
    "src/activities/home/MissileCommandActivity.h",
    "  bool sceneNeedsFullRedraw_ = true;\n",
    "  bool sceneNeedsFullRedraw_ = true;\n"
    "  uint8_t* windowShadow_ = nullptr;\n"
    "  bool windowShadowValid_ = false;\n",
)
replace_once(
    "src/activities/home/MissileCommandActivity.h",
    "  void drawPlayingFrame();\n",
    "  void drawPlayingFrame();\n"
    "  void refreshPlayingWindow(bool forceFullRefresh);\n"
    "  void releaseWindowShadow();\n",
)

replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "#include <GfxRenderer.h>\n",
    "#include <GfxRenderer.h>\n#include <HalDisplay.h>\n#include <esp_heap_caps.h>\n",
)
replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "#include <cstdio>\n",
    "#include <cstdio>\n#include <cstring>\n",
)
replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "constexpr const char SCORE_PATH[] = \"/.crosspoint/missile-command-score.bin\";\n",
    "constexpr const char SCORE_PATH[] = \"/.crosspoint/missile-command-score.bin\";\n"
    "constexpr const char WINDOW_BENCH_PATH[] = \"/missile-command-window-stage2.csv\";\n",
)

bench_fn = r'''
void runUc8279WindowBenchmark() {
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE-WINDOW2", WINDOW_BENCH_PATH, file)) return;

  const char header[] = "window_w,window_h,window_pixels,screen_pct_x100,pass,refresh_us\n";
  file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);

  uint8_t* const fb = display.getFrameBuffer();
  const uint16_t panelW = display.getDisplayWidth();
  const uint16_t panelH = display.getDisplayHeight();
  const uint16_t wb = display.getDisplayWidthBytes();
  if (!fb || panelW < 32 || panelH < 32 || wb == 0) {
    file.close();
    return;
  }

  constexpr uint16_t markerW = 16;
  constexpr uint16_t markerH = 16;
  const uint16_t markerX = static_cast<uint16_t>(((panelW - markerW) / 2) & ~0x07u);
  const uint16_t markerY = static_cast<uint16_t>((panelH - markerH) / 2);
  const auto toggleMarker = [&]() {
    for (uint16_t row = 0; row < markerH; ++row) {
      uint8_t* p = fb + static_cast<uint32_t>(markerY + row) * wb + markerX / 8;
      for (uint16_t b = 0; b < markerW / 8; ++b) p[b] ^= 0xFF;
    }
  };

  struct WindowSize { uint16_t w; uint16_t h; };
  const WindowSize tests[] = {
      {32, 32}, {64, 64}, {128, 64}, {128, 128}, {256, 128}, {400, 240}, {800, 480},
  };
  const uint32_t screenPixels = static_cast<uint32_t>(panelW) * panelH;

  for (const auto& test : tests) {
    if (test.w > panelW || test.h > panelH) continue;
    const uint16_t x = static_cast<uint16_t>(((panelW - test.w) / 2) & ~0x07u);
    const uint16_t y = static_cast<uint16_t>((panelH - test.h) / 2);
    for (uint8_t pass = 1; pass <= 2; ++pass) {
      toggleMarker();
      const uint32_t t0 = micros();
      display.displayWindow(x, y, test.w, test.h, false);
      const uint32_t elapsed = micros() - t0;
      const uint32_t pixels = static_cast<uint32_t>(test.w) * test.h;
      const uint32_t pctX100 = screenPixels ? static_cast<uint32_t>((static_cast<uint64_t>(pixels) * 10000ULL) / screenPixels) : 0;
      char line[128];
      const int n = std::snprintf(line, sizeof(line), "%u,%u,%lu,%lu,%u,%lu\n",
                                  static_cast<unsigned>(test.w), static_cast<unsigned>(test.h),
                                  static_cast<unsigned long>(pixels), static_cast<unsigned long>(pctX100),
                                  static_cast<unsigned>(pass), static_cast<unsigned long>(elapsed));
      if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
    }
  }
  file.close();
}

'''
replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "}  // namespace\n\nMissileCommandActivity::MissileCommandActivity",
    bench_fn + "}  // namespace\n\nMissileCommandActivity::MissileCommandActivity",
)

replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "void MissileCommandActivity::onExit() {\n  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n  saveHighScore();\n  Activity::onExit();\n}\n",
    "void MissileCommandActivity::onExit() {\n"
    "  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n"
    "  saveHighScore();\n"
    "  releaseWindowShadow();\n"
    "  Activity::onExit();\n"
    "}\n",
)

refresh_impl = r'''
void MissileCommandActivity::releaseWindowShadow() {
  if (windowShadow_ != nullptr) {
    heap_caps_free(windowShadow_);
    windowShadow_ = nullptr;
  }
  windowShadowValid_ = false;
}

void MissileCommandActivity::refreshPlayingWindow(bool forceFullRefresh) {
  uint8_t* const fb = display.getFrameBuffer();
  const uint32_t bufferSize = display.getBufferSize();
  const uint16_t panelW = display.getDisplayWidth();
  const uint16_t panelH = display.getDisplayHeight();
  const uint16_t wb = display.getDisplayWidthBytes();

  if (!fb || bufferSize == 0 || wb == 0) {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    windowShadowValid_ = false;
    return;
  }

  if (windowShadow_ == nullptr) {
    windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    windowShadowValid_ = false;
  }

  if (forceFullRefresh || windowShadow_ == nullptr || !windowShadowValid_) {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    if (windowShadow_ != nullptr) {
      memcpy(windowShadow_, fb, bufferSize);
      windowShadowValid_ = true;
    }
    return;
  }

  uint16_t minByte = wb;
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

  const uint16_t copyBytes = static_cast<uint16_t>(w / 8);
  for (uint16_t row = 0; row < h; ++row) {
    const uint32_t offset = static_cast<uint32_t>(y + row) * wb + minByte;
    memcpy(windowShadow_ + offset, fb + offset, copyBytes);
  }
}

'''
replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "void MissileCommandActivity::renderPlaying() {\n",
    refresh_impl + "void MissileCommandActivity::renderPlaying() {\n",
)

replace_once(
    "src/activities/home/MissileCommandActivity.cpp",
    "void MissileCommandActivity::renderPlaying() {\n"
    "  if (sceneNeedsFullRedraw_) drawFullPlayingScene();\n"
    "  drawPlayingFrame();\n\n"
    "  // Blocking FAST refresh is deliberate: the next simulation/input cycle cannot\n"
    "  // begin until this exact synchronized frame has completed on the panel.\n"
    "  renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "  cycleRenderPending_.store(false);\n"
    "}\n",
    "void MissileCommandActivity::renderPlaying() {\n"
    "  const bool forceFullRefresh = sceneNeedsFullRedraw_ || !windowShadowValid_;\n"
    "  if (sceneNeedsFullRedraw_) drawFullPlayingScene();\n"
    "  drawPlayingFrame();\n\n"
    "  // First frame establishes a complete controller baseline. Then one exact\n"
    "  // dirty rectangle is refreshed per synchronized game step. The call is\n"
    "  // blocking, so input/simulation still cannot outrun the physical panel.\n"
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    static bool windowBenchmarkDone = false;\n"
    "    if (!windowBenchmarkDone) {\n"
    "      windowBenchmarkDone = true;\n"
    "      runUc8279WindowBenchmark();\n"
    "      lastCycleUs_ = esp_timer_get_time();\n"
    "    }\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n"
    "    const uint32_t bufferSize = display.getBufferSize();\n"
    "    if (windowShadow_ == nullptr && bufferSize != 0) {\n"
    "      windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));\n"
    "    }\n"
    "    if (windowShadow_ != nullptr && fb != nullptr && bufferSize != 0) {\n"
    "      memcpy(windowShadow_, fb, bufferSize);\n"
    "      windowShadowValid_ = true;\n"
    "    }\n"
    "  } else {\n"
    "    refreshPlayingWindow(false);\n"
    "  }\n"
    "  cycleRenderPending_.store(false);\n"
    "}\n",
)

print("UC8279 Stage-B window transfers + dirty Missile refresh applied")
