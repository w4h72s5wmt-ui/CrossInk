from pathlib import Path

p = Path('src/activities/home/MissileCommandActivity.cpp')
s = p.read_text()

def r(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'{label} anchor missing')
    s = s.replace(old, new, 1)

cache = r'''
constexpr uint8_t EXP_ROT_COUNT = 4;
constexpr uint8_t EXP_VERTS = 8;
struct ExpPt { int8_t x; int8_t y; };
using ExpContour = std::array<ExpPt, EXP_VERTS>;
std::array<std::array<ExpContour, EXPLOSION_MAX_RADIUS + 1>, EXP_ROT_COUNT> expCache{};
bool expCacheReady = false;

void prepareExplosionCache(bool rebuild = false) {
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
r('void drawClippedLine1px(GfxRenderer& renderer, const Rect& clip, int x0, int y0, int x1, int y1) {\n', cache + 'void drawClippedLine1px(GfxRenderer& renderer, const Rect& clip, int x0, int y0, int x1, int y1) {\n', 'cache')
r('void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius) {\n', 'void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius, uint8_t rot) {\n', 'signature')
r('''  const int d = std::max(1, (radius * 181 + 128) / 256);  // ~= r / sqrt(2)\n  const int vx[8] = {x + radius, x + d, x, x - d, x - radius, x - d, x, x + d};\n  const int vy[8] = {y, y + d, y + radius, y + d, y, y - d, y - radius, y - d};\n  for (int i = 0; i < 8; ++i)\n    drawClippedLine1px(renderer, clip, vx[i], vy[i], vx[(i + 1) & 7], vy[(i + 1) & 7]);\n\n  // White interior by design: outer 1-bit contour only.\n''', '''  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);\n  const ExpContour& c = expCache[rot % EXP_ROT_COUNT][cr];\n  for (uint8_t i = 0; i < EXP_VERTS; ++i) {\n    const ExpPt& a = c[i];\n    const ExpPt& b = c[(i + 1) & 7];\n    drawClippedLine1px(renderer, clip, x + a.x, y + a.y, x + b.x, y + b.y);\n  }\n\n  // White interior by design: outer 1-bit contour only.\n''', 'rotated contour')
r('    explosion.phase = 0;\n    explosion.phaseElapsedUs = 0;\n', '    explosion.phase = static_cast<uint8_t>(esp_random() % EXP_ROT_COUNT);\n    explosion.phaseElapsedUs = 0;\n', 'random orientation')
r('drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs));', 'drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs), explosion.phase);', 'draw call')
r('void MissileCommandActivity::onEnter() {\n  Activity::onEnter();\n', 'void MissileCommandActivity::onEnter() {\n  Activity::onEnter();\n  prepareExplosionCache();\n', 'initial cache')
r('void MissileCommandActivity::startWave() {\n  enemies_ = {};\n', 'void MissileCommandActivity::startWave() {\n  prepareExplosionCache(true);\n  enemies_ = {};\n', 'wave cache')

s = s.replace('/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-basemode2-bench.csv', '/missile-command-bm3-rotcache-bench.csv')
s = s.replace('/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-basemode2-trace.csv', '/missile-command-bm3-rotcache-trace.csv')
s = s.replace('game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-basemode2-started', 'bm3-rotcache-started')
s = s.replace('game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-explosion2-basemode2,%lu,%lu,%lu,%lu,%lu', 'bm3-rotcache,%lu,%lu,%lu,%lu,%lu')
s = s.replace('MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF-EXP2-BASEMODE2', 'MISSILE-BM3-ROTCACHE')
r('char line[128];', 'char line[192];', 'bench buffer')

p.write_text(s)
print('BaseMode3 RotCache + bench fix applied')
