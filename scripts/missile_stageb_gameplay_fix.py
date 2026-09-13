from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
HDR = "src/activities/home/MissileCommandActivity.h"

# Stage B shortened the blocking refresh from about 592 ms/cycle to roughly
# 440-470 ms/cycle. Missile speeds in the stable game are increments PER FRAME,
# so applying the same increments more often changes the gameplay. Preserve the
# stable real-world timing while keeping every Stage-B display refresh.
replace_once(
    CPP,
    "constexpr int64_t GAME_FRAME_US = 100000;\nconstexpr int EXPLOSION_PHASE_TICKS = 1;\n",
    "constexpr int64_t GAME_FRAME_US = 100000;\n"
    "// Stable pre-window build measured ~591.6 ms per synchronized game/display\n"
    "// cycle. Missile speed values and explosion phases are legacy per-frame\n"
    "// increments, so normalize them to that wall-clock duration rather than to\n"
    "// the now-faster Stage-B refresh rate. This preserves gameplay speed while\n"
    "// allowing the panel to render every optimized frame.\n"
    "constexpr uint32_t LEGACY_GAMEPLAY_FRAME_US = 592000;\n",
)

replace_once(
    HDR,
    "    uint16_t progress = 0;\n    uint16_t speed = 0;\n    bool active = false;\n",
    "    uint16_t progress = 0;\n"
    "    uint16_t speed = 0;\n"
    "    // Fractional legacy-frame progress carried between faster Stage-B frames.\n"
    "    uint32_t progressRemainderUs = 0;\n"
    "    bool active = false;\n",
)

replace_once(
    HDR,
    "    uint8_t phase = 0;\n    uint8_t phaseTicks = 0;\n    bool active = false;\n",
    "    uint8_t phase = 0;\n"
    "    // Explosion phases keep the same real duration as the stable build.\n"
    "    uint32_t phaseElapsedUs = 0;\n"
    "    bool active = false;\n",
)

replace_once(
    HDR,
    "  void tickGame(int64_t nowUs);\n",
    "  void tickGame(int64_t nowUs, uint32_t gameplayElapsedUs);\n",
)

replace_once(
    CPP,
    "  const int64_t now = esp_timer_get_time();\n"
    "  if (lastCycleUs_ == 0) lastCycleUs_ = now;\n"
    "  if (now - lastCycleUs_ < GAME_FRAME_US) return;\n"
    "  lastCycleUs_ = now;\n",
    "  const int64_t now = esp_timer_get_time();\n"
    "  if (lastCycleUs_ == 0) {\n"
    "    lastCycleUs_ = now;\n"
    "    return;\n"
    "  }\n"
    "  const int64_t cycleElapsedUs = now - lastCycleUs_;\n"
    "  if (cycleElapsedUs < GAME_FRAME_US) return;\n"
    "  lastCycleUs_ = now;\n"
    "  // Keep the original no-catch-up rule: a stall may never advance more than\n"
    "  // one legacy frame of gameplay. Normal Stage-B frames are shorter and get\n"
    "  // a proportionally smaller movement increment instead.\n"
    "  const uint32_t gameplayElapsedUs = static_cast<uint32_t>(\n"
    "      std::min<int64_t>(cycleElapsedUs, LEGACY_GAMEPLAY_FRAME_US));\n",
)

replace_once(CPP, "  tickGame(now);\n", "  tickGame(now, gameplayElapsedUs);\n")

replace_once(
    CPP,
    "void MissileCommandActivity::tickGame(int64_t nowUs) {\n",
    "void MissileCommandActivity::tickGame(int64_t nowUs, uint32_t gameplayElapsedUs) {\n"
    "  const auto advanceMissile = [gameplayElapsedUs](Missile& missile) {\n"
    "    const uint64_t scaled = static_cast<uint64_t>(missile.speed) * gameplayElapsedUs +\n"
    "                            missile.progressRemainderUs;\n"
    "    const uint32_t delta = static_cast<uint32_t>(scaled / LEGACY_GAMEPLAY_FRAME_US);\n"
    "    missile.progressRemainderUs = static_cast<uint32_t>(scaled % LEGACY_GAMEPLAY_FRAME_US);\n"
    "    missile.progress = static_cast<uint16_t>(std::min<uint32_t>(1000, missile.progress + delta));\n"
    "  };\n",
)

# Both enemy and player loops used the same per-frame increment expression.
for _ in range(2):
    replace_once(
        CPP,
        "    missile.progress = static_cast<uint16_t>(std::min<int>(1000, missile.progress + missile.speed));\n",
        "    advanceMissile(missile);\n",
    )

replace_once(
    CPP,
    "  for (auto& explosion : explosions_) {\n"
    "    if (!explosion.active) continue;\n"
    "    if (++explosion.phaseTicks < EXPLOSION_PHASE_TICKS) continue;\n"
    "    explosion.phaseTicks = 0;\n"
    "    if (++explosion.phase >= 7) explosion.active = false;\n"
    "  }\n",
    "  for (auto& explosion : explosions_) {\n"
    "    if (!explosion.active) continue;\n"
    "    explosion.phaseElapsedUs += gameplayElapsedUs;\n"
    "    if (explosion.phaseElapsedUs < LEGACY_GAMEPLAY_FRAME_US) continue;\n"
    "    explosion.phaseElapsedUs -= LEGACY_GAMEPLAY_FRAME_US;\n"
    "    if (++explosion.phase >= 7) explosion.active = false;\n"
    "  }\n",
)

replace_once(
    CPP,
    "  slot->progress = 0;\n"
    "  // Speeds are per 100 ms synchronized frame. Scale from the previous 33 ms\n",
    "  slot->progress = 0;\n"
    "  slot->progressRemainderUs = 0;\n"
    "  // Speeds are legacy per-frame increments; tickGame() now time-normalizes\n"
    "  // them so Stage-B display acceleration does not accelerate gameplay.\n"
    "  // Scale from the previous 33 ms\n",
)

replace_once(
    CPP,
    "  slot->progress = 0;\n  slot->speed = 140;\n",
    "  slot->progress = 0;\n  slot->progressRemainderUs = 0;\n  slot->speed = 140;\n",
)

replace_once(
    CPP,
    "    explosion.phase = 0;\n    explosion.phaseTicks = 0;\n    explosion.active = true;\n",
    "    explosion.phase = 0;\n    explosion.phaseElapsedUs = 0;\n    explosion.active = true;\n",
)

# The benchmark has already served its purpose. Do not pause or perturb normal
# gameplay on first launch anymore; keep the Stage-B window refresh itself.
replace_once(
    CPP,
    "    static bool windowBenchmarkDone = false;\n"
    "    if (!windowBenchmarkDone) {\n"
    "      windowBenchmarkDone = true;\n"
    "      runUc8279WindowBenchmark();\n"
    "      lastCycleUs_ = esp_timer_get_time();\n"
    "    }\n",
    "",
)

print("Missile Stage-B gameplay timing normalized to stable legacy cadence")
