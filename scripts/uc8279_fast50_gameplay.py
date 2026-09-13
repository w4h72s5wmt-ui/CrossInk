from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"

# Real-gameplay Fast50 + lightweight cadence benchmark.
# The benchmark creates its CSV immediately on the first gameplay frame, then
# replaces it with the final 60-frame result. It does not draw anything and does
# not add any panel refresh. If the final file write fails, it retries later.
#
# Safety boundary is unchanged:
#   - no PWR/VDCS/BTST writes
#   - no VCOM/VGH/VGL/source/gate voltage change
#   - no PLL change
#   - no TSSET/CDI/PFS/GATE_SCAN/CCSET change
#   - same stock rail/polarity codes and phase order
# Only the lower-six-bit frame durations are scaled to 50%, exactly as Stage E.

helper = r'''
void buildFast50PreBw(uint8_t out[5][PREBW_LUT_LEN]) {
  constexpr uint8_t speedPct = 50;
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
}

'''
replace_once(
    DRIVER,
    "const GrayLut* selectAaLuts() {\n",
    helper + "const GrayLut* selectAaLuts() {\n",
)

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
new_setup = r'''  // Validated Stage-E 50% stock X4 Pro transition waveform for real gameplay.
  // The app still establishes its first gameplay frame with the ordinary full
  // FAST path; only subsequent synchronized displayWindow() updates arrive here.
  uint8_t fast50Luts[5][PREBW_LUT_LEN];
  buildFast50PreBw(fast50Luts);

  bus.cmd(CMD_PANEL_SETTING);
  bus.data(_cfg.psr0);  // REG=1: external LUT
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
    bus.data(fast50Luts[t], PREBW_LUT_LEN);
  }

  powerOnIfNeeded(bus, " 8279x4_win_fast50_PON");
  bus.cmd(CMD_DISPLAY_REFRESH);
'''
replace_once(DRIVER, old_setup, new_setup)

replace_once(
    DRIVER,
    '  bus.waitRefreshComplete(" 8279x4_window_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
    '  bus.waitRefreshComplete(" 8279x4_window_fast50_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
)

bench = r'''void MissileCommandActivity::drawPlayingFrame() {
  {
    constexpr const char* BENCH_PATH = "/missile-command-fast50-gameplay-bench.csv";
    constexpr uint32_t BENCH_TARGET_SAMPLES = 60;
    static int64_t benchLastFrameStartUs = 0;
    static uint32_t benchSamples = 0;
    static uint64_t benchSumCycleUs = 0;
    static uint32_t benchMinCycleUs = 0xFFFFFFFFu;
    static uint32_t benchMaxCycleUs = 0;
    static bool benchFilePrimed = false;
    static bool benchSaved = false;

    // Make the file visible immediately, so we can verify that storage access is
    // working before the benchmark has finished.
    if (!benchFilePrimed) {
      FsFile file;
      if (Storage.openFileForWrite("MISSILE-FAST50-BENCH", BENCH_PATH, file)) {
        const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
        file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
        const char started[] = "fast50-started,0,0,0,0,0\n";
        file.write(reinterpret_cast<const uint8_t*>(started), sizeof(started) - 1);
        file.close();
        benchFilePrimed = true;
      }
    }

    const int64_t benchNowUs = esp_timer_get_time();
    if (!benchSaved && benchLastFrameStartUs != 0) {
      const int64_t rawCycleUs = benchNowUs - benchLastFrameStartUs;
      if (rawCycleUs > 0 && rawCycleUs < 2000000) {
        const uint32_t cycleUs = static_cast<uint32_t>(rawCycleUs);
        benchSumCycleUs += cycleUs;
        if (cycleUs < benchMinCycleUs) benchMinCycleUs = cycleUs;
        if (cycleUs > benchMaxCycleUs) benchMaxCycleUs = cycleUs;
        ++benchSamples;

        if (benchSamples >= BENCH_TARGET_SAMPLES) {
          const uint32_t avgCycleUs = static_cast<uint32_t>(benchSumCycleUs / benchSamples);
          const uint32_t fpsX1000 = avgCycleUs != 0
              ? static_cast<uint32_t>(1000000000ULL / avgCycleUs)
              : 0;
          FsFile file;
          if (Storage.openFileForWrite("MISSILE-FAST50-BENCH", BENCH_PATH, file)) {
            const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
            file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
            char line[128];
            const int n = std::snprintf(line, sizeof(line),
                                        "fast50,%lu,%lu,%lu,%lu,%lu\n",
                                        static_cast<unsigned long>(benchSamples),
                                        static_cast<unsigned long>(avgCycleUs),
                                        static_cast<unsigned long>(benchMinCycleUs),
                                        static_cast<unsigned long>(benchMaxCycleUs),
                                        static_cast<unsigned long>(fpsX1000));
            if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
            file.close();
            benchSaved = true;
            benchFilePrimed = true;
          }
        }
      } else if (rawCycleUs >= 2000000) {
        // Do not mix a menu/game-over pause into the gameplay cadence sample.
        benchSamples = 0;
        benchSumCycleUs = 0;
        benchMinCycleUs = 0xFFFFFFFFu;
        benchMaxCycleUs = 0;
      }
    }
    benchLastFrameStartUs = benchNowUs;
  }

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
'''
replace_once(
    CPP,
    "void MissileCommandActivity::drawPlayingFrame() {\n  const GameGeometry geometry = gameGeometry(renderer, mappedInput);\n",
    bench,
)

print("UC8279 Fast50 gameplay + immediate-file 60-frame cadence benchmark applied")
