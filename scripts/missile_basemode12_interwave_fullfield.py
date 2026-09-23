from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")

cpp = CPP.read_text()
hdr = HDR.read_text()


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:260]!r}")
    return text.replace(old, new, 1)


def replace_function(text: str, signature: str, next_signature: str, replacement: str, name: str) -> str:
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"{name} start not found")
    end = text.find(next_signature, start)
    if end < 0:
        raise SystemExit(f"{name} end not found")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


# ---------------------------------------------------------------------------
# Header/state: add a WaveComplete view and compact captured end-of-wave stats.
# ---------------------------------------------------------------------------
hdr = replace_once(
    hdr,
    "  enum class ViewMode : uint8_t { Menu, Playing, GameOver };\n",
    "  enum class ViewMode : uint8_t { Menu, Playing, WaveComplete, GameOver };\n",
    "wave complete view mode",
)

hdr = replace_once(
    hdr,
    "  uint16_t wave_ = 1;\n",
    "  uint16_t wave_ = 1;\n"
    "  uint16_t completedWave_ = 0;\n"
    "  uint16_t waveEndAmmoRemaining_ = 0;\n"
    "  uint8_t waveEndObjectives_ = 0;\n"
    "  bool interWavePrepPending_ = false;\n",
    "inter-wave stats state",
)

hdr = replace_once(
    hdr,
    "  void loopGameOver();\n",
    "  void loopGameOver();\n"
    "  void loopWaveComplete();\n",
    "wave complete loop declaration",
)

hdr = replace_once(
    hdr,
    "  void renderGameOver();\n",
    "  void renderGameOver();\n"
    "  void renderWaveComplete();\n",
    "wave complete render declaration",
)

hdr = replace_once(
    hdr,
    "  void startWave();\n",
    "  void startWave();\n"
    "  void beginPreparedWave();\n",
    "prepared wave declaration",
)

HDR.write_text(hdr)


# ---------------------------------------------------------------------------
# Geometry: delete the Score/Record strip from gameplay. Keep the small normal
# application header for Back/navigation; the play field starts immediately
# below it and gains the complete former status-strip height.
# ---------------------------------------------------------------------------
geom_start = cpp.find("GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {")
geom_end = cpp.find("\n}\n\nbool pointInRect", geom_start)
if geom_start < 0 or geom_end < 0:
    raise SystemExit("gameGeometry function not found")
geom_end += 3
new_geom = r'''GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const Rect status{0, 0, 0, 0};  // no in-game HUD strip
  const int fieldTop = header.y + header.height + metrics.verticalSpacing;
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  const Rect field{metrics.contentSidePadding, fieldTop,
                   renderer.getScreenWidth() - 2 * metrics.contentSidePadding,
                   std::max(80, footerTop - fieldTop - metrics.verticalSpacing)};
  return GameGeometry{header, status, field, field.y + field.height - 34};
}'''
cpp = cpp[:geom_start] + new_geom + cpp[geom_end:]


# Inter-wave panel geometry.
gameover_action = r'''Rect gameOverActionRect(const GfxRenderer& renderer) {
  const Rect box = gameOverBox(renderer);
  return Rect{box.x + 12, box.y + 106, box.width - 24, 48};
}

'''
if gameover_action not in cpp:
    raise SystemExit("game-over geometry anchor not found")
wave_geom = gameover_action + r'''Rect waveCompleteBox(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + 12;
  const int bottom = renderer.getScreenHeight() - UITheme::getInstance().getMetrics().buttonHintsHeight - 10;
  const int width = std::min(560, renderer.getScreenWidth() - 40);
  const int height = std::max(220, bottom - top);
  return Rect{(renderer.getScreenWidth() - width) / 2, top, width, height};
}

Rect waveCompleteActionRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect box = waveCompleteBox(renderer, mappedInput);
  return Rect{box.x + 28, box.y + box.height - 58, box.width - 56, 44};
}

'''
cpp = cpp.replace(gameover_action, wave_geom, 1)


# ---------------------------------------------------------------------------
# View dispatch.
# ---------------------------------------------------------------------------
cpp = replace_once(
    cpp,
    "    case ViewMode::Playing:\n      loopPlaying();\n      break;\n"
    "    case ViewMode::GameOver:\n",
    "    case ViewMode::Playing:\n      loopPlaying();\n      break;\n"
    "    case ViewMode::WaveComplete:\n      loopWaveComplete();\n      break;\n"
    "    case ViewMode::GameOver:\n",
    "loop wave-complete dispatch",
)

cpp = replace_once(
    cpp,
    "    case ViewMode::Playing:\n      renderPlaying();\n      break;\n"
    "    case ViewMode::GameOver:\n",
    "    case ViewMode::Playing:\n      renderPlaying();\n      break;\n"
    "    case ViewMode::WaveComplete:\n      renderWaveComplete();\n      break;\n"
    "    case ViewMode::GameOver:\n",
    "render wave-complete dispatch",
)


# ---------------------------------------------------------------------------
# Gameplay header/HUD: static app title only, then field. Remove the complete
# Score/Record draw block. Logical score tracking remains in drawPlayingFrame().
# ---------------------------------------------------------------------------
full_sig = "void MissileCommandActivity::drawFullPlayingScene() {"
full_start = cpp.find(full_sig)
if full_start < 0:
    raise SystemExit("drawFullPlayingScene not found")
title_start = cpp.find("  char gameplayTitle[64];", full_start)
field_draw = cpp.find("  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);", full_start)
if title_start < 0 or field_draw < 0 or title_start > field_draw:
    raise SystemExit("final gameplay header/HUD block not found")
static_header = r'''  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }

'''
cpp = cpp[:title_start] + static_header + cpp[field_draw:]


# ---------------------------------------------------------------------------
# True ammo bargraph: solid black at full ammo, continuously recedes left->right
# as shots are spent. No text and no per-shot refresh request; normal Cluster1
# sees only the few boundary pixels that changed.
# ---------------------------------------------------------------------------
gauge_start_marker = "    // Ammo is represented directly by the battery body."
gauge_start = cpp.find(gauge_start_marker)
if gauge_start < 0:
    raise SystemExit("BaseMode11 ammo gauge block not found")
gauge_end_marker = "  }\n\n  for (const auto& missile : enemies_)"
gauge_end = cpp.find(gauge_end_marker, gauge_start)
if gauge_end < 0:
    raise SystemExit("BaseMode11 ammo gauge end not found")

# Keep loop prefix through the battery Rect, replace only body after Rect.
rect_anchor = cpp.rfind("    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};\n", 0, gauge_start)
if rect_anchor < 0:
    raise SystemExit("battery Rect anchor not found")
body_start = rect_anchor + len("    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};\n")
new_gauge_body = r'''    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);

    const int capacity = 10 + std::min<int>(wave_ / 2, 5);
    const int remaining = std::clamp<int>(ammo_[static_cast<size_t>(i)], 0, capacity);
    const Rect gauge{battery.x + 4, battery.y + 6, battery.width - 8, battery.height - 12};
    renderer.drawRect(gauge.x, gauge.y, gauge.width, gauge.height, 1, true);

    const int innerW = std::max(1, gauge.width - 2);
    const int innerH = std::max(1, gauge.height - 2);
    const int fillW = capacity > 0 ? (innerW * remaining + capacity - 1) / capacity : 0;
    if (fillW > 0)
      renderer.fillRect(gauge.x + 1, gauge.y + 1, std::min(innerW, fillW), innerH, true);
'''
cpp = cpp[:body_start] + new_gauge_body + cpp[gauge_end:]


# ---------------------------------------------------------------------------
# End-of-wave state machine.
#
# The first intermission loop prepares the next wave while the static summary is
# already on screen: arrays/ammo/save are ready before the player presses the
# button. Explosion geometry is static, so stop rebuilding the whole cache at
# every wave; onEnter() already prepares it once.
# ---------------------------------------------------------------------------
cpp = cpp.replace("void MissileCommandActivity::startWave() {\n  prepareExplosionCache(true);\n",
                  "void MissileCommandActivity::startWave() {\n  prepareExplosionCache();\n", 1)

finish_wave = r'''void MissileCommandActivity::finishWaveIfNeeded() {
  const int targetCount = 5 + difficulty_ * 2 + std::min<int>(wave_, 7);
  if (enemiesSpawned_ < targetCount || activeEnemyCount() > 0 || activePlayerCount() > 0) return;

  completedWave_ = wave_;
  waveEndAmmoRemaining_ = 0;
  for (uint8_t ammo : ammo_) waveEndAmmoRemaining_ = static_cast<uint16_t>(waveEndAmmoRemaining_ + ammo);
  waveEndObjectives_ = static_cast<uint8_t>(std::max(0, aliveCityCount()));

  if (baseMode_) {
    for (int i = 0; i < kBatteryCount; ++i) {
      if (batteriesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  } else {
    for (int i = 0; i < kCityCount; ++i) {
      if (citiesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  }
  for (uint8_t ammo : ammo_) score_ += static_cast<uint32_t>(ammo) * 5;

  if (score_ > highScore_) highScore_ = score_;
  saveHighScore();

  // Freeze gameplay on a clean summary screen. The next normal loop performs
  // next-wave preparation while the user is reading it.
  viewMode_ = ViewMode::WaveComplete;
  interWavePrepPending_ = true;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;
  requestUpdate();
}'''
cpp = replace_function(
    cpp,
    "void MissileCommandActivity::finishWaveIfNeeded() {",
    "void MissileCommandActivity::finishGame() {",
    finish_wave,
    "finishWaveIfNeeded",
)


# Intermission loop inserted before loopGameOver.
loop_wave = r'''void MissileCommandActivity::loopWaveComplete() {
  // Use the human pause between waves for all safe next-wave preparation.
  // Staying in WaveComplete means none of this can advance simulation.
  if (interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    saveGame();
    interWavePrepPending_ = false;
  }

  const Rect header = headerRect(renderer, mappedInput);
  const bool headerBack = mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header);
  int tx = 0;
  int ty = 0;
  const bool touchNext = mappedInput.hasTouchHardware() && !headerBack && mappedInput.wasScreenTapped(tx, ty) &&
                         pointInRect(waveCompleteActionRect(renderer, mappedInput), tx, ty);

  if (headerBack || mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  if (touchNext || mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    beginPreparedWave();
  }
}

'''
gameover_loop_sig = "void MissileCommandActivity::loopGameOver() {"
idx = cpp.find(gameover_loop_sig)
if idx < 0:
    raise SystemExit("loopGameOver insertion point not found")
cpp = cpp[:idx] + loop_wave + cpp[idx:]


# Begin next wave is deliberately tiny because startWave()/save were already
# completed during the pause.
begin_wave = r'''void MissileCommandActivity::beginPreparedWave() {
  if (interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    saveGame();
    interWavePrepPending_ = false;
  }

  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastCycleUs_ = esp_timer_get_time();
  nextSpawnUs_ = lastCycleUs_ + 500000;
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);

  // The intermission was a different full-screen image. Force the already
  // accepted clean gameplay-entry HALF baseline, then return to Cluster1.
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  requestUpdate();
}

'''
tick_sig = "void MissileCommandActivity::tickGame(int64_t nowUs) {"
idx = cpp.find(tick_sig)
if idx < 0:
    raise SystemExit("tickGame insertion point not found")
cpp = cpp[:idx] + begin_wave + cpp[idx:]


# Static intermission render. It is outside active gameplay, so use a stock HALF
# refresh for highly readable text; no custom waveform/driver changes.
render_wave = r'''void MissileCommandActivity::renderWaveComplete() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, header, "Missile Command", nullptr, false);
  }

  const Rect box = waveCompleteBox(renderer, mappedInput);
  const Rect action = waveCompleteActionRect(renderer, mappedInput);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 1, 8, true);

  char line[72];
  std::snprintf(line, sizeof(line), "Vague %u terminee", static_cast<unsigned>(completedWave_));
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 16, box.y + 14, box.width - 32, 34}, line);

  std::snprintf(line, sizeof(line), "Score actuel : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 62, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "Meilleur score : %lu", static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 94, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "Munitions restantes : %u",
                static_cast<unsigned>(waveEndAmmoRemaining_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 126, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "%s restantes : %u",
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 158, box.width - 40, 28}, line);

  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Vague suivante");

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);

  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  cycleRenderPending_.store(false);
}

'''
gameover_render_sig = "void MissileCommandActivity::renderGameOver() {"
idx = cpp.find(gameover_render_sig)
if idx < 0:
    raise SystemExit("renderGameOver insertion point not found")
cpp = cpp[:idx] + render_wave + cpp[idx:]


# onExit: if the app is closed directly from the intermission before its first
# loop, prepare/save the next wave so Continue can never replay a completed one.
onexit_sig = "void MissileCommandActivity::onExit() {"
onexit_end_sig = "void MissileCommandActivity::loop() {"
new_onexit = r'''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::WaveComplete && interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    interWavePrepPending_ = false;
  }
  if ((viewMode_ == ViewMode::Playing || viewMode_ == ViewMode::WaveComplete) && aliveCityCount() > 0)
    saveGame();
  if (viewMode_ != ViewMode::Menu) saveHighScore();
  releaseWindowShadow();
  Activity::onExit();
}'''
cpp = replace_function(cpp, onexit_sig, onexit_end_sig, new_onexit, "onExit")


# Distinct telemetry identity.
cpp = cpp.replace("/missile-command-bm11-ammo-gauge-bench.csv",
                  "/missile-command-bm12-interwave-fullfield-bench.csv")
cpp = cpp.replace("/missile-command-bm11-ammo-gauge-trace.csv",
                  "/missile-command-bm12-interwave-fullfield-trace.csv")
cpp = cpp.replace("bm11-ammo-gauge-started", "bm12-interwave-fullfield-started")
cpp = cpp.replace("bm11-ammo-gauge,%lu,%lu,%lu,%lu,%lu",
                  "bm12-interwave-fullfield,%lu,%lu,%lu,%lu,%lu")
cpp = cpp.replace("MISSILE-BM11-AMMO-GAUGE", "MISSILE-BM12-INTERWAVE-FULLFIELD")

CPP.write_text(cpp)
print("Missile BaseMode12: continuous ammo bars + full-height field + inter-wave summary/prep applied")
