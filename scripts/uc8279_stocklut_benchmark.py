from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"

# Distinct benchmark output. Stage B is applied first, then the legacy gameplay
# timing patch removes the old one-time benchmark call. Re-enable it here.
replace_once(
    CPP,
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";\n',
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage4-stocklut.csv";\n',
)

replace_once(
    CPP,
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    static bool stockLutBenchmarkDone = false;\n"
    "    if (!stockLutBenchmarkDone) {\n"
    "      stockLutBenchmarkDone = true;\n"
    "      runUc8279WindowBenchmark();\n"
    "      lastCycleUs_ = esp_timer_get_time();\n"
    "    }\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
)

# Stage D uses the exact 42-byte UC8279_aa_prebw_mid transition tables extracted
# from the X4 Pro stock Factory.bin. IMPORTANT: only the first 14 displayWindow
# calls use this waveform -- exactly the 7 benchmark sizes x 2 passes. After
# that, displayWindow automatically returns to the proven Stage-B OTP path for
# gameplay. No power, VCOM, VGH/VGL, source/gate or PLL values are changed.
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
new_setup = r'''  // Diagnostic only: the first 14 calls correspond exactly to the one-time
  // benchmark. Exercise the STOCK X4 Pro non-flashing prev->current waveform,
  // byte-for-byte from Factory.bin, then automatically fall back to Stage B.
  static uint8_t stockLutTrialsRemaining = 14;
  const bool useStockLutTrial = stockLutTrialsRemaining != 0;

  if (useStockLutTrial) {
    // Exact stock UC8279_aa_prebw_mid setup, adapted only to the already-selected
    // PTL rectangle. REG=1 selects the external tables. Analog rails remain the
    // panel-programmed OTP/MTP values: there is deliberately no PWR/VDCS/BTST.
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
    for (const auto& l : kXtfPreBwMid) {
      bus.cmd(l[0]);
      bus.data(&l[1], PREBW_LUT_LEN);
    }
    powerOnIfNeeded(bus, " 8279x4_win_stocklut_PON");
    bus.cmd(CMD_DISPLAY_REFRESH);
  } else {
    // Proven Stage-B gameplay path: ordinary stock OTP DU waveform.
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
    '  bus.waitRefreshComplete(useStockLutTrial ? " 8279x4_window_stocklut_DRF" : " 8279x4_window_DRF");\n'
    '  if (useStockLutTrial) --stockLutTrialsRemaining;\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
)

print("UC8279 Stage-D stock X4 Pro LUT benchmark applied (14 calls only)")
