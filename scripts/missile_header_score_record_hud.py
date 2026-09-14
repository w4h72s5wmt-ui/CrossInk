from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:240]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
HDR = "src/activities/home/MissileCommandActivity.h"

# Applied after missile_sparse_trail64_hud_table.py.
# Keep the controller/sparse/Trail64 path unchanged. This is layout-only:
#   header: Missile Command + fixed wave metadata + incrementally updated city number
#   status: two wide Score / Record cells
#   ordinary score updates touch only the numeric value rectangle

replace_once(
    HDR,
    "  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;\n",
    "  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  int hudCitiesDrawn_ = -1;\n",
)

replace_once(CPP, "constexpr int MISSILE_HUD_COLUMNS = 4;\n", "constexpr int MISSILE_HUD_COLUMNS = 2;\n")
replace_once(
    CPP,
    "  // Labels use the left 52%; the numeric value is right-aligned in the rest.\n"
    "  const int valueX = cell.x + (cell.width * 52) / 100;\n",
    "  // Two wide cells: keep the static label well away from the numeric area.\n"
    "  const int valueX = cell.x + (cell.width * 40) / 100;\n",
)

anchor = r'''void drawMissileHudValue(GfxRenderer& renderer, const Rect& status, int column, const char* value) {
  const Rect valueRect = missileHudValueRect(status, column);
  renderer.fillRect(valueRect.x, valueRect.y, valueRect.width, valueRect.height, false);
  const int w = renderer.getTextWidth(UI_10_FONT_ID, value);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int x = std::max(valueRect.x, valueRect.x + valueRect.width - w);
  const int y = valueRect.y + std::max(0, (valueRect.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, value);
}

'''
extra = anchor + r'''Rect missileHeaderCityValueRect(GfxRenderer& renderer, const Rect& header) {
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int w = std::max(24, renderer.getTextWidth(UI_10_FONT_ID, "88") + 6);
  return Rect{header.x + header.width - 12 - w,
              header.y + std::max(0, (header.height - h) / 2) - 2,
              w, h + 4};
}

void drawMissileHeaderCityValue(GfxRenderer& renderer, const Rect& header, int cities) {
  const Rect valueRect = missileHeaderCityValueRect(renderer, header);
  renderer.fillRect(valueRect.x, valueRect.y, valueRect.width, valueRect.height, false);
  char value[4];
  std::snprintf(value, sizeof(value), "%d", cities);
  const int w = renderer.getTextWidth(UI_10_FONT_ID, value);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  renderer.drawText(UI_10_FONT_ID, valueRect.x + std::max(0, valueRect.width - w),
                    valueRect.y + std::max(0, (valueRect.height - h) / 2), value);
}

void drawMissileHeaderMeta(GfxRenderer& renderer, const Rect& header, uint16_t wave, int cities) {
  const Rect valueRect = missileHeaderCityValueRect(renderer, header);
  char prefix[40];
  std::snprintf(prefix, sizeof(prefix), "- Vague %u - Villes", static_cast<unsigned>(wave));
  const int w = renderer.getTextWidth(UI_10_FONT_ID, prefix);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int x = valueRect.x - 6 - w;
  const int y = header.y + std::max(0, (header.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, prefix);
  drawMissileHeaderCityValue(renderer, header, cities);
}

'''
replace_once(CPP, anchor, extra)

old_header = r'''void MissileCommandActivity::drawFullPlayingScene() {
  renderer.clearScreen();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }

  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);
'''
new_header = r'''void MissileCommandActivity::drawFullPlayingScene() {
  renderer.clearScreen();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }
  // Gameplay metadata lives in the title bar. Wave changes already trigger a
  // full gameplay redraw; only the tiny city-number rectangle changes mid-wave.
  drawMissileHeaderMeta(renderer, geometry.header, wave_, aliveCityCount());
  hudCitiesDrawn_ = aliveCityCount();

  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);
'''
replace_once(CPP, old_header, new_header)

old_full_hud = r'''  // Stable HUD table. Put the frequently changing score near the horizontal
  // centre so score-only updates are less likely to widen the gameplay bbox.
  for (int column = 1; column < MISSILE_HUD_COLUMNS; ++column) {
    const int x = geometry.status.x + (geometry.status.width * column) / MISSILE_HUD_COLUMNS;
    renderer.drawLine(x, geometry.status.y + 2, x, geometry.status.y + geometry.status.height - 3, 1, true);
  }
  drawMissileHudLabel(renderer, geometry.status, 0, "Vague");
  drawMissileHudLabel(renderer, geometry.status, 1, "Score");
  drawMissileHudLabel(renderer, geometry.status, 2, "Record");
  drawMissileHudLabel(renderer, geometry.status, 3, "Villes");

  if (score_ > highScore_) highScore_ = score_;
  char hudValue[16];
  std::snprintf(hudValue, sizeof(hudValue), "%u", static_cast<unsigned>(wave_));
  drawMissileHudValue(renderer, geometry.status, 0, hudValue);
  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));
  drawMissileHudValue(renderer, geometry.status, 1, hudValue);
  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));
  drawMissileHudValue(renderer, geometry.status, 2, hudValue);
  std::snprintf(hudValue, sizeof(hudValue), "%d", aliveCityCount());
  drawMissileHudValue(renderer, geometry.status, 3, hudValue);
  hudScoreDrawn_ = score_;
  hudHighScoreDrawn_ = highScore_;
'''
new_full_hud = r'''  // The gameplay status strip is deliberately only two wide cells. Static
  // labels/separator are painted on full scene redraws; numeric areas are the
  // only regions touched during ordinary gameplay.
  const int splitX = geometry.status.x + geometry.status.width / 2;
  renderer.drawLine(splitX, geometry.status.y + 2, splitX, geometry.status.y + geometry.status.height - 3, 1, true);
  drawMissileHudLabel(renderer, geometry.status, 0, "Score");
  drawMissileHudLabel(renderer, geometry.status, 1, "Record");

  if (score_ > highScore_) highScore_ = score_;
  char hudValue[16];
  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));
  drawMissileHudValue(renderer, geometry.status, 0, hudValue);
  std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));
  drawMissileHudValue(renderer, geometry.status, 1, hudValue);
  hudScoreDrawn_ = score_;
  hudHighScoreDrawn_ = highScore_;
'''
replace_once(CPP, old_full_hud, new_full_hud)

# HUD-table patch used score=column 1 / record=column 2. In the two-column
# layout they become columns 0 and 1.
replace_once(
    CPP,
    "    drawMissileHudValue(renderer, geometry.status, 1, hudValue);\n"
    "    hudScoreDrawn_ = score_;\n",
    "    drawMissileHudValue(renderer, geometry.status, 0, hudValue);\n"
    "    hudScoreDrawn_ = score_;\n",
)
replace_once(
    CPP,
    "    drawMissileHudValue(renderer, geometry.status, 2, hudValue);\n"
    "    hudHighScoreDrawn_ = highScore_;\n",
    "    drawMissileHudValue(renderer, geometry.status, 1, hudValue);\n"
    "    hudHighScoreDrawn_ = highScore_;\n",
)

# City count is the only title-bar field that can change in the middle of a
# wave. Update just its tiny numeric rectangle, never the title/metadata labels.
old_tail = r'''  if (hudHighScoreDrawn_ != highScore_) {
    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(highScore_));
    drawMissileHudValue(renderer, geometry.status, 1, hudValue);
    hudHighScoreDrawn_ = highScore_;
  }
'''
new_tail = old_tail + r'''  const int cities = aliveCityCount();
  if (hudCitiesDrawn_ != cities) {
    drawMissileHeaderCityValue(renderer, geometry.header, cities);
    hudCitiesDrawn_ = cities;
  }
'''
replace_once(CPP, old_tail, new_tail)

# Separate benchmark identity for a clean A/B against HUD-table.
replace_once(
    CPP,
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-hud-table-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-bench.csv";',
)
replace_once(CPP, 'Storage.openFileForWrite("MISSILE-A2-SPARSE-HUD", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-HEADER-HUD", BENCH_PATH, file)')
replace_once(CPP,
             'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-hud-table-started,0,0,0,0,0\\n";',
             'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-header-hud-started,0,0,0,0,0\\n";')
replace_once(CPP, 'Storage.openFileForWrite("MISSILE-A2-SPARSE-HUD", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-HEADER-HUD", BENCH_PATH, file)')
replace_once(CPP,
             '"game-a2-lite-pll0f-sparse-trail64-fade-hud-table,%lu,%lu,%lu,%lu,%lu\\n",',
             '"game-a2-lite-pll0f-sparse-trail64-fade-header-hud,%lu,%lu,%lu,%lu,%lu\\n",')

print("Missile header wave/cities + two-cell Score/Record HUD applied")
