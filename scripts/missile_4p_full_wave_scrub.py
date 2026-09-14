from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:260]!r}")
    p.write_text(text.replace(old, new, 1))


PANEL_H = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/PanelDriver.h"
FACADE_H = "freeink-sdk/libs/display/FreeInkDisplay/include/FreeInkDisplay.h"
FACADE_CPP = "freeink-sdk/libs/display/FreeInkDisplay/src/FreeInkDisplay.cpp"
HAL_H = "lib/hal/HalDisplay.h"
HAL_CPP = "lib/hal/HalDisplay.cpp"
DRIVER_H = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.h"
DRIVER_CPP = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
MISSILE_CPP = "src/activities/home/MissileCommandActivity.cpp"

# ---------------------------------------------------------------------------
# Coherent wave scrub experiment.
#
# Unlike LocalScrub, this always refreshes the ENTIRE panel in one physical DRF
# at the wave boundary. DTM1 is seeded with complement(target), which forces every
# pixel through BW or WB on the existing 4P waveform, then the validated window
# path resyncs DTM1=target. There is no deferred header/status cleanup and no
# follow-up dirty rectangle belonging to the scrub itself.
# ---------------------------------------------------------------------------

panel_anchor = r'''  virtual void displaySparseWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, const uint8_t* tileMask,
                                   uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,
                                   uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH, bool turnOff) {
    (void)tileMask; (void)tileCols; (void)tileRows; (void)tileW; (void)tileH;
    displayWindow(bus, fb, prev, bboxX, bboxY, bboxW, bboxH, turnOff);
  }
'''
panel_new = panel_anchor + r'''  virtual void displayScrubWindow(EpdBus& bus, const uint8_t* fb, uint16_t x, uint16_t y,
                                  uint16_t w, uint16_t h, bool turnOff) {
    displayWindow(bus, fb, nullptr, x, y, w, h, turnOff);
  }
'''
replace_once(PANEL_H, panel_anchor, panel_new)

facade_decl = r'''  void displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,
                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH,
                           bool turnOffScreen = false);
'''
replace_once(
    FACADE_H,
    facade_decl,
    facade_decl + r'''  void displayScrubWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);
''',
)

facade_impl = r'''void FreeInkDisplay::displayScrubWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h,
                                        bool turnOffScreen) {
  if (_inverted || _inversionDirty) {
    displayBuffer(HALF_REFRESH, turnOffScreen);
    return;
  }
  syncPendingAsync();
  _driver->displayScrubWindow(_bus, frameBuffer, x, y, w, h, turnOffScreen);
  _shadowValid = false;
}

'''
replace_once(
    FACADE_CPP,
    "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n",
    facade_impl + "void FreeInkDisplay::displayGrayBuffer(bool turnOffScreen, const unsigned char* lut, bool factoryMode) {\n",
)

hal_decl = r'''  void displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,
                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH,
                           bool turnOffScreen = false);
'''
replace_once(
    HAL_H,
    hal_decl,
    hal_decl + r'''  void displayScrubWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen = false);
''',
)

hal_impl = r'''void HalDisplay::displayScrubWindow(uint16_t x, uint16_t y, uint16_t w, uint16_t h, bool turnOffScreen) {
  HalSpiBus::Lock spiLock;
  einkDisplay.displayScrubWindow(x, y, w, h, turnOffScreen);
}

'''
replace_once(HAL_CPP, "void HalDisplay::setInverted(bool inverted) {\n", hal_impl + "void HalDisplay::setInverted(bool inverted) {\n")

driver_decl = r'''  void displaySparseWindow(EpdBus& bus, const uint8_t* fb, const uint8_t* prev, const uint8_t* tileMask,
                           uint16_t tileCols, uint16_t tileRows, uint16_t tileW, uint16_t tileH,
                           uint16_t bboxX, uint16_t bboxY, uint16_t bboxW, uint16_t bboxH, bool turnOff) override;
'''
replace_once(
    DRIVER_H,
    driver_decl,
    driver_decl + r'''  void displayScrubWindow(EpdBus& bus, const uint8_t* fb, uint16_t x, uint16_t y,
                          uint16_t w, uint16_t h, bool turnOff) override;
''',
)

scrub_impl = r'''
void Uc8279X4Driver::displayScrubWindow(EpdBus& bus, const uint8_t* fb, uint16_t x, uint16_t y,
                                        uint16_t w, uint16_t h, bool turnOff) {
  if (!fb || w == 0 || h == 0 || x + w > _w || y + h > _h ||
      (x & 0x07) != 0 || (w & 0x07) != 0) {
    return;
  }

  // If OLD RAM is not authoritative, retain the proven stock HALF semantics.
  if (_needFullClear || !_oldPlaneValid || _redriveAfterGray) {
    display(bus, fb, nullptr, RefreshMode::Half, turnOff);
    return;
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

  // OLD = complement(target): every cell is a real transition, never WW/BB.
  streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h, /*invert=*/true);
  bus.cmd(CMD_PARTIAL_OUT);

  // Keep the seeded OLD plane (prev=nullptr). Existing 4P + PLL0F window code
  // uploads NEW, performs exactly one DRF, restores PLL, then resyncs DTM1=NEW.
  displayWindow(bus, fb, nullptr, x, y, w, h, turnOff);
}

'''
replace_once(DRIVER_CPP, "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n",
             scrub_impl + "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n")

old_force = r'''  if (forceFullRefresh) {
    if (waveScrubPending_) {
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }
    uint8_t* const fb = display.getFrameBuffer();
    const uint32_t bufferSize = display.getBufferSize();
    if (windowShadow_ == nullptr && bufferSize != 0) {
      windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    }
    if (windowShadow_ != nullptr && fb != nullptr && bufferSize != 0) {
      memcpy(windowShadow_, fb, bufferSize);
      windowShadowValid_ = true;
    }
  } else {
    refreshPlayingWindow(false);
  }
'''

new_force = r'''  if (forceFullRefresh) {
    if (waveScrubPending_ && windowShadowValid_ && windowShadow_ != nullptr) {
      const uint16_t panelW = display.getDisplayWidth();
      const uint16_t panelH = display.getDisplayHeight();
      // One coherent physical refresh over the complete panel. The entire
      // full-scene framebuffer (header, HUD, field, cities) is refreshed now.
      display.displayScrubWindow(0, 0, panelW, panelH, false);
      clusterCatchupPending_ = false;
      waveScrubPending_ = false;
    } else if (waveScrubPending_) {
      // Missing baseline: preserve the known-good stock scrub rather than risk
      // a differential clean against stale controller RAM.
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }

    uint8_t* const fb = display.getFrameBuffer();
    const uint32_t bufferSize = display.getBufferSize();
    if (windowShadow_ == nullptr && bufferSize != 0) {
      windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    }
    if (windowShadow_ != nullptr && fb != nullptr && bufferSize != 0) {
      // Full panel was physically refreshed, so the whole app shadow is now
      // authoritative. No delayed scrub rectangles exist after this point.
      memcpy(windowShadow_, fb, bufferSize);
      windowShadowValid_ = true;
    }
  } else {
    refreshPlayingWindow(false);
  }
'''
replace_once(MISSILE_CPP, old_force, new_force)

text = Path(MISSILE_CPP).read_text()
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-fullscrub-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1', 'MISSILE-A2-OPT12-4P-CLUSTER1-FULLSCRUB')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-fullscrub-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-fullscrub,%lu,%lu,%lu,%lu,%lu',
)
Path(MISSILE_CPP).write_text(text)

print("4P Cluster1: coherent full-screen forced-transition wave scrub applied")
