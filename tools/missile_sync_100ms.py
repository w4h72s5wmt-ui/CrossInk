from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def one(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)


cpp = CPP.read_text()

old_constants = '''// Simulation and panel cadence are deliberately independent. The old version
// advanced the game once per screen refresh, so a slow e-ink waveform made the
// whole game slow. We now simulate at 25 Hz and only ask for a new visible frame
// every 120 ms. If the panel is still busy the render task waits, while the main
// task continues simulating and accepting touch input.
constexpr int64_t LOGIC_TICK_US = 33333;
constexpr int64_t FRAME_INTERVAL_US = 33333;
constexpr int MAX_CATCHUP_TICKS = 8;
constexpr int EXPLOSION_PHASE_TICKS = 2;'''
new_constants = '''// Gameplay, touch and e-ink are intentionally locked to one 100 ms cadence.
// There is no catch-up simulation and no frame running ahead of the panel:
// one cycle consumes input, advances the world exactly once, renders that exact
// state, then waits for the FAST refresh to complete before another cycle.
constexpr int64_t GAME_FRAME_US = 100000;
constexpr int EXPLOSION_PHASE_TICKS = 1;'''
cpp = one(cpp, old_constants, new_constants, "timing constants")

cpp = one(cpp, '''  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  refreshInFlight_ = false;''', '''  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;''', "onEnter frame state")
cpp = one(cpp, '''  resetRenderCaches();
  requestUpdate();''', '''  requestUpdate();''', "onEnter cache reset")
cpp = one(cpp, '''void MissileCommandActivity::onExit() {
  waitForPendingRefresh();
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();''', '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();''', "onExit wait")

loop_start = cpp.index("void MissileCommandActivity::loopPlaying() {")
loop_end = cpp.index("\nvoid MissileCommandActivity::loopGameOver()", loop_start)
new_loop = r'''void MissileCommandActivity::loopPlaying() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);

  // Capture input continuously, but consume it only at the next 100 ms game
  // frame. This gives touch exactly the same temporal state as simulation and
  // display instead of letting input or gameplay run ahead of the e-ink panel.
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    pendingBack_ = true;
  }

  int tx = 0;
  int ty = 0;
  if (!pendingBack_ && mappedInput.wasScreenTapped(tx, ty) && pointInRect(geometry.field, tx, ty) &&
      ty < geometry.groundY) {
    pendingTapX_ = static_cast<int16_t>(tx);
    pendingTapY_ = static_cast<int16_t>(ty);
    pendingTap_ = true;
  }

  // A new world step is forbidden until the frame representing the previous
  // step has finished on the panel. This is the core 1:1 game/display lock.
  if (cycleRenderPending_.load()) return;

  const int64_t now = esp_timer_get_time();
  if (lastCycleUs_ == 0) lastCycleUs_ = now;
  if (now - lastCycleUs_ < GAME_FRAME_US) return;
  lastCycleUs_ = now;

  if (pendingBack_) {
    pendingBack_ = false;
    pendingTap_ = false;
    returnToMenu();
    return;
  }

  if (pendingTap_) {
    launchPlayerMissile(pendingTapX_, pendingTapY_);
    pendingTap_ = false;
  }

  tickGame(now);
  if (viewMode_ != ViewMode::Playing) return;

  cycleRenderPending_.store(true);
  requestUpdate();
}
'''
cpp = cpp[:loop_start] + new_loop + cpp[loop_end:]

for func in ("newGame", "continueGame"):
    marker = f"void MissileCommandActivity::{func}() {{\n  waitForPendingRefresh();"
    cpp = one(cpp, marker, f"void MissileCommandActivity::{func}() {{", f"{func} wait")

cpp = one(cpp, '''  lastLogicTickUs_ = esp_timer_get_time();
  lastFrameRequestUs_ = 0;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
  requestUpdate();''', '''  lastCycleUs_ = esp_timer_get_time();
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);
  requestUpdate();''', "new game timing")

cpp = one(cpp, '''  lastLogicTickUs_ = esp_timer_get_time();
  lastFrameRequestUs_ = 0;
  nextSpawnUs_ = lastLogicTickUs_ + 500000;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
  requestUpdate();''', '''  lastCycleUs_ = esp_timer_get_time();
  nextSpawnUs_ = lastCycleUs_ + 500000;
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);
  requestUpdate();''', "continue timing")

cpp = one(cpp, '''void MissileCommandActivity::returnToMenu() {
  waitForPendingRefresh();
  if (aliveCityCount() > 0) saveGame();''', '''void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();''', "return wait")
cpp = one(cpp, '''  sceneNeedsFullRedraw_ = true;
  requestUpdate();
}

void MissileCommandActivity::startWave()''', '''  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;
  requestUpdate();
}

void MissileCommandActivity::startWave()''', "return state")
cpp = one(cpp, '''  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
}

void MissileCommandActivity::tickGame''', '''  sceneNeedsFullRedraw_ = true;
}

void MissileCommandActivity::tickGame''', "startWave cache")

cpp = one(cpp, '''  // Speeds are per 40 ms simulation tick. These values preserve roughly the
  // original real-time descent speed while producing much finer movement.
  slot->speed = static_cast<uint16_t>(4 + difficulty_ + std::min<int>(wave_ / 2, 4));''', '''  // Speeds are per 100 ms synchronized frame. Scale from the previous 33 ms
  // cadence so real-world descent time stays approximately unchanged.
  slot->speed = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);''', "enemy speed")
cpp = one(cpp, "  slot->speed = 46;", "  slot->speed = 140;", "player speed")
cpp = one(cpp, '''  viewMode_ = ViewMode::GameOver;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  requestUpdate();''', '''  viewMode_ = ViewMode::GameOver;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  requestUpdate();''', "finish game")

render_marker = "void MissileCommandActivity::render(RenderLock&&) {\n  waitForPendingRefresh();"
cpp = one(cpp, render_marker, "void MissileCommandActivity::render(RenderLock&&) {", "render wait")

cache_start = cpp.index("void MissileCommandActivity::resetRenderCaches() {")
draw_full_start = cpp.index("void MissileCommandActivity::drawFullPlayingScene() {", cache_start)
cpp = cpp[:cache_start] + cpp[draw_full_start:]
cpp = cpp.replace("  resetRenderCaches();\n", "")

cpp = cpp.replace("bool MissileCommandActivity::drawIncrementalPlayingScene() {", "void MissileCommandActivity::drawPlayingFrame() {")
cpp = one(cpp, '''  // Recompose the whole gameplay field in RAM each visible frame. This clears
  // the previous missile positions while retaining FAST differential e-ink
  // refresh. No permanent trajectory accumulation remains.''', '''  // Recompose the complete gameplay field from the synchronized world state.
  // Active missiles redraw their FULL trajectory from launch to current point.
  // As soon as a missile dies, reaches its target or hits the ground, it is no
  // longer active and its complete trail is therefore erased on this frame.''', "frame comment")

old_enemy = '''  for (const auto& missile : enemies_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 45 ? static_cast<uint16_t>(missile.progress - 45) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
  }'''
new_enemy = '''  for (const auto& missile : enemies_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    renderer.drawLine(missile.startX, missile.startY, x, y, 1, true);
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
  }'''
cpp = one(cpp, old_enemy, new_enemy, "enemy full trail")

old_player = '''  for (const auto& missile : players_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 70 ? static_cast<uint16_t>(missile.progress - 70) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);
  }'''
new_player = '''  for (const auto& missile : players_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    renderer.drawLine(missile.startX, missile.startY, x, y, 1, true);
    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);
  }'''
cpp = one(cpp, old_player, new_player, "player full trail")
cpp = one(cpp, '''  drawCenteredText(renderer, UI_10_FONT_ID, geometry.status, status);
  return true;
}

void MissileCommandActivity::renderPlaying() {
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  if (drawIncrementalPlayingScene()) startFastRefresh();
}''', '''  drawCenteredText(renderer, UI_10_FONT_ID, geometry.status, status);
}

void MissileCommandActivity::renderPlaying() {
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  drawPlayingFrame();

  // Blocking FAST refresh is deliberate: the next 100 ms simulation/input
  // cycle cannot begin until this exact frame has completed on the panel.
  renderer.displayBuffer(HalDisplay::FAST_REFRESH);
  cycleRenderPending_.store(false);
}''', "synchronized render")
cpp = one(cpp, '''  drawFullPlayingScene();
  drawIncrementalPlayingScene();''', '''  drawFullPlayingScene();
  drawPlayingFrame();''', "gameover frame")

CPP.write_text(cpp)

hdr = HDR.read_text()
old_state = '''  int64_t lastLogicTickUs_ = 0;
  int64_t lastFrameRequestUs_ = 0;
  int64_t nextSpawnUs_ = 0;
  bool hasSavedGame_ = false;
  bool frameDirty_ = false;
  bool sceneNeedsFullRedraw_ = true;
  bool refreshInFlight_ = false;

  // Rendering state belongs to the render task. The gameplay state above can
  // advance several 40 ms simulation ticks while an e-ink waveform is still
  // running; these caches let the next frame draw only the new trail segments.
  std::array<int16_t, kMaxEnemyMissiles> enemyDrawX_{};
  std::array<int16_t, kMaxEnemyMissiles> enemyDrawY_{};
  std::array<uint16_t, kMaxEnemyMissiles> enemyDrawProgress_{};
  std::array<uint8_t, kMaxEnemyMissiles> enemyDrawValid_{};
  std::array<int16_t, kMaxPlayerMissiles> playerDrawX_{};
  std::array<int16_t, kMaxPlayerMissiles> playerDrawY_{};
  std::array<uint16_t, kMaxPlayerMissiles> playerDrawProgress_{};
  std::array<uint8_t, kMaxPlayerMissiles> playerDrawValid_{};
  std::array<uint8_t, kMaxExplosions> explosionDrawPhase_{};
  std::array<uint8_t, kMaxExplosions> explosionDrawValid_{};
  std::array<uint8_t, kCityCount> drawnCitiesAlive_{};
  std::array<uint8_t, kBatteryCount> drawnAmmo_{};
  uint32_t drawnScore_ = UINT32_MAX;
  uint16_t drawnWave_ = UINT16_MAX;
  int drawnCityCount_ = -1;'''
new_state = '''  int64_t lastCycleUs_ = 0;
  int64_t nextSpawnUs_ = 0;
  bool hasSavedGame_ = false;
  bool sceneNeedsFullRedraw_ = true;

  // Main task captures touch into the next frame; render task clears this only
  // after the blocking FAST refresh completes. This enforces a strict 1:1
  // relationship between input, simulation state and the visible e-ink frame.
  std::atomic<bool> cycleRenderPending_{false};
  bool pendingTap_ = false;
  int16_t pendingTapX_ = 0;
  int16_t pendingTapY_ = 0;
  bool pendingBack_ = false;'''
hdr = one(hdr, old_state, new_state, "header state")
hdr = one(hdr, '''  bool drawIncrementalPlayingScene();
  void waitForPendingRefresh();
  void startFastRefresh();
  void resetRenderCaches();''', '''  void drawPlayingFrame();''', "header render methods")
HDR.write_text(hdr)

print("Missile Command converted to strict synchronized 100 ms frames")
