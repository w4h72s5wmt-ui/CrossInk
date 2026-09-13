from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"

# Fast40 Hybrid-B2:
#   * Start from visually-clean Hybrid-A.
#   * 0x20 VCOM stays Fast40.
#   * 0x21/0x24 same-state tables keep Hybrid-A aggressive 4->1 cuts.
#   * Test ONLY active table 0x23 with the same 4->1 cut.
#   * 0x22 remains Fast40 as the protected active transition.
# Safety boundary unchanged: no analog rails, PLL, TSSET/CDI/PFS/GATE_SCAN/CCSET changes.

helper = r'''
void buildFast40HybridB2PreBw(uint8_t out[5][PREBW_LUT_LEN]) {
  constexpr uint8_t speedPct = 40;
  for (uint8_t t = 0; t < 5; ++t) {
    memcpy(out[t], &kXtfPreBwMid[t][1], PREBW_LUT_LEN);
    for (uint8_t group = 0; group < PREBW_LUT_LEN / 7; ++group) {
      uint8_t* const g = out[t] + group * 7;
      for (uint8_t phase = 1; phase <= 4; ++phase) {
        const uint8_t original = g[phase];
        const uint8_t rail = static_cast<uint8_t>(original & 0xC0);
        const uint8_t frames = static_cast<uint8_t>(original & 0x3F);
        if (frames == 0) continue;
        uint16_t scaled = static_cast<uint16_t>((static_cast<uint16_t>(frames) * speedPct + 50u) / 100u);
        if (scaled == 0) scaled = 1;
        if (scaled > 63) scaled = 63;
        g[phase] = static_cast<uint8_t>(rail | scaled);
      }
    }
  }

  // Hybrid-A tables 0x21/0x24 plus one isolated active transition 0x23.
  for (uint8_t t : {uint8_t(1), uint8_t(3), uint8_t(4)}) {
    for (uint8_t group = 0; group < PREBW_LUT_LEN / 7; ++group) {
      uint8_t* const g = out[t] + group * 7;
      const uint8_t* const src = &kXtfPreBwMid[t][1] + group * 7;
      for (uint8_t phase = 1; phase <= 4; ++phase) {
        if ((src[phase] & 0x3F) == 4) {
          g[phase] = static_cast<uint8_t>((g[phase] & 0xC0) | 0x01);
        }
      }
    }
  }
}

'''
replace_once(DRIVER, "const GrayLut* selectAaLuts() {\n", helper + "const GrayLut* selectAaLuts() {\n")

old_setup = r'''  // Same known-good fast settings as the stock full-surface DU path.
  bus.cmd(CMD_VCOM_DATA_INTERVAL);
  bus.data(_cfg.cdiBwFast);
  bus.cmd(CMD_CCSET);
  bus.data(_cfg.ccset);
  bus.cmd(CMD_TSSET);
  bus.data(_cfg.tssetFast);
  bus.cmd(CMD_PFS);
  bus.data(_cfg.pfs);
  bus.cmd(CMD_GATE_SCAN);
  bus.data(_cfg.gateScan);

  powerOnIfNeeded(bus, " 8279x4_win_PON");
  bus.cmd(CMD_PANEL_SETTING);
  bus.data(static_cast<uint8_t>(_cfg.psr0 & 0xDF));
  bus.data(_cfg.psr1);
  bus.cmd(CMD_DISPLAY_REFRESH);
'''
new_setup = r'''  uint8_t hybridLuts[5][PREBW_LUT_LEN];
  buildFast40HybridB2PreBw(hybridLuts);

  bus.cmd(CMD_PANEL_SETTING);
  bus.data(_cfg.psr0);
  bus.data(_cfg.psr1);
  bus.cmd(CMD_PFS);
  bus.data(_cfg.pfs);
  bus.cmd(CMD_GATE_SCAN);
  bus.data(_cfg.gateScan);
  bus.cmd(CMD_VCOM_DATA_INTERVAL);
  bus.data(_cfg.cdiBwFast);
  bus.cmd(CMD_CCSET);
  bus.data(_cfg.ccset);
  bus.cmd(CMD_TSSET);
  bus.data(_cfg.tssetFast);
  for (uint8_t t = 0; t < 5; ++t) {
    bus.cmd(kXtfPreBwMid[t][0]);
    bus.data(hybridLuts[t], PREBW_LUT_LEN);
  }

  powerOnIfNeeded(bus, " 8279x4_win_fast40_hybridB2_PON");
  bus.cmd(CMD_DISPLAY_REFRESH);
'''
replace_once(DRIVER, old_setup, new_setup)
replace_once(
    DRIVER,
    '  bus.waitRefreshComplete(" 8279x4_window_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
    '  bus.waitRefreshComplete(" 8279x4_window_fast40_hybridB2_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
)

bench = r'''void MissileCommandActivity::drawPlayingFrame() {
  {
    constexpr const char* BENCH_PATH = "/missile-command-fast40-hybrid-b2-bench.csv";
    constexpr uint32_t BENCH_TARGET_SAMPLES = 200;
    static int64_t benchLastFrameStartUs = 0;
    static uint32_t benchSamples = 0;
    static uint64_t benchSumCycleUs = 0;
    static uint32_t benchMinCycleUs = 0xFFFFFFFFu;
    static uint32_t benchMaxCycleUs = 0;
    static bool benchFilePrimed = false;
    static bool benchSaved = false;

    if (!benchFilePrimed) {
      FsFile file;
      if (Storage.openFileForWrite("MISSILE-HYBRID-B2", BENCH_PATH, file)) {
        const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
        file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
        const char started[] = "fast40-hybrid-b2-started,0,0,0,0,0\n";
        file.write(reinterpret_cast<const uint8_t*>(started), sizeof(started) - 1);
        file.close();
        benchFilePrimed = true;
      }
    }

    const int64_t nowUs = esp_timer_get_time();
    if (!benchSaved && benchLastFrameStartUs != 0) {
      const int64_t raw = nowUs - benchLastFrameStartUs;
      if (raw > 0 && raw < 2000000) {
        const uint32_t cycleUs = static_cast<uint32_t>(raw);
        benchSumCycleUs += cycleUs;
        if (cycleUs < benchMinCycleUs) benchMinCycleUs = cycleUs;
        if (cycleUs > benchMaxCycleUs) benchMaxCycleUs = cycleUs;
        ++benchSamples;
        if (benchSamples >= BENCH_TARGET_SAMPLES) {
          const uint32_t avg = static_cast<uint32_t>(benchSumCycleUs / benchSamples);
          const uint32_t fpsX1000 = avg ? static_cast<uint32_t>(1000000000ULL / avg) : 0;
          FsFile file;
          if (Storage.openFileForWrite("MISSILE-HYBRID-B2", BENCH_PATH, file)) {
            const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
            file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
            char line[128];
            const int n = std::snprintf(line, sizeof(line), "fast40-hybrid-b2,%lu,%lu,%lu,%lu,%lu\n",
                                        static_cast<unsigned long>(benchSamples),
                                        static_cast<unsigned long>(avg),
                                        static_cast<unsigned long>(benchMinCycleUs),
                                        static_cast<unsigned long>(benchMaxCycleUs),
                                        static_cast<unsigned long>(fpsX1000));
            if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
            file.close();
            benchSaved = true;
          }
        }
      } else if (raw >= 2000000) {
        benchSamples = 0;
        benchSumCycleUs = 0;
        benchMinCycleUs = 0xFFFFFFFFu;
        benchMaxCycleUs = 0;
      }
    }
    benchLastFrameStartUs = nowUs;
  }

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
'''
replace_once(CPP,
             "void MissileCommandActivity::drawPlayingFrame() {\n  const GameGeometry geometry = gameGeometry(renderer, mappedInput);\n",
             bench)

print("UC8279 Fast40 Hybrid-B2 (0x23 isolated) + 200-frame gameplay benchmark applied")
