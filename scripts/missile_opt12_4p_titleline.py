from pathlib import Path

DRIVER = Path("freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp")
CPP = Path("src/activities/home/MissileCommandActivity.cpp")

# ---------------------------------------------------------------------------
# A2-Lite-4P: keep the already proven transition-only model (WW/BB no-drive),
# but retain only the first LUT frame-group for VCOM/BW/WB. A2-Lite quantizes
# each non-zero phase to one frame; group 0 has four active phases while group 1
# contributes two more. Clearing phases 1..4 from groups >= 1 therefore tests a
# 6 -> 4 driven-slot waveform without touching polarity/rail bits of the kept
# first group.
# ---------------------------------------------------------------------------
text = DRIVER.read_text()
old = r'''void buildMissileGameA2LitePreBw(uint8_t out[5][PREBW_LUT_LEN]) {
  for (uint8_t t = 0; t < 5; ++t) {
    memcpy(out[t], &kXtfPreBwMid[t][1], PREBW_LUT_LEN);
    for (uint8_t group = 0; group < PREBW_LUT_LEN / 7; ++group) {
      uint8_t* const g = out[t] + group * 7;
      for (uint8_t phase = 1; phase <= 4; ++phase) {
        const uint8_t original = g[phase];
        const uint8_t frames = static_cast<uint8_t>(original & 0x3F);
        if (t == 1 || t == 4) {
          // WW / BB: true no-drive for same-state pixels.
          g[phase] = 0x00;
        } else if (frames != 0) {
          // VCOM / BW / WB: preserve rail/polarity, shorten duration only.
          g[phase] = static_cast<uint8_t>((original & 0xC0) | 0x01);
        }
      }
    }
  }
}
'''
new = r'''void buildMissileGameA2LitePreBw(uint8_t out[5][PREBW_LUT_LEN]) {
  for (uint8_t t = 0; t < 5; ++t) {
    memcpy(out[t], &kXtfPreBwMid[t][1], PREBW_LUT_LEN);
    for (uint8_t group = 0; group < PREBW_LUT_LEN / 7; ++group) {
      uint8_t* const g = out[t] + group * 7;
      for (uint8_t phase = 1; phase <= 4; ++phase) {
        const uint8_t original = g[phase];
        const uint8_t frames = static_cast<uint8_t>(original & 0x3F);
        if (t == 1 || t == 4) {
          // WW / BB: true no-drive for same-state pixels.
          g[phase] = 0x00;
        } else if (group > 0) {
          // A2-Lite-4P experiment: keep only the four driven phase slots from
          // the first group. Later groups contribute no drive.
          g[phase] = 0x00;
        } else if (frames != 0) {
          // VCOM / BW / WB first group: preserve rail/polarity, one frame each.
          g[phase] = static_cast<uint8_t>((original & 0xC0) | 0x01);
        }
      }
    }
  }
}
'''
if old not in text:
    raise SystemExit("A2-Lite LUT helper not found")
DRIVER.write_text(text.replace(old, new, 1))

# ---------------------------------------------------------------------------
# Header: deliberately use ONE title string and ONE header draw. No separate
# metadata renderer, no right-side reserve, no second font, no second alignment.
# Wave/Town still update only on the full scene redraw at wave boundaries.
# ---------------------------------------------------------------------------
text = CPP.read_text()
old_header = r'''  const int headerMetaReserve = missileHeaderMetaReserve(renderer, wave_, aliveCityCount());
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
new_header = r'''  char gameplayTitle[64];
  std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Missile Command - Wave %u - Town %d",
                static_cast<unsigned>(wave_), aliveCityCount());
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, gameplayTitle, false);
  } else {
    GUI.drawHeader(renderer, geometry.header, gameplayTitle, nullptr, false);
  }
'''
if old_header not in text:
    raise SystemExit("reserved gameplay header block not found")
text = text.replace(old_header, new_header, 1)

# Distinct benchmark identity for an unambiguous A/B against OPT12.
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12', 'MISSILE-A2-OPT12-4P')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline,%lu,%lu,%lu,%lu,%lu',
)
CPP.write_text(text)

print("OPT12 + A2-Lite-4P + single title-line header applied")
