from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:220]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
HDR = "src/activities/home/MissileCommandActivity.h"

# Applied after missile_header_score_record_hud.py.
# Keep the cleaner two-cell Score/Record strip, but make gameplay header metadata
# visually independent from the large title and completely static during a wave.

replace_once(HDR, "  int hudCitiesDrawn_ = -1;\n", "")

old_helpers = r'''Rect missileHeaderCityValueRect(GfxRenderer& renderer, const Rect& header) {
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
new_helpers = r'''void drawMissileHeaderMeta(GfxRenderer& renderer, const Rect& header, uint16_t wave, int cities) {
  // Compact, right-aligned metadata so it never collides with the large
  // "Missile Command" title. It is painted only during a full scene redraw,
  // therefore Wave and Cities stay fixed for the whole wave.
  char meta[40];
  std::snprintf(meta, sizeof(meta), "Vague %u - Villes %d", static_cast<unsigned>(wave), cities);
  const int fontId = LEXENDDECA_8_FONT_ID;
  const int w = renderer.getTextWidth(fontId, meta);
  const int h = renderer.getLineHeight(fontId);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x + header.width / 2 + 8, right - w);
  const int y = header.y + std::max(0, (header.height - h) / 2);
  renderer.drawText(fontId, x, y, meta);
}

'''
replace_once(CPP, old_helpers, new_helpers)

replace_once(
    CPP,
    "  drawMissileHeaderMeta(renderer, geometry.header, wave_, aliveCityCount());\n"
    "  hudCitiesDrawn_ = aliveCityCount();\n",
    "  drawMissileHeaderMeta(renderer, geometry.header, wave_, aliveCityCount());\n",
)

old_city_incremental = r'''  const int cities = aliveCityCount();
  if (hudCitiesDrawn_ != cities) {
    drawMissileHeaderCityValue(renderer, geometry.header, cities);
    hudCitiesDrawn_ = cities;
  }
'''
replace_once(CPP, old_city_incremental, "")

# Keep this candidate separate in the benchmark CSV.
replace_once(
    CPP,
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-bench.csv";',
)
replace_once(CPP, 'Storage.openFileForWrite("MISSILE-A2-HEADER-HUD", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-HEADER-CLEAN", BENCH_PATH, file)')
replace_once(
    CPP,
    'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-header-hud-started,0,0,0,0,0\\n";',
    'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean-started,0,0,0,0,0\\n";',
)
replace_once(CPP, 'Storage.openFileForWrite("MISSILE-A2-HEADER-HUD", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-HEADER-CLEAN", BENCH_PATH, file)')
replace_once(
    CPP,
    '"game-a2-lite-pll0f-sparse-trail64-fade-header-hud,%lu,%lu,%lu,%lu,%lu\\n",',
    '"game-a2-lite-pll0f-sparse-trail64-fade-header-hud-clean,%lu,%lu,%lu,%lu,%lu\\n",',
)

print("Missile clean right-aligned header HUD; cities refresh only on wave redraw")
