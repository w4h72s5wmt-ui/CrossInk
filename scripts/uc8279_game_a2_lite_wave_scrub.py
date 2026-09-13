from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"
HDR = "src/activities/home/MissileCommandActivity.h"

# Missile GAME-A2 Lite experiment, applied AFTER Stage-B + gameplay fix + Hybrid-A.
#
# Scope:
#   * ordinary UI/full refreshes are untouched
#   * SPI frequency is untouched
#   * PLL/voltages/TSSET/CDI/PFS/GATE_SCAN/CCSET are untouched
#   * only the Stage-B UC8279 dirty-window waveform used by Missile gameplay changes
#   * WW (0x21) and BB (0x24) phases are zeroed: unchanged pixels receive no drive
#   * BW (0x22) and WB (0x23) non-zero phases are quantized to one frame
#   * VCOM (0x20) non-zero phases are quantized to one frame
#   * at each wave transition Missile performs one stock HALF scrub before resuming
#     GAME-A2 Lite dirty-window refreshes

helper = r'''
void buildMissileGameA2LitePreBw(uint8_t out[5][PREBW_LUT_LEN]) {
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
replace_once(DRIVER, "const GrayLut* selectAaLuts() {\n", helper + "const GrayLut* selectAaLuts() {\n")
replace_once(DRIVER,
             "  buildFast40HybridAPreBw(hybridLuts);\n",
             "  buildMissileGameA2LitePreBw(hybridLuts);\n")
replace_once(DRIVER,
             '  powerOnIfNeeded(bus, " 8279x4_win_fast40_hybridA_PON");\n',
             '  powerOnIfNeeded(bus, " 8279x4_win_gameA2Lite_PON");\n')
replace_once(DRIVER,
             '  bus.waitRefreshComplete(" 8279x4_window_fast40_hybridA_DRF");\n',
             '  bus.waitRefreshComplete(" 8279x4_window_gameA2Lite_DRF");\n')

replace_once(HDR,
             "  bool windowShadowValid_ = false;\n",
             "  bool windowShadowValid_ = false;\n"
             "  bool waveScrubPending_ = false;\n")

replace_once(CPP,
             "  ++wave_;\n  startWave();\n  saveGame();\n",
             "  ++wave_;\n"
             "  waveScrubPending_ = true;\n"
             "  startWave();\n"
             "  saveGame();\n")
replace_once(CPP,
             "  wave_ = 1;\n  startWave();\n",
             "  wave_ = 1;\n  waveScrubPending_ = false;\n  startWave();\n")
replace_once(CPP,
             "void MissileCommandActivity::continueGame() {\n  enemies_ = {};\n",
             "void MissileCommandActivity::continueGame() {\n  waveScrubPending_ = false;\n  enemies_ = {};\n")

replace_once(CPP,
             "  if (forceFullRefresh) {\n"
             "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
             "    uint8_t* const fb = display.getFrameBuffer();\n",
             "  if (forceFullRefresh) {\n"
             "    if (waveScrubPending_) {\n"
             "      renderer.displayBuffer(HalDisplay::HALF_REFRESH);\n"
             "      waveScrubPending_ = false;\n"
             "    } else {\n"
             "      renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
             "    }\n"
             "    uint8_t* const fb = display.getFrameBuffer();\n")

replace_once(CPP,
             'constexpr const char* BENCH_PATH = "/missile-command-fast40-hybrid-a-bench.csv";',
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-wave-scrub-bench.csv";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-HYBRID-A", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-GAME-A2-LITE", BENCH_PATH, file)')
replace_once(CPP,
             'const char started[] = "fast40-hybrid-a-started,0,0,0,0,0\\n";',
             'const char started[] = "game-a2-lite-wave-scrub-started,0,0,0,0,0\\n";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-HYBRID-A", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-GAME-A2-LITE", BENCH_PATH, file)')
replace_once(CPP,
             '"fast40-hybrid-a,%lu,%lu,%lu,%lu,%lu\\n",',
             '"game-a2-lite-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",')

print("UC8279 Missile GAME-A2 Lite transition-only + inter-wave HALF scrub applied")
