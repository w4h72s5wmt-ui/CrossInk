from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:240]!r}")
    text = text.replace(old, new, 1)


# BaseMode3 cached four almost-identical static orientations. BaseMode4 keeps
# the no-trig hot path but makes the effect deliberately obvious:
#   * 8 cached orientations, 45 degrees apart
#   * strongly asymmetric/jagged contour, same max radius envelope
#   * random start angle and random direction per explosion
#   * animated orientation derived from elapsed time (~one 45-degree step per
#     recurrent e-paper frame), with no geometry work in the gameplay loop
replace_once(
    "constexpr uint8_t EXP_ROT_COUNT = 4;\n",
    "constexpr uint8_t EXP_ROT_COUNT = 8;\n"
    "constexpr uint32_t EXP_ROT_STEP_US = 120000;\n",
    "rotation count",
)

old_prepare = r'''void prepareExplosionCache(bool rebuild = false) {
  if (expCacheReady && !rebuild) return;
  constexpr int16_t cq[32] = {1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200,0,200,392,569,724,851,946,1004};
  constexpr int16_t sq[32] = {0,200,392,569,724,851,946,1004,1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200};
  const auto q10 = [](int32_t v) { return static_cast<int8_t>((v >= 0 ? v + 512 : v - 512) / 1024); };
  for (uint8_t rot = 0; rot < EXP_ROT_COUNT; ++rot) {
    for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {
      for (uint8_t v = 0; v < EXP_VERTS; ++v) {
        const uint8_t a = static_cast<uint8_t>((rot + v * 4) & 31);
        expCache[rot][radius][v] = {q10(radius * cq[a]), q10(radius * sq[a])};
      }
    }
  }
  expCacheReady = true;
}
'''

new_prepare = r'''void prepareExplosionCache(bool rebuild = false) {
  if (expCacheReady && !rebuild) return;
  constexpr int16_t cq[32] = {1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200,0,200,392,569,724,851,946,1004};
  constexpr int16_t sq[32] = {0,200,392,569,724,851,946,1004,1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200};
  // Deliberately asymmetric radial profile. The longest spike still reaches the
  // accepted Explosion2 radius, so the overall explosion size is not reduced.
  constexpr uint16_t radialQ10[EXP_VERTS] = {1024, 540, 900, 620, 980, 500, 860, 680};
  const auto q10 = [](int32_t v) { return static_cast<int8_t>((v >= 0 ? v + 512 : v - 512) / 1024); };
  for (uint8_t rot = 0; rot < EXP_ROT_COUNT; ++rot) {
    for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {
      for (uint8_t v = 0; v < EXP_VERTS; ++v) {
        // 32-entry table = 11.25 degrees. rot*4 therefore advances by a very
        // visible 45 degrees, not the subtle BaseMode3 11.25-degree offset.
        const uint8_t a = static_cast<uint8_t>(((rot * 4) + v * 4) & 31);
        const int32_t scaledRadius =
            (static_cast<int32_t>(radius) * radialQ10[v] + 512) / 1024;
        expCache[rot][radius][v] = {q10(scaledRadius * cq[a]), q10(scaledRadius * sq[a])};
      }
    }
  }
  expCacheReady = true;
}

uint8_t explosionRotationIndex(uint32_t ageUs, uint8_t seed) {
  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);
  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_ROT_STEP_US) & 0x07u);
  if ((seed & 0x08u) != 0)
    return static_cast<uint8_t>((start + EXP_ROT_COUNT - step) & 0x07u);
  return static_cast<uint8_t>((start + step) & 0x07u);
}
'''
replace_once(old_prepare, new_prepare, "animated irregular cache")

replace_once(
    "    explosion.phase = static_cast<uint8_t>(esp_random() % EXP_ROT_COUNT);\n"
    "    explosion.phaseElapsedUs = 0;\n",
    "    const uint32_t explosionRnd = esp_random();\n"
    "    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3));\n"
    "    explosion.phaseElapsedUs = 0;\n",
    "random start and direction",
)

replace_once(
    "drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs), explosion.phase);",
    "drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs),\n"
    "                           explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase));",
    "animated draw index",
)

# Keep PROFILE1/summary output distinct for a clean A/B test against RotCache.
text = text.replace("/missile-command-bm3-rotcache-bench.csv", "/missile-command-bm4-rotanim-bench.csv")
text = text.replace("/missile-command-bm3-rotcache-trace.csv", "/missile-command-bm4-rotanim-trace.csv")
text = text.replace("bm3-rotcache-started", "bm4-rotanim-started")
text = text.replace("bm3-rotcache,%lu,%lu,%lu,%lu,%lu", "bm4-rotanim,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM3-ROTCACHE", "MISSILE-BM4-ROTANIM")

CPP.write_text(text)
print("Missile BaseMode4 RotAnim: 45-degree animated irregular precached explosions applied")
