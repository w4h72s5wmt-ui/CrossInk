from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:220]!r}")
    p.write_text(text.replace(old, new, 1))


HAL_H = "lib/hal/HalDisplay.h"
HAL_CPP = "lib/hal/HalDisplay.cpp"
FACADE_H = "freeink-sdk/libs/display/FreeInkDisplay/include/FreeInkDisplay.h"
FACADE_CPP = "freeink-sdk/libs/display/FreeInkDisplay/src/FreeInkDisplay.cpp"
PANEL_H = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/PanelDriver.h"
DRIVER_H = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.h"
DRIVER_CPP = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
MISSILE_H = "src/activities/home/MissileCommandActivity.h"
MISSILE_CPP = "src/activities/home/MissileCommandActivity.cpp"

# ---------------------------------------------------------------------------
# Sparse-DTM experiment, applied after Stage-B + timing + Hybrid-A + A2-Lite +
# PLL0F. It preserves the validated waveform and one-DRF cadence. Only RAM
# writes become tiled when the changed pixels are sparse inside the global bbox.
# ---------------------------------------------------------------------------

# Generic driver fallback: panels other than UC8279 simply execute the ordinary
# bbox displayWindow path.
replace_once(
    PANEL_H,
    "  virtual void displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y, uint16_t w,\n"
    "                             uint16_t h, bool turnOff) {\n"
    "    display(bus, fb, prev, RefreshMode::Fast, turnOff);\n"
    "  }\n",
    "  virtual void displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y, uint16_t w,\n"
    "                             uint16_t h, bool turnOff) {\n"
    "    display(bus, fb, prev, RefreshMode::Fast, turnOff);\n"
    "  }\n"
    "  virtual void displaySparseWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, const uint8_t* tileMask,\n"
    "                                   uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,\n"
    "                                   uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH, bool turnOff) {\n"
    "    (void)tileMask; (void)tileCols; (void)tileRows; (void)tileW; (void)tileH;\n"
    "    displayWindow(bus, fb, prev, bboxX, bboxY, bboxW, bboxH, turnOff);\n"
    "  }\n",
)

# FreeInk facade.
replace_once(
    FACADE_H,
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n",
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n"
    "  void displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,\n"
    "                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH,\n"
    "                           bool turnOffScreen = false);\n",
)

facade_impl = r'''
void FreeInkDisplay::displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows,
                                         uint16_t tileW, uint16_t tileH, uint16_t bboxX, uint16_t bboxY,
                                         uint16_t bboxW, uint16_t bboxH, bool turnOffScreen) {
  cancelGrayscalePass();
  if (_inverted || _inversionDirty) {
    displayBuffer(FAST_REFRESH, turnOffScreen);
    return;
  }
  syncPendingAsync();
#ifdef EINK_DISPLAY_SINGLE_BUFFER_MODE
  _driver->displaySparseWindow(_bus, frameBuffer, nullptr, tileMask, tileCols, tileRows, tileW, tileH,
                               bboxX, bboxY, bboxW, bboxH, turnOffScreen);
  _shadowValid = false;
#else
  _driver->displaySparseWindow(_bus, frameBuffer, frameBufferActive, tileMask, tileCols, tileRows, tileW, tileH,
                               bboxX, bboxY, bboxW, bboxH, turnOffScreen);
#endif
}

'''
replace_once(FACADE_CPP,
             "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n",
             facade_impl + "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n")

# HAL passthrough under the same SPI lock as displayWindow.
replace_once(
    HAL_H,
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n",
    "  void displayWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);\n"
    "  void displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,\n"
    "                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH,\n"
    "                           bool turnOffScreen = false);\n",
)
replace_once(
    HAL_CPP,
    "void HalDisplay::setInverted(bool inverted) {\n",
    "void HalDisplay::displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows,\n"
    "                                     uint16_t tileW, uint16_t tileH, uint16_t bboxX, uint16_t bboxY,\n"
    "                                     uint16_t bboxW, uint16_t bboxH, bool turnOffScreen) {\n"
    "  HalSpiBus::Lock spiLock;\n"
    "  einkDisplay.displaySparseWindow(tileMask, tileCols, tileRows, tileW, tileH, bboxX, bboxY, bboxW, bboxH,\n"
    "                                  turnOffScreen);\n"
    "}\n\n"
    "void HalDisplay::setInverted(bool inverted) {\n",
)

# UC8279 override.
replace_once(
    DRIVER_H,
    "  void displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y,\n"
    "                     uint16_t w, uint16_t h, bool turnOff) override;\n",
    "  void displayWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, uint16_t x, uint16_t y,\n"
    "                     uint16_t w, uint16_t h, bool turnOff) override;\n"
    "  void displaySparseWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, const uint8_t* tileMask,\n"
    "                           uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,\n"
    "                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH, bool turnOff) override;\n",
)

sparse_impl = r'''
void Uc8279X4Driver::displaySparseWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev,
                                         const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows,
                                         uint16_t tileW, uint16_t tileH, uint16_t bboxX, uint16_t bboxY,
                                         uint16_t bboxW, uint16_t bboxH, bool turnOff) {
  if (!fb || !tileMask || tileCols == 0 || tileRows == 0 || tileW == 0 || tileH == 0 ||
      (tileW & 0x07) != 0 || bboxW == 0 || bboxH == 0 || (bboxX & 0x07) != 0 || (bboxW & 0x07) != 0 ||
      bboxX + bboxW > _w || bboxY + bboxH > _h) {
    displayWindow(bus, fb, prev, bboxX, bboxY, bboxW, bboxH, turnOff);
    return;
  }

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

  const auto setWindow = [&](uint16_t x, uint16_t y, uint16_t w, uint16_t h) {
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
  };

  bus.cmd(CMD_PARTIAL_IN);

  // DTM1 and DTM2 are kept equal to the displayed frame after every successful
  // update. Therefore pixels not rewritten here remain a valid no-transition
  // baseline even when they lie inside the final DRF bbox.
  uint16_t dirtyCount = 0;
  for (uint16_t ty = 0; ty < tileRows; ++ty) {
    for (uint16_t tx = 0; tx < tileCols; ++tx) {
      const uint32_t bit = static_cast<uint32_t>(ty) * tileCols + tx;
      if ((tileMask[bit >> 3] & static_cast<uint8_t>(1u << (bit & 7))) == 0) continue;
      const uint16_t x = static_cast<uint16_t>(tx * tileW);
      const uint16_t y = static_cast<uint16_t>(ty * tileH);
      if (x >= _w || y >= _h) continue;
      const uint16_t w = static_cast<uint16_t>(min<uint32_t>(tileW, _w - x));
      const uint16_t h = static_cast<uint16_t>(min<uint32_t>(tileH, _h - y));
      if ((w & 0x07) != 0) continue;
      setWindow(x, y, w, h);
      if (prev != nullptr) streamWindowPlane(bus, CMD_DTM1, prev, x, y, w, h);
      streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);
      ++dirtyCount;
    }
  }

  if (dirtyCount == 0) {
    bus.cmd(CMD_PARTIAL_OUT);
    return;
  }

  // One DRF only: last PTL becomes the physical scan bbox; RAM upload itself was sparse.
  setWindow(bboxX, bboxY, bboxW, bboxH);

  uint8_t hybridLuts[5][PREBW_LUT_LEN];
  buildMissileGameA2LitePreBw(hybridLuts);
  bus.cmd(CMD_PANEL_SETTING);
  bus.data(_cfg.psr0);
  bus.data(_cfg.psr1);
  bus.cmd(CMD_PFS);
  bus.data(_cfg.pfs);
  bus.cmd(CMD_GATE_SCAN);
  bus.data(_cfg.gateScan);
  bus.cmd(CMD_VCOM_DATA_INTERVAL);
  bus.data(_cfg.cdiBwFast);
  bus.cmd(CMD_CCSET);
  bus.data(_cfg.ccset);
  bus.cmd(CMD_TSSET);
  bus.data(_cfg.tssetFast);
  for (uint8_t t = 0; t < 5; ++t) {
    bus.cmd(kXtfPreBwMid[t][0]);
    bus.data(hybridLuts[t], PREBW_LUT_LEN);
  }

  bus.cmd(CMD_PLL);
  bus.data(0x0F);
  powerOnIfNeeded(bus, " 8279x4_sparse_gameA2Lite_pll0f_PON");
  bus.cmd(CMD_DISPLAY_REFRESH);
  {
    const int8_t busyPin = bus.pins().busy;
    const unsigned long t0 = millis();
    while (digitalRead(busyPin) == HIGH && millis() - t0 < 50) delay(1);
  }
  bus.waitRefreshComplete(" 8279x4_sparse_gameA2Lite_pll0f_DRF");
  bus.cmd(CMD_PLL);
  bus.data(_cfg.pll);

  // Re-establish the global invariant only for tiles that actually changed.
  for (uint16_t ty = 0; ty < tileRows; ++ty) {
    for (uint16_t tx = 0; tx < tileCols; ++tx) {
      const uint32_t bit = static_cast<uint32_t>(ty) * tileCols + tx;
      if ((tileMask[bit >> 3] & static_cast<uint8_t>(1u << (bit & 7))) == 0) continue;
      const uint16_t x = static_cast<uint16_t>(tx * tileW);
      const uint16_t y = static_cast<uint16_t>(ty * tileH);
      if (x >= _w || y >= _h) continue;
      const uint16_t w = static_cast<uint16_t>(min<uint32_t>(tileW, _w - x));
      const uint16_t h = static_cast<uint16_t>(min<uint32_t>(tileH, _h - y));
      if ((w & 0x07) != 0) continue;
      setWindow(x, y, w, h);
      streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h);
    }
  }

  bus.cmd(CMD_PARTIAL_OUT);
  _oldPlaneValid = true;
  _needFullClear = false;

  if (turnOff) {
    bus.cmd(CMD_POWER_OFF);
    bus.waitBusy(" 8279x4_sparse_POF");
    _isScreenOn = false;
  }
}

'''
replace_once(DRIVER_CPP,
             "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n",
             sparse_impl + "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n")

# ---------------------------------------------------------------------------
# Missile: 32x16 dirty tile map. Use sparse upload only when payload savings are
# meaningful; otherwise retain the validated bbox displayWindow path.
# ---------------------------------------------------------------------------
replace_once(MISSILE_H,
             "  bool waveScrubPending_ = false;\n",
             "  bool waveScrubPending_ = false;\n  bool menuScrubPending_ = false;\n")

# Fresh activity entry is not a return from gameplay.
replace_once(MISSILE_CPP,
             "  sceneNeedsFullRedraw_ = true;\n  cycleRenderPending_.store(false);\n",
             "  sceneNeedsFullRedraw_ = true;\n  menuScrubPending_ = false;\n  cycleRenderPending_.store(false);\n")

# Back/game-over -> menu gets a one-shot stock HALF clean while drawing the menu.
replace_once(MISSILE_CPP,
             "  viewMode_ = ViewMode::Menu;\n  selectedIndex_ = difficulty_;\n",
             "  viewMode_ = ViewMode::Menu;\n  menuScrubPending_ = true;\n  selectedIndex_ = difficulty_;\n")
replace_once(MISSILE_CPP,
             "  renderer.displayBuffer();\n}\n\nvoid MissileCommandActivity::drawFullPlayingScene() {\n",
             "  if (menuScrubPending_) {\n"
             "    renderer.displayBuffer(HalDisplay::HALF_REFRESH);\n"
             "    menuScrubPending_ = false;\n"
             "  } else {\n"
             "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
             "  }\n"
             "}\n\nvoid MissileCommandActivity::drawFullPlayingScene() {\n")

old_dirty = r'''  display.displayWindow(x, y, w, h, false);

  const uint16_t copyBytes = static_cast<uint16_t>(w / 8);
'''
new_dirty = r'''  constexpr uint16_t TILE_W = 32;
  constexpr uint16_t TILE_H = 16;
  constexpr uint16_t TILE_COLS = (HalDisplay::DISPLAY_WIDTH + TILE_W - 1) / TILE_W;
  constexpr uint16_t TILE_ROWS = (HalDisplay::DISPLAY_HEIGHT + TILE_H - 1) / TILE_H;
  constexpr uint16_t TILE_COUNT = TILE_COLS * TILE_ROWS;
  constexpr uint16_t TILE_MASK_BYTES = (TILE_COUNT + 7) / 8;
  std::array<uint8_t, TILE_MASK_BYTES> tileMask{};
  uint16_t dirtyTiles = 0;

  for (uint16_t row = minY; row <= maxY; ++row) {
    const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
    for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
      const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
      const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
      const uint8_t mask = static_cast<uint8_t>(1u << (bit & 7));
      if ((tileMask[bit >> 3] & mask) == 0) {
        tileMask[bit >> 3] |= mask;
        ++dirtyTiles;
      }
    }
  }

  const uint32_t bboxPayload = static_cast<uint32_t>(w / 8) * h;
  const uint32_t sparsePayload = static_cast<uint32_t>(dirtyTiles) * (TILE_W / 8) * TILE_H;
  // PTL command overhead is tiny, but don't fragment dense frames. Require at
  // least 30% RAM-byte savings and cap the number of small windows.
  const bool useSparse = dirtyTiles > 0 && dirtyTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
  if (useSparse) {
    display.displaySparseWindow(tileMask.data(), TILE_COLS, TILE_ROWS, TILE_W, TILE_H, x, y, w, h, false);
  } else {
    display.displayWindow(x, y, w, h, false);
  }

  const uint16_t copyBytes = static_cast<uint16_t>(w / 8);
'''
replace_once(MISSILE_CPP, old_dirty, new_dirty)

# Separate benchmark identity.
replace_once(MISSILE_CPP,
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-wave-scrub-bench.csv";',
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-wave-scrub-bench.csv";')
replace_once(MISSILE_CPP,
             'Storage.openFileForWrite("MISSILE-A2-LITE-PLL0F", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-LITE-SPARSE", BENCH_PATH, file)')
replace_once(MISSILE_CPP,
             'const char started[] = "game-a2-lite-pll0f-wave-scrub-started,0,0,0,0,0\\n";',
             'const char started[] = "game-a2-lite-pll0f-sparse-wave-scrub-started,0,0,0,0,0\\n";')
replace_once(MISSILE_CPP,
             'Storage.openFileForWrite("MISSILE-A2-LITE-PLL0F", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-LITE-SPARSE", BENCH_PATH, file)')
replace_once(MISSILE_CPP,
             '"game-a2-lite-pll0f-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",',
             '"game-a2-lite-pll0f-sparse-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",')

print("UC8279 Missile A2-Lite PLL0F sparse-DTM + menu HALF scrub applied")
