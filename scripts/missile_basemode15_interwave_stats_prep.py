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
# Wave stats + precomputed wave parameters.
# These four gameplay parameters used to be recomputed in recurrent paths.
# startWave() now calculates them once; in the inter-wave flow startWave() runs
# while the user is reading the popup, so the work is outside active gameplay.
# ---------------------------------------------------------------------------
hdr = replace_once(
    hdr,
    "  uint16_t completedWave_ = 0;\n"
    "  uint16_t waveEndAmmoRemaining_ = 0;\n"
    "  uint8_t waveEndObjectives_ = 0;\n"
    "  bool interWavePrepPending_ = false;\n",
    "  uint16_t completedWave_ = 0;\n"
    "  uint16_t waveEndAmmoRemaining_ = 0;\n"
    "  uint8_t waveEndObjectives_ = 0;\n"
    "  uint16_t waveShotsFired_ = 0;\n"
    "  uint16_t waveEnemyKills_ = 0;\n"
    "  uint16_t completedWaveShotsFired_ = 0;\n"
    "  uint16_t completedWaveEnemyKills_ = 0;\n"
    "  uint16_t completedWaveEfficiencyPct_ = 0;\n"
    "  uint16_t waveTargetCount_ = 0;\n"
    "  uint16_t waveEnemySpeed_ = 0;\n"
    "  uint32_t waveSpawnIntervalUs_ = 0;\n"
    "  uint8_t waveAmmoCapacity_ = 10;\n"
    "  bool interWavePrepPending_ = false;\n",
    "wave stats/prep state",
)
HDR.write_text(hdr)

# Compute wave constants once in startWave(), before arrays are reset/refilled.
start_marker = "void MissileCommandActivity::startWave() {"
start = cpp.find(start_marker)
if start < 0:
    raise SystemExit("startWave not found")
brace = cpp.find("\n", start) + 1
prep = r'''  waveTargetCount_ = static_cast<uint16_t>(5 + difficulty_ * 2 + std::min<int>(wave_, 7));
  waveEnemySpeed_ = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);
  waveSpawnIntervalUs_ = static_cast<uint32_t>(
      std::max(420, 1150 - difficulty_ * 180 - static_cast<int>(wave_) * 45)) * 1000u;
  waveAmmoCapacity_ = static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5));
  waveShotsFired_ = 0;
  waveEnemyKills_ = 0;
'''
cpp = cpp[:brace] + prep + cpp[brace:]

# startWave's ammo refill uses the already prepared capacity.
old_ammo = "  const uint8_t waveAmmo = static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5));\n"
if old_ammo not in cpp:
    raise SystemExit("wave ammo computation not found")
cpp = cpp.replace(old_ammo, "  const uint8_t waveAmmo = waveAmmoCapacity_;\n", 1)

# Recurrent tick / wave-finish target count uses prepared value.
target_expr = "  const int targetCount = 5 + difficulty_ * 2 + std::min<int>(wave_, 7);\n"
if cpp.count(target_expr) < 2:
    raise SystemExit(f"expected recurrent target count twice, found {cpp.count(target_expr)}")
cpp = cpp.replace(target_expr, "  const int targetCount = waveTargetCount_;\n", 2)

# Spawn speed and interval become simple field loads.
old_speed = "  slot->speed = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);\n"
if old_speed not in cpp:
    raise SystemExit("enemy speed expression not found")
cpp = cpp.replace(old_speed, "  slot->speed = waveEnemySpeed_;\n", 1)

old_delay = (
    "  const int delayMs = std::max(420, 1150 - difficulty_ * 180 - static_cast<int>(wave_) * 45);\n"
    "  nextSpawnUs_ = nowUs + static_cast<int64_t>(delayMs) * 1000;\n"
)
if old_delay not in cpp:
    raise SystemExit("spawn delay expression not found")
cpp = cpp.replace(
    old_delay,
    "  nextSpawnUs_ = nowUs + static_cast<int64_t>(waveSpawnIntervalUs_);\n",
    1,
)

# Turret bargraph no longer recomputes ammo capacity every frame.
old_gauge_cap = "    const int capacity = 10 + std::min<int>(wave_ / 2, 5);\n"
if old_gauge_cap not in cpp:
    raise SystemExit("bargraph capacity expression not found")
cpp = cpp.replace(old_gauge_cap, "    const int capacity = waveAmmoCapacity_;\n", 1)

# Count only accepted launches (after ammo validation and decrement).
ammo_dec = "  --ammo_[static_cast<size_t>(battery)];\n"
if ammo_dec not in cpp:
    raise SystemExit("player ammo decrement not found")
cpp = cpp.replace(
    ammo_dec,
    ammo_dec + "  ++waveShotsFired_;\n",
    1,
)

# Count only actual enemy destructions in resolveCollisions; impacts do not count.
hit_anchor = (
    "      enemy.active = false;\n"
    "      ++enemiesResolved_;\n"
    "      score_ += static_cast<uint32_t>(25 + wave_ * 2);\n"
)
if hit_anchor not in cpp:
    raise SystemExit("enemy collision resolution anchor not found")
cpp = cpp.replace(
    hit_anchor,
    "      enemy.active = false;\n"
    "      ++enemiesResolved_;\n"
    "      ++waveEnemyKills_;\n"
    "      score_ += static_cast<uint32_t>(25 + wave_ * 2);\n",
    1,
)

# Capture stats BEFORE startWave() resets the counters during inter-wave prep.
capture_anchor = (
    "  completedWave_ = wave_;\n"
    "  waveEndAmmoRemaining_ = 0;\n"
)
if capture_anchor not in cpp:
    raise SystemExit("wave-complete capture anchor not found")
cpp = cpp.replace(
    capture_anchor,
    "  completedWave_ = wave_;\n"
    "  completedWaveShotsFired_ = waveShotsFired_;\n"
    "  completedWaveEnemyKills_ = waveEnemyKills_;\n"
    "  completedWaveEfficiencyPct_ = completedWaveShotsFired_ == 0 ? 0 :\n"
    "      static_cast<uint16_t>((static_cast<uint32_t>(completedWaveEnemyKills_) * 100u +\n"
    "                             completedWaveShotsFired_ / 2u) / completedWaveShotsFired_);\n"
    "  waveEndAmmoRemaining_ = 0;\n",
    1,
)

# Re-layout compact popup: combine existing basic stats into two rows and add
# destroyed/tirs/efficiency without growing the card or changing refresh cost.
old_stats = r'''  std::snprintf(line, sizeof(line), "Score : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 51, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "Record : %lu", static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 79, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "Munitions : %u", static_cast<unsigned>(waveEndAmmoRemaining_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 107, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "%s : %u",
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 135, box.width - 36, 25}, line);
'''
new_stats = r'''  std::snprintf(line, sizeof(line), "Score %lu   Record %lu",
                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 48, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Munitions %u   %s %u",
                static_cast<unsigned>(waveEndAmmoRemaining_),
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 76, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Tirs %u   Detruits %u",
                static_cast<unsigned>(completedWaveShotsFired_),
                static_cast<unsigned>(completedWaveEnemyKills_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 104, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Efficacite : %u%%",
                static_cast<unsigned>(completedWaveEfficiencyPct_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 132, box.width - 36, 24}, line);
'''
if old_stats not in cpp:
    raise SystemExit("BaseMode13 compact popup stats block not found")
cpp = cpp.replace(old_stats, new_stats, 1)

# Distinct identity.
cpp = cpp.replace("/missile-command-bm14-popup-local-refresh-bench.csv",
                  "/missile-command-bm15-interwave-stats-prep-bench.csv")
cpp = cpp.replace("/missile-command-bm14-popup-local-refresh-trace.csv",
                  "/missile-command-bm15-interwave-stats-prep-trace.csv")
cpp = cpp.replace("bm14-popup-local-refresh-started", "bm15-interwave-stats-prep-started")
cpp = cpp.replace("bm14-popup-local-refresh,%lu,%lu,%lu,%lu,%lu",
                  "bm15-interwave-stats-prep,%lu,%lu,%lu,%lu,%lu")
cpp = cpp.replace("MISSILE-BM14-POPUP-LOCAL", "MISSILE-BM15-STATS-PREP")

CPP.write_text(cpp)
print("Missile BaseMode15: inter-wave combat stats + prepared recurrent wave constants applied")
