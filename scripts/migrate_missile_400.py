from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


H = "src/activities/home/MissileCommandActivity.h"
CPP = "src/activities/home/MissileCommandActivity.cpp"
PATCH = "scripts/uc8279_window_benchmark_patch.py"

# Keep gameplay/window state directly in the app (not in the build patch).
replace_once(
    H,
    "  bool sceneNeedsFullRedraw_ = true;\n",
    "  bool sceneNeedsFullRedraw_ = true;\n"
    "  uint8_t* windowShadow_ = nullptr;\n"
    "  bool windowShadowValid_ = false;\n",
)
replace_once(
    H,
    "  void drawPlayingFrame();\n",
    "  void drawPlayingFrame();\n"
    "  void refreshPlayingWindow(bool forceFullRefresh);\n"
    "  void releaseWindowShadow();\n",
)

replace_once(CPP, "#include <GfxRenderer.h>\n", "#include <GfxRenderer.h>\n#include <HalDisplay.h>\n#include <esp_heap_caps.h>\n")
replace_once(CPP, "#include <cstdio>\n", "#include <cstdio>\n#include <cstring>\n")

replace_once(
    CPP,
    "constexpr int64_t GAME_FRAME_US = 100000;\n",
    "constexpr int64_t GAME_FRAME_US = 100000;\n"
    "// Physical 1:1 gameplay viewport. This is NOT upscaled: limiting panel PTL\n"
    "// to 400x240 caps the worst gameplay refresh at 25% of the 800x480 panel.\n"
    "constexpr int GAME_VIEW_W = 400;\n"
    "constexpr int GAME_VIEW_H = 240;\n"
    "constexpr int GAME_EFFECT_MARGIN = 40;  // max explosion radius is 35 px\n",
)

old_geometry = '''GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int statusH = std::max(44, renderer.getLineHeight(UI_10_FONT_ID) + 16);
  const Rect status{metrics.contentSidePadding, header.y + header.height + metrics.verticalSpacing,
                    renderer.getScreenWidth() - 2 * metrics.contentSidePadding, statusH};
  const int fieldTop = status.y + status.height + metrics.verticalSpacing;
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  const Rect field{metrics.contentSidePadding, fieldTop,
                   renderer.getScreenWidth() - 2 * metrics.contentSidePadding,
                   std::max(80, footerTop - fieldTop - metrics.verticalSpacing)};
  return GameGeometry{header, status, field, field.y + field.height - 34};
}
'''
new_geometry = '''GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect header = headerRect(renderer, mappedInput);
  const int viewW = std::min(GAME_VIEW_W, renderer.getScreenWidth());
  const int viewH = std::min(GAME_VIEW_H, renderer.getScreenHeight());
  // 800-400 = 400, so X=200 is naturally byte aligned for displayWindow().
  const int viewX = (renderer.getScreenWidth() - viewW) / 2;
  const int viewY = (renderer.getScreenHeight() - viewH) / 2;
  const int statusH = std::max(30, renderer.getLineHeight(UI_10_FONT_ID) + 8);
  constexpr int gap = 4;
  const Rect status{viewX, viewY, viewW, statusH};
  const Rect field{viewX, viewY + statusH + gap, viewW, std::max(80, viewH - statusH - gap)};
  return GameGeometry{header, status, field, field.y + field.height - GAME_EFFECT_MARGIN};
}
'''
replace_once(CPP, old_geometry, new_geometry)

replace_once(
    CPP,
    "  sceneNeedsFullRedraw_ = true;\n  cycleRenderPending_.store(false);\n",
    "  sceneNeedsFullRedraw_ = true;\n  windowShadowValid_ = false;\n  cycleRenderPending_.store(false);\n",
)

replace_once(
    CPP,
    "void MissileCommandActivity::onExit() {\n  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n  saveHighScore();\n  Activity::onExit();\n}\n",
    "void MissileCommandActivity::onExit() {\n"
    "  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n"
    "  saveHighScore();\n"
    "  releaseWindowShadow();\n"
    "  Activity::onExit();\n"
    "}\n",
)

replace_once(
    CPP,
    "  sceneNeedsFullRedraw_ = true;\n  cycleRenderPending_.store(true);\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::continueGame()",
    "  sceneNeedsFullRedraw_ = true;\n  windowShadowValid_ = false;\n  cycleRenderPending_.store(true);\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::continueGame()",
)
replace_once(
    CPP,
    "  sceneNeedsFullRedraw_ = true;\n  cycleRenderPending_.store(true);\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::returnToMenu()",
    "  sceneNeedsFullRedraw_ = true;\n  windowShadowValid_ = false;\n  cycleRenderPending_.store(true);\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::returnToMenu()",
)
replace_once(
    CPP,
    "  pendingTap_ = false;\n  pendingBack_ = false;\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::startWave()",
    "  pendingTap_ = false;\n  pendingBack_ = false;\n  releaseWindowShadow();\n  requestUpdate();\n}\n\nvoid MissileCommandActivity::startWave()",
)
# Wave-to-wave transitions do not need a new full-screen scene; dynamic field/status redraw covers them.
replace_once(
    CPP,
    "  nextSpawnUs_ = esp_timer_get_time() + 500000;\n  sceneNeedsFullRedraw_ = true;\n}\n\nvoid MissileCommandActivity::tickGame",
    "  nextSpawnUs_ = esp_timer_get_time() + 500000;\n}\n\nvoid MissileCommandActivity::tickGame",
)

replace_once(CPP, "  const int margin = 8;\n", "  const int margin = GAME_EFFECT_MARGIN;\n")
replace_once(CPP, "  slot->startY = static_cast<int16_t>(geometry.field.y + 2);\n",
                   "  slot->startY = static_cast<int16_t>(geometry.field.y + GAME_EFFECT_MARGIN);\n")
replace_once(
    CPP,
    "  slot->targetX = static_cast<int16_t>(std::clamp(x, geometry.field.x, geometry.field.x + geometry.field.width - 1));\n"
    "  slot->targetY = static_cast<int16_t>(std::clamp(y, geometry.field.y, geometry.groundY - 4));\n",
    "  slot->targetX = static_cast<int16_t>(std::clamp(x, geometry.field.x + GAME_EFFECT_MARGIN,\n"
    "                                                   geometry.field.x + geometry.field.width - 1 - GAME_EFFECT_MARGIN));\n"
    "  slot->targetY = static_cast<int16_t>(std::clamp(y, geometry.field.y + GAME_EFFECT_MARGIN,\n"
    "                                                   geometry.groundY - 4));\n",
)

replace_once(
    CPP,
    "  std::snprintf(status, sizeof(status), \"Score %lu   Record %lu   Vague %u   Villes %d\",\n"
    "                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_),\n"
    "                static_cast<unsigned>(wave_), aliveCityCount());\n",
    "  std::snprintf(status, sizeof(status), \"S:%lu  R:%lu  V:%u  C:%d\",\n"
    "                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_),\n"
    "                static_cast<unsigned>(wave_), aliveCityCount());\n",
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

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int playX0 = geometry.status.x;
  const int playY0 = geometry.status.y;
  const int playX1 = geometry.field.x + geometry.field.width - 1;
  const int playY1 = geometry.field.y + geometry.field.height - 1;
  const uint16_t bx0 = static_cast<uint16_t>(playX0 / 8);
  const uint16_t bx1 = static_cast<uint16_t>(playX1 / 8);

  uint16_t minByte = static_cast<uint16_t>(bx1 + 1);
  uint16_t maxByte = bx0;
  uint16_t minY = static_cast<uint16_t>(playY1 + 1);
  uint16_t maxY = static_cast<uint16_t>(playY0);
  bool changed = false;

  // Compare only the physical 400x240 gameplay viewport. Static header/footer
  // can therefore never expand a gameplay PTL window.
  for (uint16_t y = static_cast<uint16_t>(playY0); y <= static_cast<uint16_t>(playY1); ++y) {
    const uint32_t rowOffset = static_cast<uint32_t>(y) * wb;
    for (uint16_t bx = bx0; bx <= bx1; ++bx) {
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
replace_once(CPP, "void MissileCommandActivity::renderPlaying() {\n", refresh_impl + "void MissileCommandActivity::renderPlaying() {\n")

old_render = '''void MissileCommandActivity::renderPlaying() {
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  drawPlayingFrame();

  // Blocking FAST refresh is deliberate: the next simulation/input cycle cannot
  // begin until this exact synchronized frame has completed on the panel.
  renderer.displayBuffer(HalDisplay::FAST_REFRESH);
  cycleRenderPending_.store(false);
}
'''
new_render = '''void MissileCommandActivity::renderPlaying() {
  const bool forceFullRefresh = sceneNeedsFullRedraw_ || !windowShadowValid_;
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  drawPlayingFrame();

  // Establish the controller baseline once. After that, gameplay is physically
  // confined to the 400x240 viewport and refreshed synchronously as one dirty PTL.
  refreshPlayingWindow(forceFullRefresh);
  cycleRenderPending_.store(false);
}
'''
replace_once(CPP, old_render, new_render)

# The build patch must now contain ONLY the unavoidable HalDisplay + submodule driver
# injection. App code lives directly in MissileCommandActivity.*.
p = Path(PATCH)
text = p.read_text()
marker = "# ---------------------------------------------------------------------------\n# Missile Command Stage-B integration."
if marker not in text:
    raise SystemExit("driver patch app-section marker not found")
text = text.split(marker, 1)[0].rstrip() + "\n\nprint(\"UC8279 Stage-B driver window patch applied\")\n"
p.write_text(text)

print("Direct 400x240 Missile app migration complete")
