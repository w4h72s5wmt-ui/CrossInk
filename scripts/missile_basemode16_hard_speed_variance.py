from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")

cpp = CPP.read_text()
hdr = HDR.read_text()

def replace_once(text, old, new, name):
    if old not in text:
        raise SystemExit(f"{name} anchor not found")
    return text.replace(old, new, 1)

# ---------------------------------------------------------------------------
# BaseMode16: hard-mode enemy speed variance.
#
# Easy/Normal stay bit-for-bit on the accepted waveEnemySpeed_ behavior.
# Hard gets seven precomputed speed variants spanning 80..120% with a mean of
# exactly 100%. The only recurrent work is one RNG selection when an enemy is
# spawned; there is no extra per-frame math.
# ---------------------------------------------------------------------------

hdr = replace_once(
    hdr,
    "  uint16_t waveEnemySpeed_ = 0;\n"
    "  uint32_t waveSpawnIntervalUs_ = 0;\n",
    "  uint16_t waveEnemySpeed_ = 0;\n"
    "  std::array<uint16_t, 7> waveHardEnemySpeeds_{};\n"
    "  uint32_t waveSpawnIntervalUs_ = 0;\n",
    "hard speed variants state",
)
HDR.write_text(hdr)

prep_anchor = (
    "  waveEnemySpeed_ = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);\n"
    "  waveSpawnIntervalUs_ = static_cast<uint32_t>(\n"
)
prep_replacement = (
    "  waveEnemySpeed_ = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);\n"
    "  // Seven symmetric hard-mode speed bands. Their percentages sum to 700,\n"
    "  // so the average enemy speed remains exactly the accepted baseline.\n"
    "  constexpr uint8_t hardSpeedPct[7] = {80, 87, 93, 100, 107, 113, 120};\n"
    "  for (size_t i = 0; i < waveHardEnemySpeeds_.size(); ++i) {\n"
    "    waveHardEnemySpeeds_[i] = static_cast<uint16_t>(\n"
    "        std::max<uint32_t>(1u, (static_cast<uint32_t>(waveEnemySpeed_) * hardSpeedPct[i] + 50u) / 100u));\n"
    "  }\n"
    "  waveSpawnIntervalUs_ = static_cast<uint32_t>(\n"
)
cpp = replace_once(cpp, prep_anchor, prep_replacement, "precompute hard speed variants")

cpp = replace_once(
    cpp,
    "  slot->speed = waveEnemySpeed_;\n",
    "  if (difficulty_ == 2) {\n"
    "    // One choice per spawned missile; no recurrent RNG or multiplier.\n"
    "    const uint32_t speedPick = esp_random() % waveHardEnemySpeeds_.size();\n"
    "    slot->speed = waveHardEnemySpeeds_[speedPick];\n"
    "  } else {\n"
    "    slot->speed = waveEnemySpeed_;\n"
    "  }\n",
    "hard-mode spawn speed selection",
)

cpp = cpp.replace("/missile-command-bm15-interwave-stats-prep-bench.csv",
                  "/missile-command-bm16-hard-speed-variance-bench.csv")
cpp = cpp.replace("/missile-command-bm15-interwave-stats-prep-trace.csv",
                  "/missile-command-bm16-hard-speed-variance-trace.csv")
cpp = cpp.replace("bm15-interwave-stats-prep-started", "bm16-hard-speed-variance-started")
cpp = cpp.replace("bm15-interwave-stats-prep,%lu,%lu,%lu,%lu,%lu",
                  "bm16-hard-speed-variance,%lu,%lu,%lu,%lu,%lu")
cpp = cpp.replace("MISSILE-BM15-STATS-PREP", "MISSILE-BM16-HARD-SPEED")

CPP.write_text(cpp)
print("Missile BaseMode16: hard-mode enemy speed variance applied")
