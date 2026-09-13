from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"

# Real-gameplay Stage F: use exactly the 50% stock pre-B/W waveform profile that
# Stage E benchmarked successfully. No benchmark, no counter, no automatic
# fallback: every post-baseline displayWindow() refresh uses this profile.
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

print("UC8279 real-gameplay Fast50 waveform applied")
