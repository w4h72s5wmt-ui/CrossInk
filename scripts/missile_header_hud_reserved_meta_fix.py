from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:260]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"

old_helper = r'''void drawMissileHeaderMeta(GfxRenderer& renderer, const Rect& header, uint16_t wave, int cities) {
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
new_helper = r'''int missileHeaderMetaReserve(GfxRenderer& renderer, uint16_t wave, int cities) {
  char meta[40];
  std::snprintf(meta, sizeof(meta), "Vague %u - Villes %d", static_cast<unsigned>(wave), cities);
  // UI_10 is part of the normal UI font set and is already used successfully
  // by the score strip. Reserve the exact metadata width plus breathing room.
  return renderer.getTextWidth(UI_10_FONT_ID, meta) + 24;
}

void drawMissileHeaderMeta(GfxRenderer& renderer, const Rect& header, uint16_t wave, int cities) {
  char meta[40];
  std::snprintf(meta, sizeof(meta), "Vague %u - Villes %d", static_cast<unsigned>(wave), cities);
  const int w = renderer.getTextWidth(UI_10_FONT_ID, meta);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x, right - w);
  const int y = header.y + std::max(0, (header.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, meta);
}

'''
replace_once(CPP, old_helper, new_helper)

old_header = r'''  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }
  // Gameplay metadata lives in the title bar. Wave changes already trigger a
  // full gameplay redraw; only the tiny city-number rectangle changes mid-wave.
  drawMissileHeaderMeta(renderer, geometry.header, wave_, aliveCityCount());
'''
new_header = r'''  const int headerMetaReserve = missileHeaderMetaReserve(renderer, wave_, aliveCityCount());
  if (mappedInput.hasTouchHardware()) {
    // TouchHeaderBackButton supports a right-side reserve explicitly. Use it so
    // the large title can never overlap the Wave/Cities lane.
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false,
                                headerMetaReserve);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }
  // Wave/Cities are painted only on full scene redraws (start / wave change).
  drawMissileHeaderMeta(renderer, geometry.header, wave_, aliveCityCount());
'''
replace_once(CPP, old_header, new_header)

print("Missile header metadata visible with UI_10 and dedicated right-side reserve")
