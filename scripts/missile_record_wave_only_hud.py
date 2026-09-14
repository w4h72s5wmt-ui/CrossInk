from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old_record = r'''  if (hudHighScoreDrawn_ != highScore_) {
    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));
    drawMissileHudValue(renderer, geometry.status, 1, hudValue);
    hudHighScoreDrawn_ = highScore_;
  }
'''
new_record = r'''  // Keep the logical high score current for persistence, but leave the displayed
  // Record fixed for the duration of the wave. drawFullPlayingScene() refreshes
  // it (and hudHighScoreDrawn_) on the next full redraw / wave boundary.
'''
if old_record not in text:
    raise SystemExit("incremental Record HUD block not found")
text = text.replace(old_record, new_record, 1)

replacements = {
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-bench.csv";':
        'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-record-wave-bench.csv";',
    'Storage.openFileForWrite("MISSILE-A2-HEADER-CLEAN", BENCH_PATH, file)':
        'Storage.openFileForWrite("MISSILE-A2-RECORD-WAVE", BENCH_PATH, file)',
    'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-started,0,0,0,0,0\\n";':
        'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-record-wave-started,0,0,0,0,0\\n";',
    '"game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean,%lu,%lu,%lu,%lu,%lu\\n",':
        '"game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-record-wave,%lu,%lu,%lu,%lu,%lu\\n",',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"benchmark anchor not found: {old}")
    text = text.replace(old, new)

CPP.write_text(text)
print("Missile Record display now refreshes only on full scene/wave redraw; logical highScore stays live")
