from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:220]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
HDR = "src/activities/home/MissileCommandActivity.h"

# Applied after the validated A2-Lite + PLL0F + sparse-DTM + Trail64 Fade
# + menu scrub lifecycle patches. Keep the display/controller path untouched.
#
# The old HUD was one centered sentence. When its width changed, all following
# labels could move, broadening the dirty bbox and repeatedly redriving the whole
# status strip. Replace it with four fixed cells. Only the Score value is updated
# during ordinary gameplay; Record changes only after it is beaten. Wave/Cities
# are redrawn only on a full gameplay scene (new/continued game, wave boundary).

replace_once(
    HDR,
    "  bool menuScrubPending_ = false;\n",
    "  bool menuScrubPending_ = false;\n"
    "  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;\n",
)

hud_helpers = r'''
constexpr int MISSILE_HUD_COLUMNS = 4;

Rect missileHudCell(const Rect& status, int column) {
  const int left = status.x + (status.width * column) / MISSILE_HUD_COLUMNS;
  const int right = status.x + (status.width * (column + 1)) / MISSILE_HUD_COLUMNS;
  return Rect{left, status.y, std::max(1, right - left), status.height};
}

Rect missileHudValueRect(const Rect& status, int column) {
  const Rect cell = missileHudCell(status, column);
  // Labels use the left 52%; the numeric value is right-aligned in the rest.
  const int valueX = cell.x + (cell.width * 52) / 100;
  const int right = cell.x + cell.width - 3;
  return Rect{valueX, cell.y + 2, std::max(1, right - valueX), std::max(1, cell.height - 4)};
}

void drawMissileHudLabel(GfxRenderer& renderer, const Rect& status, int column, const char* label) {
  const Rect cell = missileHudCell(status, column);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int y = cell.y + std::max(0, (cell.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, cell.x + 5, y, label);
}

void drawMissileHudValue(GfxRenderer& renderer, const Rect& status, int column, const char* value) {
  const Rect valueRect = missileHudValueRect(status, column);
  renderer.fillRect(valueRect.x, valueRect.y, valueRect.width, valueRect.height, false);
  const int w = renderer.getTextWidth(UI_10_FONT_ID, value);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int x = std::max(valueRect.x, valueRect.x + valueRect.width - w);
  const int y = valueRect.y + std::max(0, (valueRect.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, value);
}

'''
replace_once(
    CPP,
    "}  // namespace\n\nMissileCommandActivity::MissileCommandActivity",
    hud_helpers + "}  // namespace\n\nMissileCommandActivity::MissileCommandActivity",
)

old_full = '''  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);\n  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);\n'''
new_full = '''  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);\n\n  // Stable HUD table. Put the frequently changing score near the horizontal\n  // centre so score-only updates are less likely to widen the gameplay bbox.\n  for (int column = 1; column < MISSILE_HUD_COLUMNS; ++column) {\n    const int x = geometry.status.x + (geometry.status.width * column) / MISSILE_HUD_COLUMNS;\n    renderer.drawLine(x, geometry.status.y + 2, x, geometry.status.y + geometry.status.height - 3, 1, true);\n  }\n  drawMissileHudLabel(renderer, geometry.status, 0, "Vague");\n  drawMissileHudLabel(renderer, geometry.status, 1, "Score");\n  drawMissileHudLabel(renderer, geometry.status, 2, "Record");\n  drawMissileHudLabel(renderer, geometry.status, 3, "Villes");\n\n  if (score_ > highScore_) highScore_ = score_;\n  char hudValue[16];\n  std::snprintf(hudValue, sizeof(hudValue), "%u", static_cast<unsigned>(wave_));\n  drawMissileHudValue(renderer, geometry.status, 0, hudValue);\n  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));\n  drawMissileHudValue(renderer, geometry.status, 1, hudValue);\n  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));\n  drawMissileHudValue(renderer, geometry.status, 2, hudValue);\n  std::snprintf(hudValue, sizeof(hudValue), "%d", aliveCityCount());\n  drawMissileHudValue(renderer, geometry.status, 3, hudValue);\n  hudScoreDrawn_ = score_;\n  hudHighScoreDrawn_ = highScore_;\n\n  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);\n'''
replace_once(CPP, old_full, new_full)

old_status = '''  renderer.fillRect(geometry.status.x + 2, geometry.status.y + 2,\n                    geometry.status.width - 4, geometry.status.height - 4, false);\n  char status[96];\n  std::snprintf(status, sizeof(status), "Score %lu   Record %lu   Vague %u   Villes %d",\n                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_),\n                static_cast<unsigned>(wave_), aliveCityCount());\n  drawCenteredText(renderer, UI_10_FONT_ID, geometry.status, status);\n'''
new_status = '''  // Incremental HUD: do not erase/recompose the whole strip each frame. The\n  // static labels, separators, wave and city count remain untouched until the\n  // next full gameplay redraw (notably a wave boundary).\n  if (score_ > highScore_) highScore_ = score_;\n  char hudValue[16];\n  if (hudScoreDrawn_ != score_) {\n    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));\n    drawMissileHudValue(renderer, geometry.status, 1, hudValue);\n    hudScoreDrawn_ = score_;\n  }\n  if (hudHighScoreDrawn_ != highScore_) {\n    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));\n    drawMissileHudValue(renderer, geometry.status, 2, hudValue);\n    hudHighScoreDrawn_ = highScore_;\n  }\n'''
replace_once(CPP, old_status, new_status)

# Give the consolidated candidate its own benchmark file/profile.
replace_once(
    CPP,
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-clean-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-hud-table-bench.csv";',
)
replace_once(
    CPP,
    'Storage.openFileForWrite("MISSILE-A2-SPARSE-TRAIL64", BENCH_PATH, file)',
    'Storage.openFileForWrite("MISSILE-A2-SPARSE-HUD", BENCH_PATH, file)',
)
replace_once(
    CPP,
    'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-clean-started,0,0,0,0,0\\n";',
    'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-hud-table-started,0,0,0,0,0\\n";',
)
replace_once(
    CPP,
    'Storage.openFileForWrite("MISSILE-A2-SPARSE-TRAIL64", BENCH_PATH, file)',
    'Storage.openFileForWrite("MISSILE-A2-SPARSE-HUD", BENCH_PATH, file)',
)
replace_once(
    CPP,
    '"game-a2-lite-pll0f-sparse-trail64-fade-clean,%lu,%lu,%lu,%lu,%lu\\n",',
    '"game-a2-lite-pll0f-sparse-trail64-fade-hud-table,%lu,%lu,%lu,%lu,%lu\\n",',
)

print("Missile fixed-cell HUD table + score-only incremental updates applied")
