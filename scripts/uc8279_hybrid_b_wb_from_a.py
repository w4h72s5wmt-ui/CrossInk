from pathlib import Path


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor in {path}, found {count}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"expected {expected} anchors in {path}, found {count}: {old[:180]!r}")
    p.write_text(text.replace(old, new))


# This patch is intentionally additive and MUST run after uc8279_fast40_hybrid_a.py.
# Hybrid-A already applies the aggressive original-4-frame -> 1-frame cut only to
# the same-state tables 0x21 (WW) and 0x24 (BB). Hybrid-B-WB adds exactly one
# active-transition table to that rule: 0x23 (W->B). In the stock PREBW table,
# 0x23 has one phase slot whose original frame count is 4; Fast40 quantizes that
# slot to 2 frames, and this experiment shortens only that slot to 1 frame.
#
# 0x22 (B->W), VCOM, voltage rails, PLL, TSSET, CDI, PFS, gate scan, CCSET and SPI
# settings remain exactly as in Hybrid-A / the underlying X4 Pro configuration.

old_loop = (
    "  // Hybrid-A experiment: only same-state tables get the aggressive 4->1 cut.\n"
    "  // Use the original LUT to identify exactly those phases; preserve rail bits.\n"
    "  for (uint8_t t : {uint8_t(1), uint8_t(4)}) {\n"
)
new_loop = (
    "  // Hybrid-B W->B experiment: retain Hybrid-A's WW/BB cuts and add only\n"
    "  // table 0x23 (index 3). In the source table this changes exactly one\n"
    "  // original 4-frame phase from Fast40's 2 frames to 1 frame.\n"
    "  for (uint8_t t : {uint8_t(1), uint8_t(3), uint8_t(4)}) {\n"
)
replace_once(DRIVER, old_loop, new_loop)

# Rename the generated helper and timing tags so serial traces cannot be confused
# with the clean Hybrid-A reference build.
replace_all(DRIVER, "buildFast40HybridAPreBw", "buildFast40HybridBwbPreBw", expected=2)
replace_once(DRIVER, " 8279x4_win_fast40_hybridA_PON", " 8279x4_win_fast40_hybridBwb_PON")
replace_once(DRIVER, " 8279x4_window_fast40_hybridA_DRF", " 8279x4_window_fast40_hybridBwb_DRF")

# Keep Hybrid-A's existing 200-frame gameplay benchmark, but write it to a
# distinct file/profile so A and B results can coexist on the SD card.
replace_once(
    CPP,
    '    constexpr const char* BENCH_PATH = "/missile-command-fast40-hybrid-a-bench.csv";\n',
    '    constexpr const char* BENCH_PATH = "/missile-command-fast40-hybrid-b-wb-bench.csv";\n',
)
replace_all(CPP, '"MISSILE-HYBRID-A"', '"MISSILE-HYBRID-B-WB"', expected=2)
replace_once(CPP, "fast40-hybrid-a-started,0,0,0,0,0", "fast40-hybrid-b-wb-started,0,0,0,0,0")
replace_once(CPP, "fast40-hybrid-a,%lu,%lu,%lu,%lu,%lu", "fast40-hybrid-b-wb,%lu,%lu,%lu,%lu,%lu")

print("UC8279 Hybrid-B W->B isolated transition patch applied on top of Hybrid-A")
