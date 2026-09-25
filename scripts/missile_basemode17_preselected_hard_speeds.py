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
# BaseMode17: preselect the complete hard-mode enemy speed sequence outside
# recurrent gameplay.
#
# Normal inter-wave path: startWave() runs while WaveComplete popup is visible,
# so every speed RNG pick for the next wave happens during that user pause.
# Continue also rebuilds the plan before gameplay resumes, fixing the runtime
# constants that are intentionally not serialized in the save file.
# ---------------------------------------------------------------------------

hdr = replace_once(
    hdr,
    "  std::array<uint16_t, 7> waveHardEnemySpeeds_{};\n"
    "  uint32_t waveSpawnIntervalUs_ = 0;\n",
    "  std::array<uint16_t, 7> waveHardEnemySpeeds_{};\n"
    "  std::array<uint16_t, 16> waveEnemySpawnSpeeds_{};\n"
    "  uint32_t waveSpawnIntervalUs_ = 0;\n",
    "preselected enemy speed plan state",
)

hdr = replace_once(
    hdr,
    "  void startWave();\n",
    "  void prepareWaveRuntimeConstants();\n"
    "  void startWave();\n",
    "prepare runtime constants declaration",
)
HDR.write_text(hdr)

helper = r'''void MissileCommandActivity::prepareWaveRuntimeConstants() {
  waveTargetCount_ = static_cast<uint16_t>(5 + difficulty_ * 2 + std::min<int>(wave_, 7));
  waveEnemySpeed_ = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);

  // Seven symmetric hard-mode bands: -25% .. +25%.
  constexpr uint8_t hardSpeedPct[7] = {75, 83, 92, 100, 108, 117, 125};
  for (size_t i = 0; i < waveHardEnemySpeeds_.size(); ++i) {
    waveHardEnemySpeeds_[i] = static_cast<uint16_t>(
        std::max<uint32_t>(1u, (static_cast<uint32_t>(waveEnemySpeed_) * hardSpeedPct[i] + 50u) / 100u));
  }

  // Preselect the ENTIRE next-wave speed sequence now. In the normal flow this
  // runs from loopWaveComplete() while the popup is displayed. Spawns therefore
  // do zero RNG and zero speed multiplications during active gameplay.
  waveEnemySpawnSpeeds_.fill(waveEnemySpeed_);
  if (difficulty_ == 2) {
    const size_t count = std::min<size_t>(waveTargetCount_, waveEnemySpawnSpeeds_.size());
    for (size_t i = 0; i < count; ++i) {
      const uint32_t pick = esp_random() % waveHardEnemySpeeds_.size();
      waveEnemySpawnSpeeds_[i] = waveHardEnemySpeeds_[pick];
    }
  }

  waveSpawnIntervalUs_ = static_cast<uint32_t>(
      std::max(420, 1150 - difficulty_ * 180 - static_cast<int>(wave_) * 45)) * 1000u;
  waveAmmoCapacity_ = static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5));
}

'''

start_sig = "void MissileCommandActivity::startWave() {"
start = cpp.find(start_sig)
if start < 0:
    raise SystemExit("startWave not found")

# BaseMode15/16 injected all runtime-constant calculations before the wave stat
# reset. Replace only that generated block; keep explosion-cache preparation and
# the rest of startWave untouched.
body_start = cpp.find("\n", start) + 1
stats_anchor = "  waveShotsFired_ = 0;\n"
stats = cpp.find(stats_anchor, body_start)
if stats < 0:
    raise SystemExit("startWave stats reset anchor not found")

cpp = cpp[:start] + helper + cpp[start:]
# start index moved by helper length.
start = cpp.find(start_sig, start + len(helper))
body_start = cpp.find("\n", start) + 1
stats = cpp.find(stats_anchor, body_start)
if stats < 0:
    raise SystemExit("relocated startWave stats reset anchor not found")
cpp = cpp[:body_start] + "  prepareWaveRuntimeConstants();\n" + cpp[stats:]

old_spawn = r'''  if (difficulty_ == 2) {
    // One choice per spawned missile; no recurrent RNG or multiplier.
    const uint32_t speedPick = esp_random() % waveHardEnemySpeeds_.size();
    slot->speed = waveHardEnemySpeeds_[speedPick];
  } else {
    slot->speed = waveEnemySpeed_;
  }
'''
new_spawn = r'''  if (difficulty_ == 2 && enemiesSpawned_ < waveEnemySpawnSpeeds_.size()) {
    // enemiesSpawned_ is incremented below, so it is the exact preselected
    // sequence index for this spawn. No RNG or multiplication in gameplay.
    slot->speed = waveEnemySpawnSpeeds_[static_cast<size_t>(enemiesSpawned_)];
  } else {
    slot->speed = waveEnemySpeed_;
  }
'''
cpp = replace_once(cpp, old_spawn, new_spawn, "spawn uses preselected speed")

# Runtime constants are not serialized. Rebuild them on Continue before active
# gameplay resumes. This also preselects the hard-mode speed plan outside the
# recurrent loop and resets non-persisted wave-only stats.
continue_sig = "void MissileCommandActivity::continueGame() {\n"
cpp = replace_once(
    cpp,
    continue_sig,
    continue_sig +
    "  prepareWaveRuntimeConstants();\n"
    "  waveShotsFired_ = 0;\n"
    "  waveEnemyKills_ = 0;\n",
    "continue runtime preparation",
)

cpp = cpp.replace("/missile-command-bm16-hard-speed-variance-bench.csv",
                  "/missile-command-bm17-preselected-hard-speeds-bench.csv")
cpp = cpp.replace("/missile-command-bm16-hard-speed-variance-trace.csv",
                  "/missile-command-bm17-preselected-hard-speeds-trace.csv")
cpp = cpp.replace("bm16-hard-speed-variance-started", "bm17-preselected-hard-speeds-started")
cpp = cpp.replace("bm16-hard-speed-variance,%lu,%lu,%lu,%lu,%lu",
                  "bm17-preselected-hard-speeds,%lu,%lu,%lu,%lu,%lu")
cpp = cpp.replace("MISSILE-BM16-HARD-SPEED", "MISSILE-BM17-PRESELECTED-SPEEDS")

CPP.write_text(cpp)
print("Missile BaseMode17: complete hard-mode speed sequence preselected outside gameplay")
