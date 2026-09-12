from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HPP = Path("src/activities/home/MissileCommandActivity.h")

cpp = CPP.read_text()
hpp = HPP.read_text()


def one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


# Restore gameplay constants exactly to the diagnostic build. Do not change
# rendering, frame synchronization, trails, spawn cadence, geometry or UI.
cpp = one(
    cpp,
    '''// Gameplay, touch and e-ink stay strictly locked 1:1. GAME_FRAME_US is only
// the minimum cycle gate; on the X4 Pro UC8279 the blocking FAST refresh
// (~590 ms measured) is slower and therefore sets the real visible cadence.
constexpr int64_t GAME_FRAME_US = 100000;

// Motion is tuned to the measured UC8279 physical frame while preserving the
// strict one-input / one-simulation / one-refresh contract.
constexpr uint16_t ENEMY_SPEED_SCALE = 6;
constexpr uint16_t PLAYER_MISSILE_SPEED = 500;
constexpr uint8_t EXPLOSION_PHASE_STEP = 3;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};
''',
    '''// Gameplay, touch and e-ink are intentionally locked to one 100 ms cadence.
// There is no catch-up simulation and no frame running ahead of the panel:
// one cycle consumes input, advances the world exactly once, renders that exact
// state, then waits for the FAST refresh to complete before another cycle.
constexpr int64_t GAME_FRAME_US = 100000;
constexpr int EXPLOSION_PHASE_TICKS = 1;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};
''',
    "diagnostic gameplay constants",
)

cpp = one(
    cpp,
    '''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    if (static_cast<uint8_t>(explosion.phase + EXPLOSION_PHASE_STEP) >= 7) {
      explosion.active = false;
    } else {
      explosion.phase = static_cast<uint8_t>(explosion.phase + EXPLOSION_PHASE_STEP);
    }
  }
''',
    '''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    if (++explosion.phaseTicks < EXPLOSION_PHASE_TICKS) continue;
    explosion.phaseTicks = 0;
    if (++explosion.phase >= 7) explosion.active = false;
  }
''',
    "diagnostic explosion cadence",
)

cpp = one(
    cpp,
    '''  // Keep approximately the intended real-world descent time at the measured
  // ~590 ms UC8279 visible cadence.
  const int baseSpeed = 12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3;
  slot->speed = static_cast<uint16_t>(baseSpeed * ENEMY_SPEED_SCALE);
''',
    '''  // Speeds are per 100 ms synchronized frame. Scale from the previous 33 ms
  // cadence so real-world descent time stays approximately unchanged.
  slot->speed = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);
''',
    "diagnostic enemy speed",
)

cpp = one(
    cpp,
    '''  slot->speed = PLAYER_MISSILE_SPEED;
''',
    '''  slot->speed = 140;
''',
    "diagnostic player speed",
)

cpp = one(
    cpp,
    '''    explosion.phase = 0;
    explosion.active = true;
''',
    '''    explosion.phase = 0;
    explosion.phaseTicks = 0;
    explosion.active = true;
''',
    "diagnostic explosion initialization",
)

hpp = one(
    hpp,
    '''  struct Explosion {
    int16_t x = 0;
    int16_t y = 0;
    uint8_t phase = 0;
    bool active = false;
  };
''',
    '''  struct Explosion {
    int16_t x = 0;
    int16_t y = 0;
    uint8_t phase = 0;
    uint8_t phaseTicks = 0;
    bool active = false;
  };
''',
    "diagnostic explosion state",
)

# Guardrails: diagnostic instrumentation must stay removed, while the tactile
# Game Over return hitbox from the clean-up commit must remain present.
for forbidden in (
    "BENCHMARK_PATH",
    "CONTROLLER_DIAG_PATH",
    "writeControllerDiagnostic",
    "openBenchmarkLog",
    "recordBenchmarkSample",
    "benchmarkSampleArmed_",
    "benchmarkFlushPending_",
    "BoardConfig.h",
):
    if forbidden in cpp or forbidden in hpp:
        raise RuntimeError(f"diagnostic residue remains: {forbidden}")

required = (
    "gameOverActionRect(renderer)",
    "mappedInput.wasScreenTapped(tx, ty)",
    "pointInRect(gameOverActionRect(renderer), tx, ty)",
    "renderer.displayBuffer(HalDisplay::FAST_REFRESH)",
    "GAME_FRAME_US = 100000",
)
for token in required:
    if token not in cpp:
        raise RuntimeError(f"required behavior missing: {token}")

CPP.write_text(cpp)
HPP.write_text(hpp)
print("Missile Command diagnostic-base cleanup staged")
