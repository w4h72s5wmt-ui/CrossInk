from pathlib import Path
import re

CPP_PATH = Path("src/activities/home/MissileCommandActivity.cpp")
H_PATH = Path("src/activities/home/MissileCommandActivity.h")

cpp = CPP_PATH.read_text()
hpp = H_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    return out


# ---------------------------------------------------------------------------
# CPP: remove temporary benchmark/controller instrumentation.
# ---------------------------------------------------------------------------
cpp = replace_once(cpp, '#include <BoardConfig.h>\n', '', 'remove BoardConfig include')
cpp = replace_once(cpp, 'constexpr const char BENCHMARK_PATH[] = "/missile-command-benchmark.csv";\n', '', 'remove benchmark path')
cpp = replace_once(cpp, 'constexpr const char CONTROLLER_DIAG_PATH[] = "/missile-command-controller.txt";\n', '', 'remove controller diag path')

old_timing = '''// Gameplay, touch and e-ink are intentionally locked to one 100 ms cadence.
// There is no catch-up simulation and no frame running ahead of the panel:
// one cycle consumes input, advances the world exactly once, renders that exact
// state, then waits for the FAST refresh to complete before another cycle.
constexpr int64_t GAME_FRAME_US = 100000;
constexpr uint32_t BENCHMARK_BATCH_FRAMES = 100;
constexpr int EXPLOSION_PHASE_TICKS = 1;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};
FsFile benchmarkLogFile;
'''
new_timing = '''// Gameplay, touch and e-ink stay strictly locked 1:1. GAME_FRAME_US is only
// the minimum cycle gate; on the X4 Pro UC8279 the blocking FAST refresh
// (~590 ms measured) is slower and therefore sets the real visible cadence.
constexpr int64_t GAME_FRAME_US = 100000;

// Motion is tuned to the measured UC8279 physical frame while preserving the
// strict one-input / one-simulation / one-refresh contract.
constexpr uint16_t ENEMY_SPEED_SCALE = 6;
constexpr uint16_t PLAYER_MISSILE_SPEED = 500;
constexpr uint8_t EXPLOSION_PHASE_STEP = 3;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};
'''
cpp = replace_once(cpp, old_timing, new_timing, 'replace gameplay timing constants')

cpp = regex_once(
    cpp,
    r'\n\nconst char\* activeDisplayControllerName\(\) \{.*?\n\}\n\nRect headerRect',
    '\n\nRect headerRect',
    'remove controller diagnostic helpers',
)

# Shared Game Over geometry keeps draw and touch hit-box identical.
point_block = '''bool pointInRect(const Rect& rect, int x, int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}
'''
point_new = point_block + '''
Rect gameOverBox(const GfxRenderer& renderer) {
  const int width = std::min(380, renderer.getScreenWidth() - 36);
  constexpr int height = 170;
  return Rect{(renderer.getScreenWidth() - width) / 2,
              (renderer.getScreenHeight() - height) / 2, width, height};
}

Rect gameOverActionRect(const GfxRenderer& renderer) {
  const Rect box = gameOverBox(renderer);
  return Rect{box.x + 12, box.y + 106, box.width - 24, 48};
}
'''
cpp = replace_once(cpp, point_block, point_new, 'add game over geometry helpers')

on_enter_old = '''  pendingTap_ = false;
  pendingBack_ = false;
  benchmarkSampleArmed_.store(false);
  benchmarkFlushPending_.store(false);
  lastLogicUs_.store(0);
  lastCycleIntervalUs_.store(0);
  resetBenchmarkAccumulator();
  benchmarkLogFile.close();
  benchmarkLogOpen_ = false;
  benchmarkSessionStartUs_ = esp_timer_get_time();
  writeControllerDiagnostic();
  openBenchmarkLog();
  loadHighScore();
'''
on_enter_new = '''  pendingTap_ = false;
  pendingBack_ = false;
  loadHighScore();
'''
cpp = replace_once(cpp, on_enter_old, on_enter_new, 'clean onEnter instrumentation')

cpp = replace_once(
    cpp,
    '''void MissileCommandActivity::onExit() {
  if (benchmarkFlushPending_.load()) flushBenchmarkLog();
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  closeBenchmarkLog();
  Activity::onExit();
}
''',
    '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  Activity::onExit();
}
''',
    'clean onExit instrumentation',
)

cpp = replace_once(
    cpp,
    '''  // Capture input continuously, but consume it only at the next 100 ms game
  // frame. This gives touch exactly the same temporal state as simulation and
  // display instead of letting input or gameplay run ahead of the e-ink panel.
''',
    '''  // Capture input continuously, but consume it only at the next synchronized
  // game/display frame. Input, simulation and visible e-ink state never run ahead.
''',
    'update synchronized input comment',
)

cpp = replace_once(
    cpp,
    '''  // SD writes happen only between measured frames. Pausing here and resetting
  // the cadence afterwards keeps filesystem latency out of the timing samples.
  if (benchmarkFlushPending_.load() && !cycleRenderPending_.load()) {
    flushBenchmarkLog();
    lastCycleUs_ = esp_timer_get_time();
    return;
  }

''',
    '',
    'remove benchmark flush from gameplay loop',
)
cpp = replace_once(
    cpp,
    '''  const uint32_t cycleIntervalUs = static_cast<uint32_t>(now - lastCycleUs_);
  lastCycleUs_ = now;
''',
    '''  lastCycleUs_ = now;
''',
    'remove cycle timing sample',
)
cpp = replace_once(cpp, '  const int64_t logicStartUs = esp_timer_get_time();\n', '', 'remove logic timer start')
cpp = replace_once(
    cpp,
    '''  tickGame(now);
  const uint32_t logicUs = static_cast<uint32_t>(esp_timer_get_time() - logicStartUs);
  lastLogicUs_.store(logicUs);
  lastCycleIntervalUs_.store(cycleIntervalUs);
  if (viewMode_ != ViewMode::Playing) return;

  benchmarkSampleArmed_.store(true);
''',
    '''  tickGame(now);
  if (viewMode_ != ViewMode::Playing) return;

''',
    'remove benchmark sampling from gameplay loop',
)

# Touch-enabled Game Over return button, while retaining physical Back/Confirm.
cpp = regex_once(
    cpp,
    r'void MissileCommandActivity::loopGameOver\(\) \{.*?\n\}\n\nvoid MissileCommandActivity::activateRow',
    '''void MissileCommandActivity::loopGameOver() {
  const Rect header = headerRect(renderer, mappedInput);
  const bool headerBack = mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header);
  int tx = 0;
  int ty = 0;
  const bool touchReturn = mappedInput.hasTouchHardware() && !headerBack && mappedInput.wasScreenTapped(tx, ty) &&
                           pointInRect(gameOverActionRect(renderer), tx, ty);
  if (headerBack || touchReturn || mappedInput.wasPressed(MappedInputManager::Button::Back) ||
      mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
  }
}

void MissileCommandActivity::activateRow''',
    'replace game over input handling',
)

# Tune movement for the measured ~590 ms visible frame rather than the old
# theoretical 100 ms cadence.
cpp = replace_once(
    cpp,
    '''  // Speeds are per 100 ms synchronized frame. Scale from the previous 33 ms
  // cadence so real-world descent time stays approximately unchanged.
  slot->speed = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);
''',
    '''  // Keep approximately the intended real-world descent time at the measured
  // ~590 ms UC8279 visible cadence.
  const int baseSpeed = 12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3;
  slot->speed = static_cast<uint16_t>(baseSpeed * ENEMY_SPEED_SCALE);
''',
    'tune enemy speed',
)
cpp = replace_once(cpp, '  slot->speed = 140;\n', '  slot->speed = PLAYER_MISSILE_SPEED;\n', 'tune player speed')

cpp = replace_once(
    cpp,
    '''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    if (++explosion.phaseTicks < EXPLOSION_PHASE_TICKS) continue;
    explosion.phaseTicks = 0;
    if (++explosion.phase >= 7) explosion.active = false;
  }
''',
    '''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    if (static_cast<uint8_t>(explosion.phase + EXPLOSION_PHASE_STEP) >= 7) {
      explosion.active = false;
    } else {
      explosion.phase = static_cast<uint8_t>(explosion.phase + EXPLOSION_PHASE_STEP);
    }
  }
''',
    'shorten explosion animation',
)
cpp = replace_once(cpp, '    explosion.phaseTicks = 0;\n', '', 'remove explosion phase tick init')

cpp = regex_once(
    cpp,
    r'void MissileCommandActivity::renderPlaying\(\) \{.*?\n\}\n\nvoid MissileCommandActivity::renderGameOver',
    '''void MissileCommandActivity::renderPlaying() {
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  drawPlayingFrame();

  // Blocking FAST refresh is deliberate: the next simulation/input cycle cannot
  // begin until this exact synchronized frame has completed on the panel.
  renderer.displayBuffer(HalDisplay::FAST_REFRESH);
  cycleRenderPending_.store(false);
}

void MissileCommandActivity::renderGameOver''',
    'simplify renderPlaying',
)

cpp = regex_once(
    cpp,
    r'void MissileCommandActivity::renderGameOver\(\) \{.*?\n\}\n\n\nvoid MissileCommandActivity::resetBenchmarkAccumulator',
    '''void MissileCommandActivity::renderGameOver() {
  drawFullPlayingScene();
  drawPlayingFrame();
  const Rect box = gameOverBox(renderer);
  const Rect action = gameOverActionRect(renderer);
  renderer.fillRect(box.x, box.y, box.width, box.height, false);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 2, 8, true);
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 12, box.y + 18, box.width - 24, 36},
                   "Toutes les villes sont perdues");
  char scoreText[64];
  std::snprintf(scoreText, sizeof(scoreText), "Score final : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 12, box.y + 68, box.width - 24, 30}, scoreText);
  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Retour au menu");
  renderer.displayBuffer();
  sceneNeedsFullRedraw_ = true;
}


void MissileCommandActivity::resetBenchmarkAccumulator''',
    'make game over action visibly touchable',
)

cpp = regex_once(
    cpp,
    r'\n\nvoid MissileCommandActivity::resetBenchmarkAccumulator\(\) \{.*?\n\n bool MissileCommandActivity::saveGame\(\)',
    '\n\nbool MissileCommandActivity::saveGame()',
    'remove benchmark methods',
) if '\n\n bool MissileCommandActivity::saveGame()' in cpp else regex_once(
    cpp,
    r'\n\nvoid MissileCommandActivity::resetBenchmarkAccumulator\(\) \{.*?\n\nbool MissileCommandActivity::saveGame\(\)',
    '\n\nbool MissileCommandActivity::saveGame()',
    'remove benchmark methods',
)

# ---------------------------------------------------------------------------
# Header: remove benchmark-only state and obsolete explosion phase tick.
# ---------------------------------------------------------------------------
hpp = regex_once(
    hpp,
    r'\n\n  struct BenchmarkAccumulator \{.*?\n  \};\n\n  struct Explosion',
    '\n\n  struct Explosion',
    'remove benchmark structs',
)
hpp = replace_once(hpp, '    uint8_t phaseTicks = 0;\n', '', 'remove phaseTicks field')
hpp = regex_once(
    hpp,
    r'\n  // Timing samples cross the main gameplay task.*?  bool benchmarkLogOpen_ = false;\n',
    '\n',
    'remove benchmark state',
)
hpp = regex_once(
    hpp,
    r'\n  void resetBenchmarkAccumulator\(\);.*?  void flushBenchmarkLog\(\);\n',
    '\n',
    'remove benchmark declarations',
)

# Final invariants: no diagnostic/benchmark hooks remain, strict blocking FAST
# path remains, and the new touch/timing tuning is present.
for forbidden in ("BENCHMARK_PATH", "benchmarkLog", "benchmarkSample", "writeControllerDiagnostic", "CONTROLLER_DIAG_PATH", "phaseTicks"):
    if forbidden in cpp or forbidden in hpp:
        raise RuntimeError(f"forbidden final instrumentation remains: {forbidden}")

required_cpp = (
    "ENEMY_SPEED_SCALE = 6",
    "PLAYER_MISSILE_SPEED = 500",
    "EXPLOSION_PHASE_STEP = 3",
    "gameOverActionRect",
    "mappedInput.wasScreenTapped(tx, ty)",
    "renderer.displayBuffer(HalDisplay::FAST_REFRESH)",
    "cycleRenderPending_.store(false)",
)
for token in required_cpp:
    if token not in cpp:
        raise RuntimeError(f"missing final invariant: {token}")

CPP_PATH.write_text(cpp)
H_PATH.write_text(hpp)
print("Missile Command final app-only optimization staged")
