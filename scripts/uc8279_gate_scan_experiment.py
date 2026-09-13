from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"
DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"

# Stage C: keep every known-good Stage-B parameter (OTP waveform selection,
# CDI, CCSET, TSSET, PFS, gate scan register, PLL and all analog rails) and only
# change PTL's PT_SCAN flag. UltraChip UC81xx defines PT_SCAN=0 as scanning only
# gates inside the programmed partial window, while PT_SCAN=1 also scans gates
# outside it. Stage B used 1, matching the OEM full-window path; for genuinely
# small dirty windows that defeats most of the expected gate-scan saving.
replace_once(
    DRIVER,
    "  bus.data(static_cast<uint8_t>(yEnd >> 8));\n"
    "  bus.data(static_cast<uint8_t>(yEnd & 0xFF));\n"
    "  bus.data(0x01);\n\n"
    "  // Dual-buffer callers may supply an explicit OLD plane. Single-buffer X4 Pro\n",
    "  bus.data(static_cast<uint8_t>(yEnd >> 8));\n"
    "  bus.data(static_cast<uint8_t>(yEnd & 0xFF));\n"
    "  // PT_SCAN=0: scan only gates inside PTL. This does not alter LUTs,\n"
    "  // voltage rails, CDI, TSSET, PLL or drive amplitudes.\n"
    "  bus.data(0x00);\n\n"
    "  // Dual-buffer callers may supply an explicit OLD plane. Single-buffer X4 Pro\n",
)

# Keep Stage-B benchmark geometry so results are directly comparable, but write
# a distinct file and re-enable the one-time benchmark after the gameplay-timing
# patch removed the Stage-B diagnostic invocation.
replace_once(
    CPP,
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";\n',
    'constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage3.csv";\n',
)

replace_once(
    CPP,
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
    "  if (forceFullRefresh) {\n"
    "    renderer.displayBuffer(HalDisplay::FAST_REFRESH);\n"
    "    static bool gateScanBenchmarkDone = false;\n"
    "    if (!gateScanBenchmarkDone) {\n"
    "      gateScanBenchmarkDone = true;\n"
    "      runUc8279WindowBenchmark();\n"
    "      lastCycleUs_ = esp_timer_get_time();\n"
    "    }\n"
    "    uint8_t* const fb = display.getFrameBuffer();\n",
)

print("UC8279 Stage-C PT_SCAN=0 gate-window experiment applied")
