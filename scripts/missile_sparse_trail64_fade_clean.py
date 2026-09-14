from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:220]!r}")
    p.write_text(text.replace(old, new, 1))


CPP = "src/activities/home/MissileCommandActivity.cpp"

# Applied AFTER Stage-B + gameplay timing + Hybrid-A + A2-Lite + PLL0F + sparse-DTM.
# Keep the validated sparse controller path unchanged. This patch only changes
# Missile rendering/cleanup and gives this combined experiment its own benchmark.

old_helpers = r'''void drawExplosion(GfxRenderer& renderer, int x, int y, int radius) {
  if (radius <= 1) {
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
    return;
  }
  renderer.drawRect(x - radius, y - radius, radius * 2, radius * 2, 1, true);
  const int inner = std::max(1, radius / 2);
  renderer.drawRect(x - inner, y - inner, inner * 2, inner * 2, 1, true);
}
'''
new_helpers = r'''void drawClippedRectOutline(GfxRenderer& renderer, const Rect& clip, int x, int y, int w, int h) {
  if (w <= 0 || h <= 0 || clip.width <= 0 || clip.height <= 0) return;
  const int left = x;
  const int right = x + w - 1;
  const int top = y;
  const int bottom = y + h - 1;
  const int clipLeft = clip.x;
  const int clipRight = clip.x + clip.width - 1;
  const int clipTop = clip.y;
  const int clipBottom = clip.y + clip.height - 1;

  const auto hLine = [&](int yy) {
    if (yy < clipTop || yy > clipBottom) return;
    const int x0 = std::max(left, clipLeft);
    const int x1 = std::min(right, clipRight);
    if (x0 <= x1) renderer.fillRect(x0, yy, x1 - x0 + 1, 1, true);
  };
  const auto vLine = [&](int xx) {
    if (xx < clipLeft || xx > clipRight) return;
    const int y0 = std::max(top, clipTop);
    const int y1 = std::min(bottom, clipBottom);
    if (y0 <= y1) renderer.fillRect(xx, y0, 1, y1 - y0 + 1, true);
  };

  hLine(top);
  if (bottom != top) hLine(bottom);
  vLine(left);
  if (right != left) vLine(right);
}

void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius) {
  if (radius <= 1) {
    const int x0 = std::max(x - 1, clip.x);
    const int y0 = std::max(y - 1, clip.y);
    const int x1 = std::min(x + 1, clip.x + clip.width - 1);
    const int y1 = std::min(y + 1, clip.y + clip.height - 1);
    if (x0 <= x1 && y0 <= y1) renderer.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, true);
    return;
  }
  drawClippedRectOutline(renderer, clip, x - radius, y - radius, radius * 2, radius * 2);
  const int inner = std::max(1, radius / 2);
  drawClippedRectOutline(renderer, clip, x - inner, y - inner, inner * 2, inner * 2);
}

void drawMissileTrailFade64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
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
replace_once(CPP, old_helpers, new_helpers)

# Leaving Missile Command entirely also purges residual gameplay charge.
replace_once(CPP,
             "void MissileCommandActivity::onExit() {\n"
             "  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n"
             "  saveHighScore();\n"
             "  releaseWindowShadow();\n"
             "  Activity::onExit();\n"
             "}\n",
             "void MissileCommandActivity::onExit() {\n"
             "  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();\n"
             "  saveHighScore();\n"
             "  renderer.displayBuffer(HalDisplay::HALF_REFRESH);\n"
             "  releaseWindowShadow();\n"
             "  Activity::onExit();\n"
             "}\n")

# Replace full launch->head trajectories with a deterministic faded 64 px tail.
replace_once(CPP,
             "    renderer.drawLine(missile.startX, missile.startY, x, y, 1, true);\n"
             "    renderer.fillRect(x - 1, y - 1, 3, 3, true);\n",
             "    drawMissileTrailFade64(renderer, missile.startX, missile.startY, x, y);\n"
             "    renderer.fillRect(x - 1, y - 1, 3, 3, true);\n")
replace_once(CPP,
             "    renderer.drawLine(missile.startX, missile.startY, x, y, 1, true);\n"
             "    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);\n",
             "    drawMissileTrailFade64(renderer, missile.startX, missile.startY, x, y);\n"
             "    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);\n")

# Hard clip explosions to the interior that drawPlayingFrame clears each frame.
replace_once(CPP,
             "  for (const auto& explosion : explosions_) {\n"
             "    if (explosion.active) drawExplosion(renderer, explosion.x, explosion.y, explosionRadius(explosion.phase));\n"
             "  }\n",
             "  const Rect explosionClip{geometry.field.x + 1, geometry.field.y + 1,\n"
             "                           std::max(1, geometry.field.width - 2),\n"
             "                           std::max(1, geometry.field.height - 2)};\n"
             "  for (const auto& explosion : explosions_) {\n"
             "    if (explosion.active)\n"
             "      drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phase));\n"
             "  }\n")

# Separate benchmark identity from sparse-only and Trail64-only runs.
replace_once(CPP,
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-wave-scrub-bench.csv";',
             'constexpr const char* BENCH_PATH = "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-clean-bench.csv";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-A2-LITE-SPARSE", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-SPARSE-TRAIL64", BENCH_PATH, file)')
replace_once(CPP,
             'const char started[] = "game-a2-lite-pll0f-sparse-wave-scrub-started,0,0,0,0,0\\n";',
             'const char started[] = "game-a2-lite-pll0f-sparse-trail64-fade-clean-started,0,0,0,0,0\\n";')
replace_once(CPP,
             'Storage.openFileForWrite("MISSILE-A2-LITE-SPARSE", BENCH_PATH, file)',
             'Storage.openFileForWrite("MISSILE-A2-SPARSE-TRAIL64", BENCH_PATH, file)')
replace_once(CPP,
             '"game-a2-lite-pll0f-sparse-wave-scrub,%lu,%lu,%lu,%lu,%lu\\n",',
             '"game-a2-lite-pll0f-sparse-trail64-fade-clean,%lu,%lu,%lu,%lu,%lu\\n",')

print("Missile sparse-DTM + Trail64 1-bit fade + clipped explosions + exit scrub applied")
