from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"

replace_once(
    CPP,
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";\n',
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage5-waveform.csv";\n',
)

replace_once(
    CPP,
    '  const char header[] = "window_w,window_h,window_pixels,screen_pct_x100,pass,refresh_us\\n";\n',
    '  const char header[] = "speed_pct,window_w,window_h,window_pixels,screen_pct_x100,pass,refresh_us\\n";\n',
)

old_loop = r'''  for (const auto& test : tests) {
    if (test.w > panelW || test.h > panelH) continue;
    const uint16_t x = static_cast<uint16_t>(((panelW - test.w) / 2) & ~0x07u);
    const uint16_t y = static_cast<uint16_t>((panelH - test.h) / 2);
    for (uint8_t pass = 1; pass <= 2; ++pass) {
      toggleMarker();
      const uint32_t t0 = micros();
      display.displayWindow(x, y, test.w, test.h, false);
      const uint32_t elapsed = micros() - t0;
      const uint32_t pixels = static_cast<uint32_t>(test.w) * test.h;
      const uint32_t pctX100 = screenPixels ? static_cast<uint32_t>((static_cast<uint64_t>(pixels) * 10000ULL) / screenPixels) : 0;
      char line[128];
      const int n = std::snprintf(line, sizeof(line), "%u,%u,%lu,%lu,%u,%lu\n",
                                  static_cast<unsigned>(test.w), static_cast<unsigned>(test.h),
                                  static_cast<unsigned long>(pixels), static_cast<unsigned long>(pctX100),
                                  static_cast<unsigned>(pass), static_cast<unsigned long>(elapsed));
      if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
    }
  }
'''
new_loop = r'''  constexpr uint8_t speedProfiles[] = {80, 65, 50};
  for (const uint8_t speedPct : speedProfiles) {
    for (const auto& test : tests) {
      if (test.w > panelW || test.h > panelH) continue;
      const uint16_t x = static_cast<uint16_t>(((panelW - test.w) / 2) & ~0x07u);
      const uint16_t y = static_cast<uint16_t>((panelH - test.h) / 2);
      for (uint8_t pass = 1; pass <= 2; ++pass) {
        toggleMarker();
        const uint32_t t0 = micros();
        display.displayWindow(x, y, test.w, test.h, false);
        const uint32_t elapsed = micros() - t0;
        const uint32_t pixels = static_cast<uint32_t>(test.w) * test.h;
        const uint32_t pctX100 = screenPixels ? static_cast<uint32_t>((static_cast<uint64_t>(pixels) * 10000ULL) / screenPixels) : 0;
        char line[144];
        const int n = std::snprintf(line, sizeof(line), "%u,%u,%u,%lu,%lu,%u,%lu\n",
                                    static_cast<unsigned>(speedPct),
                                    static_cast<unsigned>(test.w), static_cast<unsigned>(test.h),
                                    static_cast<unsigned long>(pixels), static_cast<unsigned long>(pctX100),
                                    static_cast<unsigned>(pass), static_cast<unsigned long>(elapsed));
        if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
      }
    }
  }
'''
replace_once(CPP, old_loop, new_loop)

replace_once(
    CPP,
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    static bool waveformSweepDone = false;\n"
    "    if (!waveformSweepDone) {\n"
    "      waveformSweepDone = true;\n"
    "      runUc8279WindowBenchmark();\n"
    "      lastCycleUs_ = esp_timer_get_time();\n"
    "    }\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
)

helper = r'''
void buildScaledPreBw(uint8_t speedPct, uint8_t out[5][PREBW_LUT_LEN]) {
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
new_setup = r'''  static uint8_t waveformTrialCall = 0;
  const bool useScaledTrial = waveformTrialCall < 42;
  const uint8_t trialSpeedPct = waveformTrialCall < 14 ? 80 : (waveformTrialCall < 28 ? 65 : 50);

  if (useScaledTrial) {
    uint8_t scaledLuts[5][PREBW_LUT_LEN];
    buildScaledPreBw(trialSpeedPct, scaledLuts);

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
      bus.data(scaledLuts[t], PREBW_LUT_LEN);
    }
    powerOnIfNeeded(bus, " 8279x4_win_scaled_PON");
    bus.cmd(CMD_DISPLAY_REFRESH);
  } else {
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
  }
'''
replace_once(DRIVER, old_setup, new_setup)

replace_once(
    DRIVER,
    '  bus.waitRefreshComplete(" 8279x4_window_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
    '  bus.waitRefreshComplete(useScaledTrial ? " 8279x4_window_scaled_DRF" : " 8279x4_window_DRF");\n'
    '  if (useScaledTrial) ++waveformTrialCall;\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
)

print("UC8279 Stage-E stock waveform sweep applied: 80%, 65%, 50% (42 benchmark calls only)")
