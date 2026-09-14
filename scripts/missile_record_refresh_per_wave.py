from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  if (hudHighScoreDrawn_ != highScore_) {
    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));
    drawMissileHudValue(renderer, geometry.status, 1, hudValue);
    hudHighScoreDrawn_ = highScore_;
  }
'''
if old not in text:
    raise SystemExit("incremental Record HUD block not found")
text = text.replace(old, "", 1)

# Keep logical highScore_ updates immediate; only its visual HUD refresh is
# deferred until drawFullPlayingScene(), which already runs on wave boundaries.
# Give this A/B candidate a distinct benchmark identity.
text = text.replace(
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave-bench.csv";',
    1,
)
text = text.replace(
    'Storage.openFileForWrite("MISSILE-A2-HEADER-CLEAN", BENCH_PATH, file)',
    'Storage.openFileForWrite("MISSILE-A2-RECORD-WAVE", BENCH_PATH, file)',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave-started',
    1,
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave,%lu,%lu,%lu,%lu,%lu',
    1,
)

CPP.write_text(text)
print("Missile Record display now refreshes only on full scene / wave redraw")
