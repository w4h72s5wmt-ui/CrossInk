from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:280]!r}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# BaseMode8
#   1) Stop hammering the Score digits on every score increment. Redraw the
#      displayed score only every 2 seconds, then perform a two-pass local
#      white->value scrub of the score VALUE rectangle using the existing
#      byte-aligned displayWindow path. No display-driver/waveform changes.
#   2) In "Explosions réalistes" mode, collision uses the exact currently drawn
#      convex polygon, including live radius, morphing shape, rotation and X/Y
#      visual offset. Classic mode keeps the accepted circle hit test unchanged.
# ---------------------------------------------------------------------------

h = HDR.read_text()
h = replace_once(
    h,
    "  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;\n",
    "  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;\n"
    "  int64_t nextHudScoreCleanUs_ = 0;\n"
    "  bool hudScoreCleanPending_ = false;\n",
    "score clean state",
)
HDR.write_text(h)

c = CPP.read_text()

# Two seconds is deliberately much slower than gameplay cadence: the logical
# score remains immediate, only the e-ink presentation is batched.
c = replace_once(
    c,
    "constexpr int MISSILE_HUD_COLUMNS = 2;\n",
    "constexpr int MISSILE_HUD_COLUMNS = 2;\n"
    "constexpr int64_t MISSILE_SCORE_CLEAN_INTERVAL_US = 2000000;\n",
    "score clean interval",
)

# Full scene / wave / entry redraw already paints a clean current score. Start a
# fresh 2-second period from there rather than immediately scrubbing it again.
c = replace_once(
    c,
    "  hudScoreDrawn_ = score_;\n"
    "  hudHighScoreDrawn_ = highScore_;\n",
    "  hudScoreDrawn_ = score_;\n"
    "  hudHighScoreDrawn_ = highScore_;\n"
    "  nextHudScoreCleanUs_ = esp_timer_get_time() + MISSILE_SCORE_CLEAN_INTERVAL_US;\n"
    "  hudScoreCleanPending_ = false;\n",
    "full HUD score timer",
)

old_score_incremental = r'''  if (score_ > highScore_) highScore_ = score_;
  char hudValue[16];
  if (hudScoreDrawn_ != score_) {
    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));
    drawMissileHudValue(renderer, geometry.status, 0, hudValue);
    hudScoreDrawn_ = score_;
  }
'''
new_score_incremental = r'''  if (score_ > highScore_) highScore_ = score_;

  // Batch the visible Score number. It may lag the logical score by at most two
  // seconds, but its e-ink cell no longer accumulates a transition on every hit.
  const int64_t hudNowUs = esp_timer_get_time();
  if (nextHudScoreCleanUs_ == 0)
    nextHudScoreCleanUs_ = hudNowUs + MISSILE_SCORE_CLEAN_INTERVAL_US;
  if (hudNowUs >= nextHudScoreCleanUs_) {
    char hudValue[16];
    std::snprintf(hudValue, sizeof(hudValue), "%lu", static_cast<unsigned long>(score_));
    drawMissileHudValue(renderer, geometry.status, 0, hudValue);
    hudScoreDrawn_ = score_;
    hudScoreCleanPending_ = true;
    nextHudScoreCleanUs_ = hudNowUs + MISSILE_SCORE_CLEAN_INTERVAL_US;
  }
'''
c = replace_once(c, old_score_incremental, new_score_incremental, "2s score redraw")

# The normal Cluster1 refresh still handles gameplay. Just before it, when the
# 2-second score cadence fires, clean ONLY the numeric value rectangle:
#   panel old score -> white -> current score
# and then sync only those bytes in the app shadow. This avoids a full-screen
# HALF refresh and does not alter the frozen driver/waveform/PLL path.
score_clean_block = r'''
  if (!forceFullRefresh && hudScoreCleanPending_ && windowShadowValid_ && windowShadow_ != nullptr) {
    const GameGeometry scoreGeometry = gameGeometry(renderer, mappedInput);
    const Rect scoreValueRect = missileHudValueRect(scoreGeometry.status, 0);
    uint8_t* const scoreFb = display.getFrameBuffer();
    const uint16_t scorePanelW = display.getDisplayWidth();
    const uint16_t scorePanelH = display.getDisplayHeight();
    const uint16_t scoreWb = display.getDisplayWidthBytes();

    if (scoreFb != nullptr && scoreWb != 0 && scoreValueRect.width > 0 && scoreValueRect.height > 0) {
      const int sx0i = std::max(0, scoreValueRect.x & ~7);
      const int sx1i = std::min<int>(scorePanelW, (scoreValueRect.x + scoreValueRect.width + 7) & ~7);
      const int sy0i = std::max(0, scoreValueRect.y);
      const int sy1i = std::min<int>(scorePanelH, scoreValueRect.y + scoreValueRect.height);

      if (sx1i > sx0i && sy1i > sy0i) {
        const uint16_t sx = static_cast<uint16_t>(sx0i);
        const uint16_t sy = static_cast<uint16_t>(sy0i);
        const uint16_t sw = static_cast<uint16_t>(sx1i - sx0i);
        const uint16_t sh = static_cast<uint16_t>(sy1i - sy0i);

        // Pass 1: physically discharge the changing numeric area to white.
        renderer.fillRect(scoreValueRect.x, scoreValueRect.y, scoreValueRect.width, scoreValueRect.height, false);
        display.displayWindow(sx, sy, sw, sh, false);

        // Pass 2: paint the batched current value onto the now-clean cell.
        char cleanScoreValue[16];
        std::snprintf(cleanScoreValue, sizeof(cleanScoreValue), "%lu", static_cast<unsigned long>(hudScoreDrawn_));
        drawMissileHudValue(renderer, scoreGeometry.status, 0, cleanScoreValue);
        display.displayWindow(sx, sy, sw, sh, false);

        // The controller and framebuffer now agree. Acknowledge only this local
        // window in the app shadow; any deferred Cluster1 dirt elsewhere stays
        // dirty and is still mandatory for the normal refresh below.
        const uint16_t scoreCopyBytes = static_cast<uint16_t>(sw / 8);
        const uint16_t scoreMinByte = static_cast<uint16_t>(sx / 8);
        for (uint16_t row = 0; row < sh; ++row) {
          const uint32_t offset = static_cast<uint32_t>(sy + row) * scoreWb + scoreMinByte;
          memcpy(windowShadow_ + offset, scoreFb + offset, scoreCopyBytes);
        }
      }
    }
    hudScoreCleanPending_ = false;
  }

'''

render_anchor = '''  drawPlayingFrame();
  const int64_t missileProfileAfterDrawUs = esp_timer_get_time();

  // First frame establishes a complete controller baseline.'''
c = replace_once(
    c,
    render_anchor,
    '''  drawPlayingFrame();
  const int64_t missileProfileAfterDrawUs = esp_timer_get_time();
''' + score_clean_block + '''  // First frame establishes a complete controller baseline.''',
    "score clean render hook",
)

# Exact gameplay hitbox for Realistic Explosions. Keep the old circle path as-is
# whenever the checkbox is off.
old_collision = r'''      const int radius = explosionRadius(explosion.phaseElapsedUs);
      const int dx = ex - explosion.x;
      const int dy = ey - explosion.y;
      if (dx * dx + dy * dy > radius * radius) continue;
'''
new_collision = r'''      const int radius = explosionRadius(explosion.phaseElapsedUs);
      bool explosionHit = false;

      if (!realisticExplosions_) {
        // Accepted classic gameplay: circular collision around the logical
        // explosion centre.
        const int dx = ex - explosion.x;
        const int dy = ey - explosion.y;
        explosionHit = dx * dx + dy * dy <= radius * radius;
      } else {
        // Realistic mode: use the exact contour being rendered THIS frame.
        // Shape morph, 45-degree rotation, growing/shrinking radius and visual
        // X/Y drift all become real gameplay geometry.
        const uint8_t rot = explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase);
        const uint8_t shape = explosionShapeIndex(explosion.phaseElapsedUs, explosion.phase, true);
        const ExpPt visualOffset =
            explosionVisualOffset(explosion.phaseElapsedUs, explosion.phase, radius, true);
        const int cx = explosion.x + visualOffset.x;
        const int cy = explosion.y + visualOffset.y;
        const int localX = ex - cx;
        const int localY = ey - cy;
        const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);
        const ExpContour& contour = expCache[shape % EXP_SHAPE_COUNT][rot % EXP_ROT_COUNT][cr];

        // Convex polygon point test. All cached shapes are regular convex
        // polygons; a point is inside when edge cross-products do not change
        // sign. Cross==0 counts as a hit on the visible contour.
        bool positive = false;
        bool negative = false;
        for (uint8_t i = 0; i < contour.count; ++i) {
          const ExpPt& a = contour.points[i];
          const ExpPt& b = contour.points[(i + 1) % contour.count];
          const int32_t edgeX = static_cast<int32_t>(b.x) - a.x;
          const int32_t edgeY = static_cast<int32_t>(b.y) - a.y;
          const int32_t pointX = static_cast<int32_t>(localX) - a.x;
          const int32_t pointY = static_cast<int32_t>(localY) - a.y;
          const int32_t cross = edgeX * pointY - edgeY * pointX;
          positive = positive || cross > 0;
          negative = negative || cross < 0;
          if (positive && negative) break;
        }
        explosionHit = !(positive && negative);
      }

      if (!explosionHit) continue;
'''
c = replace_once(c, old_collision, new_collision, "realistic polygon collision")

# Separate telemetry identity.
c = c.replace("/missile-command-bm7-realistic-bench.csv", "/missile-command-bm8-score2s-hitpoly-bench.csv")
c = c.replace("/missile-command-bm7-realistic-trace.csv", "/missile-command-bm8-score2s-hitpoly-trace.csv")
c = c.replace("bm7-realistic-started", "bm8-score2s-hitpoly-started")
c = c.replace("bm7-realistic,%lu,%lu,%lu,%lu,%lu", "bm8-score2s-hitpoly,%lu,%lu,%lu,%lu,%lu")
c = c.replace("MISSILE-BM7-REALISTIC", "MISSILE-BM8-SCORE2S-HITPOLY")

CPP.write_text(c)
print("Missile BaseMode8: 2s clean Score cell + exact realistic polygon collision applied")
