from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:260]!r}")
    p.write_text(text.replace(old, new, 1))


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"

# Optimization 1: sparse path invariant already leaves DTM1 synchronized with
# the last displayed frame. Upload only DTM2 before DRF; keep the post-DRF DTM1
# resync for changed tiles. This avoids sending the old plane twice.
old_sparse = r'''      setWindow(x, y, w, h);
      if (prev != nullptr) streamWindowPlane(bus, CMD_DTM1, prev, x, y, w, h);
      streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);
      ++dirtyCount;
'''
new_sparse = r'''      setWindow(x, y, w, h);
      // DTM1 already contains the previously displayed frame from the prior
      // post-DRF resync. Only upload the NEW plane before refresh.
      streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);
      ++dirtyCount;
'''
replace_once(DRIVER, old_sparse, new_sparse)

# Optimization 2: make the 1-bit trail fade spatially stable. The previous
# threshold depended on step&15, so as the missile advanced the dither pattern
# itself moved and created avoidable pixel churn. A screen-anchored Bayer 4x4
# pattern preserves the same 1/16 -> 16/16 density ramp but stable pixels remain
# stable whenever geometry overlaps between consecutive frames.
old_trail = r'''void drawMissileTrailFade64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
  constexpr int TRAIL_PX = 64;
  // Ordered 1-bit dithering. The tail is sparse/near-white and density rises
  // deterministically toward the missile head, so no grayscale/AA path is used.
  constexpr uint8_t ORDER_16[16] = {0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15};

  const int dx = x - startX;
  const int dy = y - startY;
  const int span = std::max(std::abs(dx), std::abs(dy));
  if (span <= 0) return;

  const int visible = std::min(TRAIL_PX, span);
  const int tailX = x - static_cast<int>((static_cast<int32_t>(dx) * visible) / span);
  const int tailY = y - static_cast<int>((static_cast<int32_t>(dy) * visible) / span);

  for (int step = 0; step <= visible; ++step) {
    const int px = tailX + static_cast<int>((static_cast<int32_t>(x - tailX) * step) / visible);
    const int py = tailY + static_cast<int>((static_cast<int32_t>(y - tailY) * step) / visible);
    // 1/16 black at the tail -> 16/16 at the head.
    const uint8_t density = static_cast<uint8_t>(1 + (step * 15) / visible);
    if (ORDER_16[step & 15] < density) renderer.fillRect(px, py, 1, 1, true);
  }
}
'''
new_trail = r'''void drawMissileTrailFade64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
  constexpr int TRAIL_PX = 64;
  // Screen-anchored ordered 4x4 Bayer dither. Density still rises from 1/16 at
  // the tail to 16/16 at the head, but the threshold for a given pixel depends
  // only on its absolute coordinates, not on a moving trail step index.
  constexpr uint8_t BAYER_4X4[16] = {
      0, 8, 2, 10,
      12, 4, 14, 6,
      3, 11, 1, 9,
      15, 7, 13, 5,
  };

  const int dx = x - startX;
  const int dy = y - startY;
  const int span = std::max(std::abs(dx), std::abs(dy));
  if (span <= 0) return;

  const int visible = std::min(TRAIL_PX, span);
  const int tailX = x - static_cast<int>((static_cast<int32_t>(dx) * visible) / span);
  const int tailY = y - static_cast<int>((static_cast<int32_t>(dy) * visible) / span);

  for (int step = 0; step <= visible; ++step) {
    const int px = tailX + static_cast<int>((static_cast<int32_t>(x - tailX) * step) / visible);
    const int py = tailY + static_cast<int>((static_cast<int32_t>(y - tailY) * step) / visible);
    const uint8_t density = static_cast<uint8_t>(1 + (step * 15) / visible);
    const uint8_t threshold = BAYER_4X4[((py & 3) << 2) | (px & 3)];
    if (threshold < density) renderer.fillRect(px, py, 1, 1, true);
  }
}
'''
replace_once(CPP, old_trail, new_trail)

# Give the combined A/B candidate a distinct benchmark identity.
replace_once(
    CPP,
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-bench.csv";',
)
text = Path(CPP).read_text()
text = text.replace('MISSILE-A2-RECORD-WAVE', 'MISSILE-A2-OPT12')
text = text.replace('game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave-started',
                    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-started')
text = text.replace('game-a2-lite-pll0f-sparse-trail64-fade-header-hud-record-wave,%lu,%lu,%lu,%lu,%lu',
                    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12,%lu,%lu,%lu,%lu,%lu')
Path(CPP).write_text(text)

print("Missile OPT12: redundant sparse DTM1 pre-upload removed + spatial Bayer Trail64 applied")
