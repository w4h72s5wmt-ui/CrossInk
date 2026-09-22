from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:260]!r}")
    text = text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# BaseMode10 explosion polish
# Same cache dimensions, same vertex counts, same number of rendered edges,
# no extra trig and no extra recurrent draw pass.
#
# - Slightly asymmetric convex silhouettes: less "perfect CAD polygon", while
#   never extending beyond the accepted radius (so no larger dirty footprint).
# - Realistic morph profiles transition through neighbouring shapes rather than
#   harsh pentagon<->octagon jumps.
# - The visual X/Y offset follows a smooth 8-step loop instead of jumping by a
#   stride of 3/5. Direction and starting phase remain explosion-seeded.
# ---------------------------------------------------------------------------

replace_once(
    '''  // Q10 unit vectors for regular pentagon / hexagon / octagon vertices.
  constexpr uint8_t vertexCount[EXP_SHAPE_COUNT] = {5, 6, 8};
  constexpr int16_t baseX[EXP_SHAPE_COUNT][EXP_VERTS] = {
      {1024, 316, -828, -828, 316, 0, 0, 0},
      {1024, 512, -512, -1024, -512, 512, 0, 0},
      {1024, 724, 0, -724, -1024, -724, 0, 724},
  };
  constexpr int16_t baseY[EXP_SHAPE_COUNT][EXP_VERTS] = {
      {0, 974, 602, -602, -974, 0, 0, 0},
      {0, 887, 887, 0, -887, -887, 0, 0},
      {0, 724, 1024, 724, 0, -724, -1024, -724},
  };
''',
    '''  // Q10 convex silhouettes. Keep the same 5/6/8 vertices and the same
  // maximum radius, but introduce a few-percent radial irregularity so the
  // blast feels hand-shaped rather than geometrically perfect.
  constexpr uint8_t vertexCount[EXP_SHAPE_COUNT] = {5, 6, 8};
  constexpr int16_t baseX[EXP_SHAPE_COUNT][EXP_VERTS] = {
      {1024, 296, -815, -789, 314, 0, 0, 0},
      {1024, 488, -504, -992, -480, 508, 0, 0},
      {1024, 684, 0, -713, -1000, -707, 0, 718},
  };
  constexpr int16_t baseY[EXP_SHAPE_COUNT][EXP_VERTS] = {
      {0, 913, 592, -574, -966, 0, 0, 0},
      {0, 846, 873, 0, -831, -880, 0, 0},
      {0, 684, 1008, 713, 0, -707, -1016, -718},
  };
''',
    "organic cached contours",
)

replace_once(
    "constexpr uint32_t EXP_REAL_SHAPE_STEP_US = 190000;\n",
    "constexpr uint32_t EXP_REAL_SHAPE_STEP_US = 220000;\n",
    "slower organic morph cadence",
)

replace_once(
    '''  // Precalculate subtle visual centre motion as a function of radius. At
  // max radius the displacement reaches ~6-8 px and naturally tends to
  // zero for the smallest explosion frames.
  constexpr int16_t offsetXQ10[EXP_REAL_OFFSET_COUNT] = {0, 171, -171, 228, -228, 114, -114, 200};
  constexpr int16_t offsetYQ10[EXP_REAL_OFFSET_COUNT] = {0, -143, 143, 114, -114, 228, -228, 171};
''',
    '''  // Smooth clockwise loop around the logical blast centre. Peak offset
  // stays in the same visible range, but adjacent states are spatially close,
  // which looks like drifting pressure rather than random jitter.
  constexpr int16_t offsetXQ10[EXP_REAL_OFFSET_COUNT] = {0, 145, 205, 145, 0, -145, -205, -145};
  constexpr int16_t offsetYQ10[EXP_REAL_OFFSET_COUNT] = {-180, -127, 0, 127, 180, 127, 0, -127};
''',
    "smooth offset loop",
)

replace_once(
    '''  // Eight random-looking morph profiles. Adjacent states never repeat, so the
  // pentagon / hexagon / octagon change is visible inside each explosion.
  constexpr uint8_t shapeProfiles[8][8] = {
      {0, 1, 2, 1, 0, 2, 0, 1}, {1, 0, 2, 0, 1, 2, 1, 0},
      {2, 0, 1, 0, 2, 1, 2, 0}, {0, 2, 1, 2, 0, 1, 0, 2},
      {1, 2, 0, 2, 1, 0, 1, 2}, {2, 1, 0, 1, 2, 0, 2, 1},
      {0, 1, 0, 2, 1, 2, 0, 2}, {2, 0, 2, 1, 0, 1, 2, 1},
  };
  const uint8_t stage = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);
  const uint8_t profile = static_cast<uint8_t>((seed >> 5) & 0x07u);
  return static_cast<uint8_t>((base + shapeProfiles[profile][stage]) % EXP_SHAPE_COUNT);
''',
    '''  // Seeded but visually smoother morph paths. 0/1/2 are absolute
  // pentagon/hexagon/octagon indices and every large transition goes through
  // the hexagon, avoiding abrupt 5<->8 vertex jumps.
  constexpr uint8_t shapeProfiles[8][8] = {
      {0, 1, 2, 1, 0, 1, 2, 1}, {1, 2, 1, 0, 1, 2, 1, 0},
      {2, 1, 0, 1, 2, 1, 0, 1}, {0, 1, 0, 1, 2, 1, 0, 1},
      {1, 0, 1, 2, 1, 0, 1, 2}, {2, 1, 2, 1, 0, 1, 2, 1},
      {0, 1, 2, 1, 2, 1, 0, 1}, {1, 2, 1, 0, 1, 0, 1, 2},
  };
  const uint8_t stage = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);
  const uint8_t profile = static_cast<uint8_t>((seed >> 5) & 0x07u);
  return shapeProfiles[profile][stage];
''',
    "smooth seeded shape profiles",
)

replace_once(
    '''  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);
  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);
  const uint8_t stride = (seed & 0x40u) != 0 ? 5u : 3u;
  const uint8_t travel = static_cast<uint8_t>((step * stride) & 0x07u);
  const uint8_t stage = (seed & 0x08u) != 0
                            ? static_cast<uint8_t>((start + EXP_REAL_OFFSET_COUNT - travel) & 0x07u)
                            : static_cast<uint8_t>((start + travel) & 0x07u);
''',
    '''  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);
  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);
  const uint8_t stage = (seed & 0x08u) != 0
                            ? static_cast<uint8_t>((start + EXP_REAL_OFFSET_COUNT - step) & 0x07u)
                            : static_cast<uint8_t>((start + step) & 0x07u);
''',
    "smooth seeded offset travel",
)

text = text.replace("/missile-command-bm9-score-wave-hitpoly-bench.csv",
                    "/missile-command-bm10-explosion-polish-bench.csv")
text = text.replace("/missile-command-bm9-score-wave-hitpoly-trace.csv",
                    "/missile-command-bm10-explosion-polish-trace.csv")
text = text.replace("bm9-score-wave-hitpoly-started", "bm10-explosion-polish-started")
text = text.replace("bm9-score-wave-hitpoly,%lu,%lu,%lu,%lu,%lu",
                    "bm10-explosion-polish,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM9-SCORE-WAVE-HITPOLY", "MISSILE-BM10-EXPLOSION-POLISH")

CPP.write_text(text)
print("Missile BaseMode10: zero-extra-cost organic explosion polish applied")
