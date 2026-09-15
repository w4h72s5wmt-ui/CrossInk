from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

# Explosion animation is intentionally decoupled from the old ~592 ms legacy
# gameplay frame. Missile motion remains time-normalized exactly as before, but
# explosions now update from real synchronized frame time so they visibly grow
# on almost every optimized e-paper frame.
old_const = "constexpr uint32_t LEGACY_GAMEPLAY_FRAME_US = 592000;\n"
new_const = (
    "constexpr uint32_t LEGACY_GAMEPLAY_FRAME_US = 592000;\n"
    "constexpr uint32_t EXPLOSION_GROW_US = 520000;\n"
    "constexpr uint32_t EXPLOSION_HOLD_US = 160000;\n"
    "constexpr uint32_t EXPLOSION_SHRINK_US = 840000;\n"
    "constexpr uint32_t EXPLOSION_TOTAL_US = EXPLOSION_GROW_US + EXPLOSION_HOLD_US + EXPLOSION_SHRINK_US;\n"
    "constexpr int EXPLOSION_MIN_RADIUS = 4;\n"
    "constexpr int EXPLOSION_MAX_RADIUS = 36;\n"
)
if old_const not in text:
    raise SystemExit("legacy gameplay timing constant anchor not found")
text = text.replace(old_const, new_const, 1)

old_radius = r'''int explosionRadius(uint8_t phase) {
  return phase <= 3 ? 8 + phase * 9 : 8 + (6 - phase) * 9;
}
'''
new_radius = r'''int explosionRadius(uint32_t ageUs) {
  if (ageUs >= EXPLOSION_TOTAL_US) return 0;
  if (ageUs < EXPLOSION_GROW_US) {
    const uint32_t span = static_cast<uint32_t>(EXPLOSION_MAX_RADIUS - EXPLOSION_MIN_RADIUS);
    return EXPLOSION_MIN_RADIUS + static_cast<int>((span * ageUs + EXPLOSION_GROW_US / 2) / EXPLOSION_GROW_US);
  }
  ageUs -= EXPLOSION_GROW_US;
  if (ageUs < EXPLOSION_HOLD_US) return EXPLOSION_MAX_RADIUS;
  ageUs -= EXPLOSION_HOLD_US;
  const uint32_t span = static_cast<uint32_t>(EXPLOSION_MAX_RADIUS - EXPLOSION_MIN_RADIUS);
  const uint32_t drop = (span * ageUs + EXPLOSION_SHRINK_US / 2) / EXPLOSION_SHRINK_US;
  return std::max(EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS - static_cast<int>(drop));
}
'''
if old_radius not in text:
    raise SystemExit("explosionRadius anchor not found")
text = text.replace(old_radius, new_radius, 1)

old_draw = r'''void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius) {
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
'''
new_draw = r'''void drawClippedLine1px(GfxRenderer& renderer, const Rect& clip, int x0, int y0, int x1, int y1) {
  const int clipRight = clip.x + clip.width - 1;
  const int clipBottom = clip.y + clip.height - 1;
  const int dx = std::abs(x1 - x0);
  const int sx = x0 < x1 ? 1 : -1;
  const int dy = -std::abs(y1 - y0);
  const int sy = y0 < y1 ? 1 : -1;
  int err = dx + dy;
  while (true) {
    if (x0 >= clip.x && x0 <= clipRight && y0 >= clip.y && y0 <= clipBottom)
      renderer.fillRect(x0, y0, 1, 1, true);
    if (x0 == x1 && y0 == y1) break;
    const int e2 = err * 2;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}

void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius) {
  if (radius <= 2) {
    const int x0 = std::max(x - 1, clip.x);
    const int y0 = std::max(y - 1, clip.y);
    const int x1 = std::min(x + 1, clip.x + clip.width - 1);
    const int y1 = std::min(y + 1, clip.y + clip.height - 1);
    if (x0 <= x1 && y0 <= y1) renderer.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, true);
    return;
  }

  // Rounder 1-bit silhouette than the previous nested squares: an outer octagon
  // plus a smaller diamond/core. Everything remains strictly clipped to the
  // gameplay field, so ground/header cleanup and dirty-window bounds stay safe.
  const int d = std::max(1, (radius * 181 + 128) / 256);  // ~= r / sqrt(2)
  const int vx[8] = {x + radius, x + d, x, x - d, x - radius, x - d, x, x + d};
  const int vy[8] = {y, y + d, y + radius, y + d, y, y - d, y - radius, y - d};
  for (int i = 0; i < 8; ++i)
    drawClippedLine1px(renderer, clip, vx[i], vy[i], vx[(i + 1) & 7], vy[(i + 1) & 7]);

  const int inner = std::max(2, radius * 3 / 5);
  drawClippedLine1px(renderer, clip, x, y - inner, x + inner, y);
  drawClippedLine1px(renderer, clip, x + inner, y, x, y + inner);
  drawClippedLine1px(renderer, clip, x, y + inner, x - inner, y);
  drawClippedLine1px(renderer, clip, x - inner, y, x, y - inner);

  const int core = std::max(1, radius / 7);
  const int x0 = std::max(x - core, clip.x);
  const int y0 = std::max(y - core, clip.y);
  const int x1 = std::min(x + core, clip.x + clip.width - 1);
  const int y1 = std::min(y + core, clip.y + clip.height - 1);
  if (x0 <= x1 && y0 <= y1) renderer.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, true);
}
'''
if old_draw not in text:
    raise SystemExit("clipped explosion renderer anchor not found")
text = text.replace(old_draw, new_draw, 1)

old_tick = r'''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    explosion.phaseElapsedUs += gameplayElapsedUs;
    if (explosion.phaseElapsedUs < LEGACY_GAMEPLAY_FRAME_US) continue;
    explosion.phaseElapsedUs -= LEGACY_GAMEPLAY_FRAME_US;
    if (++explosion.phase >= 7) explosion.active = false;
  }
'''
new_tick = r'''  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    const uint64_t nextAge = static_cast<uint64_t>(explosion.phaseElapsedUs) + gameplayElapsedUs;
    explosion.phaseElapsedUs = static_cast<uint32_t>(std::min<uint64_t>(nextAge, EXPLOSION_TOTAL_US));
    if (explosion.phaseElapsedUs >= EXPLOSION_TOTAL_US) explosion.active = false;
  }
'''
if old_tick not in text:
    raise SystemExit("Stage-B explosion timing anchor not found")
text = text.replace(old_tick, new_tick, 1)

count = text.count("explosionRadius(explosion.phase)")
if count != 2:
    raise SystemExit(f"expected 2 explosionRadius phase call sites, found {count}")
text = text.replace("explosionRadius(explosion.phase)", "explosionRadius(explosion.phaseElapsedUs)")

# Distinct PROFILE1 filenames/identity for clean A/B against the validated
# EntryHalf baseline. Driver/display instrumentation is otherwise unchanged.
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-trace.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-trace.csv',
)
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF',
                    'MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF-EXP2')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2,%lu,%lu,%lu,%lu,%lu',
)

CPP.write_text(text)
print("Missile Explosion2: continuous 1.52 s animation + clipped octagon/diamond rendering applied")
