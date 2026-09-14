from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old_trail = r'''void drawMissileTrail64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
  constexpr int TRAIL_PX = 64;
  const int dx = x - startX;
  const int dy = y - startY;
  const int span = std::max(std::abs(dx), std::abs(dy));
  int tailX = startX;
  int tailY = startY;
  if (span > TRAIL_PX) {
    tailX = x - static_cast<int>((static_cast<int32_t>(dx) * TRAIL_PX) / span);
    tailY = y - static_cast<int>((static_cast<int32_t>(dy) * TRAIL_PX) / span);
  }
  renderer.drawLine(tailX, tailY, x, y, 1, true);
}
'''
new_trail = r'''void drawMissileTrailFade64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
  constexpr int TRAIL_PX = 64;
  // Stable ordered 1-bit dither: sparse/near-white at the tail, dense black
  // near the missile head. No grayscale/AA display path is involved.
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
    const uint8_t density = static_cast<uint8_t>(1 + (step * 15) / visible);
    if (ORDER_16[step & 15] < density) renderer.fillRect(px, py, 1, 1, true);
  }
}
'''
if old_trail not in text:
    raise SystemExit("Trail64 helper anchor not found")
text = text.replace(old_trail, new_trail, 1)
text = text.replace("drawMissileTrail64(renderer, missile.startX, missile.startY, x, y);",
                    "drawMissileTrailFade64(renderer, missile.startX, missile.startY, x, y);")

old_exit = '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  // Purge residual gameplay charge before the next activity paints over it.
  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  releaseWindowShadow();
  Activity::onExit();
}
'''
new_exit = '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  releaseWindowShadow();
  Activity::onExit();
}
'''
if old_exit not in text:
    raise SystemExit("onExit HALF scrub anchor not found")
text = text.replace(old_exit, new_exit, 1)

old_menu = '''void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = difficulty_;
'''
new_menu = '''void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();
  viewMode_ = ViewMode::Menu;
  menuScrubPending_ = true;
  selectedIndex_ = difficulty_;
'''
if old_menu not in text:
    raise SystemExit("returnToMenu anchor not found")
text = text.replace(old_menu, new_menu, 1)

text = text.replace(
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-trail64-clean-bench.csv";',
    'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-trail64-fade-menu-scrub-bench.csv";',
    1,
)
text = text.replace(
    'Storage.openFileForWrite("MISSILE-A2-PLL0F-TRAIL64", BENCH_PATH, file)',
    'Storage.openFileForWrite("MISSILE-A2-TRAIL64-FADE", BENCH_PATH, file)',
)
text = text.replace(
    'game-a2-lite-pll0f-trail64-clean-started',
    'game-a2-lite-pll0f-trail64-fade-menu-scrub-started',
    1,
)
text = text.replace(
    'game-a2-lite-pll0f-trail64-clean,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-trail64-fade-menu-scrub,%lu,%lu,%lu,%lu,%lu',
    1,
)

CPP.write_text(text)
print("Missile non-sparse Trail64 fade + clipped explosions + menu HALF scrub + normal exit applied")
