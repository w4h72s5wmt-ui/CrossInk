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
# New experimental primitive: force every pixel in one PTL window through a
# transition by seeding DTM1 with the complement of the target, then delegate to
# the already validated 4P/PLL0F displayWindow path. displayWindow performs the
# DRF and post-refresh DTM1=target resync, so the ordinary differential invariant
# is restored immediately after the scrub.
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
  cancelGrayscalePass();
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

  // A local differential scrub is meaningful only when controller OLD RAM is
  // authoritative. Fall back to the proven full HALF scrub if that invariant
  // is not available (boot/resync/post-gray edge cases).
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

  // Seed OLD = complement(target) only inside the gameplay field. Every pixel
  // in this PTL therefore selects BW or WB on the following 4P refresh; WW/BB
  // no-drive cells cannot idle with stale charge. Exit PTIN before delegating so
  // displayWindow starts from its normal, validated command sequence.
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
  streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h, /*invert=*/true);
  bus.cmd(CMD_PARTIAL_OUT);

  // prev=nullptr is intentional: keep the complemented DTM1 seed we just
  // uploaded. The existing 4P displayWindow sends NEW, runs one DRF at PLL0F,
  // then writes DTM1=target to restore the baseline.
  displayWindow(bus, fb, nullptr, x, y, w, h, turnOff);
}

'''
replace_once(DRIVER_CPP, "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n",
             scrub_impl + "void Uc8279X4Driver::requestResync(uint8_t settlePasses) {\n")

# ---------------------------------------------------------------------------
# Missile wave transition: scrub only the gameplay FIELD with the local 4P
# primitive. Header/status changes deliberately remain different from the app
# shadow and are picked up by the next normal dirty cycle (Cluster1 can keep
# that catch-up compact). Initial entry / missing shadow still uses stock paths.
# ---------------------------------------------------------------------------

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
    bool localWaveScrub = false;
    uint16_t scrubX = 0;
    uint16_t scrubY = 0;
    uint16_t scrubW = 0;
    uint16_t scrubH = 0;

    if (waveScrubPending_ && windowShadowValid_ && windowShadow_ != nullptr) {
      const GameGeometry scrubGeometry = gameGeometry(renderer, mappedInput);
      const int panelW = display.getDisplayWidth();
      const int panelH = display.getDisplayHeight();
      const int left = std::max(0, scrubGeometry.field.x);
      const int top = std::max(0, scrubGeometry.field.y);
      const int right = std::min(panelW, scrubGeometry.field.x + scrubGeometry.field.width);
      const int bottom = std::min(panelH, scrubGeometry.field.y + scrubGeometry.field.height);
      if (right > left && bottom > top) {
        const int alignedLeft = left & ~7;
        const int alignedRight = std::min(panelW, (right + 7) & ~7);
        scrubX = static_cast<uint16_t>(alignedLeft);
        scrubY = static_cast<uint16_t>(top);
        scrubW = static_cast<uint16_t>(alignedRight - alignedLeft);
        scrubH = static_cast<uint16_t>(bottom - top);
        if (scrubW != 0 && scrubH != 0) {
          display.displayScrubWindow(scrubX, scrubY, scrubW, scrubH, false);
          localWaveScrub = true;
          clusterCatchupPending_ = false;
        }
      }
      waveScrubPending_ = false;
    } else if (waveScrubPending_) {
      // Safety fallback when entering a wave without a proven app/controller
      // baseline. This should be rare (initial/resync paths only).
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }

    uint8_t* const fb = display.getFrameBuffer();
    const uint32_t bufferSize = display.getBufferSize();
    const uint16_t wb = display.getDisplayWidthBytes();
    if (windowShadow_ == nullptr && bufferSize != 0) {
      windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    }
    if (windowShadow_ != nullptr && fb != nullptr && bufferSize != 0) {
      if (localWaveScrub && wb != 0) {
        const uint16_t startByte = static_cast<uint16_t>(scrubX / 8);
        const uint16_t copyBytes = static_cast<uint16_t>(scrubW / 8);
        for (uint16_t row = 0; row < scrubH; ++row) {
          const uint32_t offset = static_cast<uint32_t>(scrubY + row) * wb + startByte;
          memcpy(windowShadow_ + offset, fb + offset, copyBytes);
        }
        // Keep the previous shadow everywhere else. The title/status were drawn
        // into fb but not physically refreshed, so the next normal frame sees
        // them as dirty instead of falsely acknowledging them.
        windowShadowValid_ = true;
      } else {
        memcpy(windowShadow_, fb, bufferSize);
        windowShadowValid_ = true;
      }
    }
  } else {
    refreshPlayingWindow(false);
  }
'''
replace_once(MISSILE_CPP, old_force, new_force)

# Separate benchmark identity.
text = Path(MISSILE_CPP).read_text()
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-localscrub-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1', 'MISSILE-A2-OPT12-4P-CLUSTER1-LOCALSCRUB')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-localscrub-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-localscrub,%lu,%lu,%lu,%lu,%lu',
)
Path(MISSILE_CPP).write_text(text)

print("4P Cluster1: local field-only forced-transition wave scrub applied")
