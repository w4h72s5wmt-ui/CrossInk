from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"

# Applied AFTER Stage-B + gameplay timing + Hybrid-A + GAME-A2 Lite.
# Isolated PLL experiment:
#   * keep validated GAME-A2 Lite LUT unchanged
#   * keep SPI unchanged
#   * keep initial/full/scrub paths at stock _cfg.pll (0x0E)
#   * only the Missile dirty-window DRF runs at PLL 0x0F
#   * restore _cfg.pll immediately after BUSY/DRF completes

replace_once(
    DRIVER,
    '  powerOnIfNeeded(bus, " 8279x4_win_gameA2Lite_PON");\n'
    '  bus.cmd(CMD_DISPLAY_REFRESH);\n',
    '  bus.cmd(CMD_PLL);\n'
    '  bus.data(0x0F);\n'
    '  powerOnIfNeeded(bus, " 8279x4_win_gameA2Lite_pll0f_PON");\n'
    '  bus.cmd(CMD_DISPLAY_REFRESH);\n',
)

replace_once(
    DRIVER,
    '  bus.waitRefreshComplete(" 8279x4_window_gameA2Lite_DRF");\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
    '  bus.waitRefreshComplete(" 8279x4_window_gameA2Lite_pll0f_DRF");\n'
    '  bus.cmd(CMD_PLL);\n'
    '  bus.data(_cfg.pll);\n\n'
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
)

replace_once(CPP,
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-wave-scrub-bench.csv";',
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-wave-scrub-bench.csv";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-GAME-A2-LITE", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-LITE-PLL0F", BENCH_PATH, file)')
replace_once(CPP,
             'const char started[] = "game-a2-lite-wave-scrub-started,0,0,0,0,0\\n";',
             'const char started[] = "game-a2-lite-pll0f-wave-scrub-started,0,0,0,0,0\\n";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-GAME-A2-LITE", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-LITE-PLL0F", BENCH_PATH, file)')
replace_once(CPP,
             '"game-a2-lite-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",',
             '"game-a2-lite-pll0f-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",')

print("UC8279 Missile GAME-A2 Lite + temporary dirty-window PLL 0x0F applied")
