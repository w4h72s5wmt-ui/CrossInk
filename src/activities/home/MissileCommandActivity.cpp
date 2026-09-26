#include "MissileCommandActivity.h"

#include <GfxRenderer.h>
#include <HalDisplay.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>

extern "C" {
extern volatile uint32_t crossink_missile_panel_kind;
extern volatile uint32_t crossink_missile_panel_upload_us;
extern volatile uint32_t crossink_missile_panel_setup_us;
extern volatile uint32_t crossink_missile_panel_drf_us;
extern volatile uint32_t crossink_missile_panel_resync_us;
}
#include <HalStorage.h>
#include <I18n.h>
#include <esp_random.h>
#include <esp_timer.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>

#include "MappedInputManager.h"
#include "activities/util/ConfirmationActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "fontIds.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;
constexpr const char SAVE_DIR[] = "/.crosspoint";
constexpr const char SAVE_PATH[] = "/.crosspoint/missile-command.bin";
constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";

constexpr const char MISSILE_PROFILE1_TRACE_PATH[] =
    "/missile-command-bm17-preselected-hard-speeds-trace.csv";
constexpr uint32_t MISSILE_PROFILE1_SAMPLES = 200;

struct MissileProfile1Row {
  uint32_t cycleUs = 0;
  uint32_t drawUs = 0;
  uint32_t refreshUs = 0;
  uint32_t dirtyPrepUs = 0;
  uint32_t panelCallUs = 0;
  uint32_t shadowCopyUs = 0;
  uint32_t panelUploadUs = 0;
  uint32_t panelSetupUs = 0;
  uint32_t panelDrfUs = 0;
  uint32_t panelResyncUs = 0;
  uint16_t dirtyTiles = 0;
  uint16_t refreshTiles = 0;
  uint16_t bboxW = 0;
  uint16_t bboxH = 0;
  uint8_t appMode = 0;      // 0=none,1=bbox,2=sparse,3=HALF,4=full-surface FAST
  uint8_t panelKind = 0;    // 1=bbox,2=sparse,3=HALF,4=FULL,5=full-surface FAST
  uint8_t forceFull = 0;
  uint8_t waveScrub = 0;
  uint8_t fullScene = 0;
  uint8_t catchupStart = 0;
  uint8_t clusterSplit = 0;
};

MissileProfile1Row* missileProfileRows = nullptr;
MissileProfile1Row missileProfilePending{};
uint32_t missileProfileCount = 0;
int64_t missileProfileLastStartUs = 0;
bool missileProfilePendingValid = false;
bool missileProfileSaved = false;

uint32_t missileRefreshDirtyPrepUs = 0;
uint32_t missileRefreshPanelCallUs = 0;
uint32_t missileRefreshShadowCopyUs = 0;
uint16_t missileRefreshDirtyTiles = 0;
uint16_t missileRefreshTiles = 0;
uint16_t missileRefreshBboxW = 0;
uint16_t missileRefreshBboxH = 0;
uint8_t missileRefreshAppMode = 0;
uint8_t missileRefreshClusterSplit = 0;

void saveMissileProfile1Trace() {
  if (missileProfileSaved || missileProfileRows == nullptr || missileProfileCount < MISSILE_PROFILE1_SAMPLES) return;
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE-PROFILE1", MISSILE_PROFILE1_TRACE_PATH, file)) return;
  const char header[] =
      "sample,cycle_us,draw_us,refresh_us,dirty_prep_us,panel_call_us,shadow_copy_us,app_mode,panel_kind,"
      "force_full,wave_scrub,full_scene,catchup_start,cluster_split,dirty_tiles,refresh_tiles,bbox_w,bbox_h,"
      "panel_upload_us,panel_setup_us,panel_drf_us,panel_resync_us\n";
  file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
  for (uint32_t i = 0; i < MISSILE_PROFILE1_SAMPLES; ++i) {
    const MissileProfile1Row& r = missileProfileRows[i];
    char line[320];
    const int n = std::snprintf(
        line, sizeof(line),
        "%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%lu,%lu,%lu,%lu\n",
        static_cast<unsigned long>(i + 1), static_cast<unsigned long>(r.cycleUs),
        static_cast<unsigned long>(r.drawUs), static_cast<unsigned long>(r.refreshUs),
        static_cast<unsigned long>(r.dirtyPrepUs), static_cast<unsigned long>(r.panelCallUs),
        static_cast<unsigned long>(r.shadowCopyUs), static_cast<unsigned>(r.appMode),
        static_cast<unsigned>(r.panelKind), static_cast<unsigned>(r.forceFull),
        static_cast<unsigned>(r.waveScrub), static_cast<unsigned>(r.fullScene),
        static_cast<unsigned>(r.catchupStart), static_cast<unsigned>(r.clusterSplit),
        static_cast<unsigned>(r.dirtyTiles), static_cast<unsigned>(r.refreshTiles),
        static_cast<unsigned>(r.bboxW), static_cast<unsigned>(r.bboxH),
        static_cast<unsigned long>(r.panelUploadUs), static_cast<unsigned long>(r.panelSetupUs),
        static_cast<unsigned long>(r.panelDrfUs), static_cast<unsigned long>(r.panelResyncUs));
    if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
  }
  file.close();
  missileProfileSaved = true;
}

void beginMissileProfile1Frame(int64_t nowUs, bool forceFull, bool waveScrub, bool fullScene, bool catchupStart) {
  if (!missileProfileSaved && missileProfileRows == nullptr) {
    missileProfileRows = static_cast<MissileProfile1Row*>(
        heap_caps_malloc(sizeof(MissileProfile1Row) * MISSILE_PROFILE1_SAMPLES,
                         MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }

  if (!missileProfileSaved && missileProfilePendingValid && missileProfileRows != nullptr) {
    const int64_t rawCycle = nowUs - missileProfileLastStartUs;
    if (rawCycle > 0 && rawCycle < 2000000) {
      missileProfilePending.cycleUs = static_cast<uint32_t>(rawCycle);
      if (missileProfileCount < MISSILE_PROFILE1_SAMPLES) {
        missileProfileRows[missileProfileCount++] = missileProfilePending;
      }
      if (missileProfileCount >= MISSILE_PROFILE1_SAMPLES) saveMissileProfile1Trace();
    } else {
      missileProfileCount = 0;
    }
  }

  missileProfileLastStartUs = nowUs;
  missileProfilePending = {};
  missileProfilePending.forceFull = forceFull ? 1 : 0;
  missileProfilePending.waveScrub = waveScrub ? 1 : 0;
  missileProfilePending.fullScene = fullScene ? 1 : 0;
  missileProfilePending.catchupStart = catchupStart ? 1 : 0;
  missileProfilePendingValid = !missileProfileSaved && missileProfileRows != nullptr;

  missileRefreshDirtyPrepUs = 0;
  missileRefreshPanelCallUs = 0;
  missileRefreshShadowCopyUs = 0;
  missileRefreshDirtyTiles = 0;
  missileRefreshTiles = 0;
  missileRefreshBboxW = 0;
  missileRefreshBboxH = 0;
  missileRefreshAppMode = 0;
  missileRefreshClusterSplit = 0;
  crossink_missile_panel_kind = 0;
  crossink_missile_panel_upload_us = 0;
  crossink_missile_panel_setup_us = 0;
  crossink_missile_panel_drf_us = 0;
  crossink_missile_panel_resync_us = 0;
}

constexpr const char WINDOW_BENCH_PATH[] = "/missile-command-window-stage2.csv";
constexpr uint32_t SAVE_MAGIC = 0x4D434D31;   // MCM1
constexpr uint32_t SCORE_MAGIC = 0x4D435331;  // MCS1
constexpr uint8_t SAVE_VERSION = 3;
constexpr uint8_t SCORE_VERSION = 2;

// Gameplay, touch and e-ink are intentionally locked to one 100 ms cadence.
// There is no catch-up simulation and no frame running ahead of the panel:
// one cycle consumes input, advances the world exactly once, renders that exact
// state, then waits for the FAST refresh to complete before another cycle.
constexpr int64_t GAME_FRAME_US = 100000;
// Stable pre-window build measured ~591.6 ms per synchronized game/display
// cycle. Missile speed values and explosion phases are legacy per-frame
// increments, so normalize them to that wall-clock duration rather than to
// the now-faster Stage-B refresh rate. This preserves gameplay speed while
// allowing the panel to render every optimized frame.
constexpr uint32_t LEGACY_GAMEPLAY_FRAME_US = 592000;
constexpr uint32_t EXPLOSION_GROW_US = 520000;
constexpr uint32_t EXPLOSION_HOLD_US = 160000;
constexpr uint32_t EXPLOSION_SHRINK_US = 840000;
constexpr uint32_t EXPLOSION_TOTAL_US = EXPLOSION_GROW_US + EXPLOSION_HOLD_US + EXPLOSION_SHRINK_US;
constexpr int EXPLOSION_MIN_RADIUS = 4;
constexpr int EXPLOSION_MAX_RADIUS = 36;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};


Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int height = mappedInput.hasTouchHardware() ? TouchHeaderBackButton::height(metrics, mappedInput)
                                                     : metrics.headerHeight;
  return Rect{0, metrics.topPadding, renderer.getScreenWidth(), height};
}

constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;
constexpr int MISSILE_SCORE_TABLE_GAP = 6;
constexpr int MISSILE_SCORE_RESET_GAP = 8;
constexpr int MISSILE_SCORE_RESET_BUTTON_HEIGHT = 44;
constexpr int MISSILE_SCORE_AREA_HEIGHT = MISSILE_SCORE_TABLE_HEIGHT + MISSILE_SCORE_TABLE_GAP +
                                          MISSILE_SCORE_RESET_GAP + MISSILE_SCORE_RESET_BUTTON_HEIGHT;

Rect menuRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + metrics.verticalSpacing;
  return Rect{0, top, renderer.getScreenWidth(),
              std::max(1, renderer.getScreenHeight() - top - metrics.buttonHintsHeight -
                              metrics.verticalSpacing - MISSILE_SCORE_AREA_HEIGHT)};
}

Rect missileScoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect list = menuRect(renderer, mappedInput);
  return Rect{metrics.contentSidePadding, list.y + list.height + MISSILE_SCORE_TABLE_GAP,
              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, MISSILE_SCORE_TABLE_HEIGHT};
}

Rect missileScoreResetButtonRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect table = missileScoreTableRect(renderer, mappedInput);
  return Rect{table.x, table.y + table.height + MISSILE_SCORE_RESET_GAP, table.width,
              MISSILE_SCORE_RESET_BUTTON_HEIGHT};
}

struct GameGeometry {
  Rect header;
  Rect status;
  Rect field;
  int groundY = 0;
};

GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const Rect status{0, 0, 0, 0};  // no in-game HUD strip
  const int fieldTop = header.y + header.height + metrics.verticalSpacing;
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  const Rect field{metrics.contentSidePadding, fieldTop,
                   renderer.getScreenWidth() - 2 * metrics.contentSidePadding,
                   std::max(80, footerTop - fieldTop - metrics.verticalSpacing)};
  return GameGeometry{header, status, field, field.y + field.height - 34};
}
bool pointInRect(const Rect& rect, int x, int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

Rect gameOverBox(const GfxRenderer& renderer) {
  const int width = std::min(380, renderer.getScreenWidth() - 36);
  constexpr int height = 170;
  return Rect{(renderer.getScreenWidth() - width) / 2,
              (renderer.getScreenHeight() - height) / 2, width, height};
}

Rect gameOverActionRect(const GfxRenderer& renderer) {
  const Rect box = gameOverBox(renderer);
  return Rect{box.x + 12, box.y + 106, box.width - 24, 48};
}

Rect waveCompleteBox(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int width = std::min(430, geometry.field.width - 40);
  const int height = std::min(272, geometry.field.height - 28);
  return Rect{geometry.field.x + (geometry.field.width - width) / 2,
              geometry.field.y + (geometry.field.height - height) / 2,
              width, height};
}

Rect waveCompleteActionRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect box = waveCompleteBox(renderer, mappedInput);
  return Rect{box.x + 34, box.y + box.height - 54, box.width - 68, 40};
}

template <typename T>
bool writeValue(FsFile& file, const T& value) {
  return file.write(reinterpret_cast<const uint8_t*>(&value), sizeof(T)) == sizeof(T);
}

template <typename T>
bool readValue(FsFile& file, T& value) {
  return file.read(reinterpret_cast<uint8_t*>(&value), sizeof(T)) == static_cast<int>(sizeof(T));
}

int lerpInt(int a, int b, uint16_t progress) {
  return a + static_cast<int>((static_cast<int32_t>(b - a) * progress) / 1000);
}

void drawCenteredText(GfxRenderer& renderer, int fontId, const Rect& rect, const char* text) {
  const int w = renderer.getTextWidth(fontId, text);
  const int h = renderer.getLineHeight(fontId);
  renderer.drawText(fontId, rect.x + std::max(0, (rect.width - w) / 2),
                    rect.y + std::max(0, (rect.height - h) / 2), text);
}

int explosionRadius(uint32_t ageUs) {
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

void drawClippedRectOutline(GfxRenderer& renderer, const Rect& clip, int x, int y, int w, int h) {
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


constexpr uint8_t EXP_ROT_COUNT = 8;
constexpr uint8_t EXP_SHAPE_COUNT = 3;
constexpr uint8_t EXP_VERTS = 8;
constexpr uint32_t EXP_ROT_STEP_US = 120000;
constexpr uint32_t EXP_REAL_SHAPE_STEP_US = 220000;
constexpr uint8_t EXP_REAL_OFFSET_COUNT = 8;
struct ExpPt { int8_t x = 0; int8_t y = 0; };
struct ExpContour {
  std::array<ExpPt, EXP_VERTS> points{};
  uint8_t count = 0;
};
std::array<std::array<std::array<ExpContour, EXPLOSION_MAX_RADIUS + 1>, EXP_ROT_COUNT>, EXP_SHAPE_COUNT>
    expCache{};
std::array<std::array<ExpPt, EXPLOSION_MAX_RADIUS + 1>, EXP_REAL_OFFSET_COUNT> expOffsetCache{};
bool expCacheReady = false;

void prepareExplosionCache(bool rebuild = false) {
  if (expCacheReady && !rebuild) return;

  // Q10 convex silhouettes. Keep the same 5/6/8 vertices and the same
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
  // Eight deliberately large orientations, 45 degrees apart.
  constexpr int16_t rotCos[EXP_ROT_COUNT] = {1024, 724, 0, -724, -1024, -724, 0, 724};
  constexpr int16_t rotSin[EXP_ROT_COUNT] = {0, 724, 1024, 724, 0, -724, -1024, -724};

  const auto divQ10 = [](int32_t value) -> int16_t {
    return static_cast<int16_t>((value >= 0 ? value + 512 : value - 512) / 1024);
  };
  const auto toPixel = [](int32_t value) -> int8_t {
    return static_cast<int8_t>((value >= 0 ? value + 512 : value - 512) / 1024);
  };

  for (uint8_t shape = 0; shape < EXP_SHAPE_COUNT; ++shape) {
    for (uint8_t rot = 0; rot < EXP_ROT_COUNT; ++rot) {
      for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {
        ExpContour& contour = expCache[shape][rot][radius];
        contour.count = vertexCount[shape];
        for (uint8_t v = 0; v < contour.count; ++v) {
          const int32_t rxQ20 = static_cast<int32_t>(baseX[shape][v]) * rotCos[rot] -
                                static_cast<int32_t>(baseY[shape][v]) * rotSin[rot];
          const int32_t ryQ20 = static_cast<int32_t>(baseX[shape][v]) * rotSin[rot] +
                                static_cast<int32_t>(baseY[shape][v]) * rotCos[rot];
          const int16_t rxQ10 = divQ10(rxQ20);
          const int16_t ryQ10 = divQ10(ryQ20);
          contour.points[v] = {toPixel(static_cast<int32_t>(radius) * rxQ10),
                               toPixel(static_cast<int32_t>(radius) * ryQ10)};
        }
      }
    }
  }
  // Smooth clockwise loop around the logical blast centre. Peak offset
  // stays in the same visible range, but adjacent states are spatially close,
  // which looks like drifting pressure rather than random jitter.
  constexpr int16_t offsetXQ10[EXP_REAL_OFFSET_COUNT] = {0, 145, 205, 145, 0, -145, -205, -145};
  constexpr int16_t offsetYQ10[EXP_REAL_OFFSET_COUNT] = {-180, -127, 0, 127, 180, 127, 0, -127};
  for (uint8_t stage = 0; stage < EXP_REAL_OFFSET_COUNT; ++stage) {
    for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {
      expOffsetCache[stage][radius] = {
          toPixel(static_cast<int32_t>(radius) * offsetXQ10[stage]),
          toPixel(static_cast<int32_t>(radius) * offsetYQ10[stage])};
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

uint8_t explosionBaseShape(uint8_t seed) {
  const uint8_t shape = static_cast<uint8_t>((seed >> 4) & 0x03u);
  return static_cast<uint8_t>(shape % EXP_SHAPE_COUNT);
}

uint8_t explosionShapeIndex(uint32_t ageUs, uint8_t seed, bool realistic) {
  const uint8_t base = explosionBaseShape(seed);
  if (!realistic) return base;

  // Seeded but visually smoother morph paths. 0/1/2 are absolute
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
}

ExpPt explosionVisualOffset(uint32_t ageUs, uint8_t seed, int radius, bool realistic) {
  if (!realistic) return ExpPt{};
  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);
  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);
  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);
  const uint8_t stage = (seed & 0x08u) != 0
                            ? static_cast<uint8_t>((start + EXP_REAL_OFFSET_COUNT - step) & 0x07u)
                            : static_cast<uint8_t>((start + step) & 0x07u);
  return expOffsetCache[stage][cr];
}

void drawClippedLine1px(GfxRenderer& renderer, const Rect& clip, int x0, int y0, int x1, int y1) {
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

void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius, uint8_t rot, uint8_t shape) {
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
  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);
  const ExpContour& contour = expCache[shape % EXP_SHAPE_COUNT][rot % EXP_ROT_COUNT][cr];
  for (uint8_t i = 0; i < contour.count; ++i) {
    const ExpPt& a = contour.points[i];
    const ExpPt& b = contour.points[(i + 1) % contour.count];
    drawClippedLine1px(renderer, clip, x + a.x, y + a.y, x + b.x, y + b.y);
  }

  // White interior by design: outer 1-bit contour only.
}

void drawMissileTrailFade64(GfxRenderer& renderer, int startX, int startY, int x, int y) {
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

void runUc8279WindowBenchmark() {
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE-WINDOW2", WINDOW_BENCH_PATH, file)) return;

  const char header[] = "window_w,window_h,window_pixels,screen_pct_x100,pass,refresh_us\n";
  file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);

  uint8_t* const fb = display.getFrameBuffer();
  const uint16_t panelW = display.getDisplayWidth();
  const uint16_t panelH = display.getDisplayHeight();
  const uint16_t wb = display.getDisplayWidthBytes();
  if (!fb || panelW < 32 || panelH < 32 || wb == 0) {
    file.close();
    return;
  }

  constexpr uint16_t markerW = 16;
  constexpr uint16_t markerH = 16;
  const uint16_t markerX = static_cast<uint16_t>(((panelW - markerW) / 2) & ~0x07u);
  const uint16_t markerY = static_cast<uint16_t>((panelH - markerH) / 2);
  const auto toggleMarker = [&]() {
    for (uint16_t row = 0; row < markerH; ++row) {
      uint8_t* p = fb + static_cast<uint32_t>(markerY + row) * wb + markerX / 8;
      for (uint16_t b = 0; b < markerW / 8; ++b) p[b] ^= 0xFF;
    }
  };

  struct WindowSize { uint16_t w; uint16_t h; };
  const WindowSize tests[] = {
      {32, 32}, {64, 64}, {128, 64}, {128, 128}, {256, 128}, {400, 240}, {800, 480},
  };
  const uint32_t screenPixels = static_cast<uint32_t>(panelW) * panelH;

  for (const auto& test : tests) {
    if (test.w > panelW || test.h > panelH) continue;
    const uint16_t x = static_cast<uint16_t>(((panelW - test.w) / 2) & ~0x07u);
    const uint16_t y = static_cast<uint16_t>((panelH - test.h) / 2);
    for (uint8_t pass = 1; pass <= 2; ++pass) {
      toggleMarker();
      const uint32_t t0 = micros();
      display.displayWindow(x, y, test.w, test.h, false);
      const uint32_t elapsed = micros() - t0;
      const uint32_t pixels = static_cast<uint32_t>(test.w) * test.h;
      const uint32_t pctX100 = screenPixels ? static_cast<uint32_t>((static_cast<uint64_t>(pixels) * 10000ULL) / screenPixels) : 0;
      char line[192];
      const int n = std::snprintf(line, sizeof(line), "%u,%u,%lu,%lu,%u,%lu\n",
                                  static_cast<unsigned>(test.w), static_cast<unsigned>(test.h),
                                  static_cast<unsigned long>(pixels), static_cast<unsigned long>(pctX100),
                                  static_cast<unsigned>(pass), static_cast<unsigned long>(elapsed));
      if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
    }
  }
  file.close();
}


constexpr int MISSILE_HUD_COLUMNS = 2;
constexpr int64_t MISSILE_SCORE_CLEAN_INTERVAL_US = 2000000;

Rect missileHudCell(const Rect& status, int column) {
  const int left = status.x + (status.width * column) / MISSILE_HUD_COLUMNS;
  const int right = status.x + (status.width * (column + 1)) / MISSILE_HUD_COLUMNS;
  return Rect{left, status.y, std::max(1, right - left), status.height};
}

Rect missileHudValueRect(const Rect& status, int column) {
  const Rect cell = missileHudCell(status, column);
  // Two wide cells: keep the static label well away from the numeric area.
  const int valueX = cell.x + (cell.width * 40) / 100;
  const int right = cell.x + cell.width - 3;
  return Rect{valueX, cell.y + 2, std::max(1, right - valueX), std::max(1, cell.height - 4)};
}

void drawMissileHudLabel(GfxRenderer& renderer, const Rect& status, int column, const char* label) {
  const Rect cell = missileHudCell(status, column);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int y = cell.y + std::max(0, (cell.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, cell.x + 5, y, label);
}

void drawMissileHudValue(GfxRenderer& renderer, const Rect& status, int column, const char* value) {
  const Rect valueRect = missileHudValueRect(status, column);
  renderer.fillRect(valueRect.x, valueRect.y, valueRect.width, valueRect.height, false);
  const int w = renderer.getTextWidth(UI_10_FONT_ID, value);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int x = std::max(valueRect.x, valueRect.x + valueRect.width - w);
  const int y = valueRect.y + std::max(0, (valueRect.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, value);
}

int missileHeaderMetaReserve(GfxRenderer& renderer, uint16_t wave, int cities) {
  char meta[40];
  std::snprintf(meta, sizeof(meta), "Vague %u - Villes %d", static_cast<unsigned>(wave), cities);
  // UI_10 is part of the normal UI font set and is already used successfully
  // by the score strip. Reserve the exact metadata width plus breathing room.
  // Counters use the same title font slot as "Missile Command" so their
  // vertical metrics are identical. Reserve that exact regular-font width.
  return renderer.getTextWidth(UI_12_FONT_ID, meta) + 24;
}

void drawMissileHeaderMeta(GfxRenderer& renderer, const Rect& header, uint16_t wave, int cities) {
  char meta[40];
  std::snprintf(meta, sizeof(meta), "Vague %u - Villes %d", static_cast<unsigned>(wave), cities);
  // Draw the metadata through the *same FreeInkUI title font slot* and the
  // exact same vertical text box used by TouchHeaderBackButton for
  // "Missile Command". GfxRendererTarget vertically centers both runs from
  // the same line-height, so their baseline is identical by construction.
  auto metaTarget = makeUiTarget(renderer);
  fui::TextStyle metaStyle = uiThemeTokens(metaTarget).titleText;
  metaStyle.bold = false;
  metaStyle.align = fui::TextAlign::Right;
  metaStyle.maxLines = 1;

  const auto titleLayout = TouchHeaderBackButton::layout(header);
  const int w = renderer.getTextWidth(UI_12_FONT_ID, meta);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x, right - w);
  metaTarget.text(fui::Rect{static_cast<int16_t>(x), static_cast<int16_t>(titleLayout.iconRect.y),
                            static_cast<int16_t>(std::max(1, right - x)),
                            static_cast<int16_t>(titleLayout.iconRect.height)},
                  meta, metaStyle);
}

}  // namespace

MissileCommandActivity::MissileCommandActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Missile Command", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

void MissileCommandActivity::onEnter() {
  Activity::onEnter();
  prepareExplosionCache();
  viewMode_ = ViewMode::Menu;
  menuScrubPending_ = true;
  selectedIndex_ = difficulty_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  uiReady_ = false;
  sceneNeedsFullRedraw_ = true;
  menuScrubPending_ = false;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;
  loadHighScore();
  hasSavedGame_ = loadSavedGame();
  syncCurrentHighScore();
  selectedIndex_ = difficulty_;
  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &MissileCommandActivity::onRowEvent, this);
  app_.setScreen(&MissileCommandActivity::menuScreen, this);
  requestUpdate();
}

void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::WaveComplete && interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    interWavePrepPending_ = false;
  }
  if ((viewMode_ == ViewMode::Playing || viewMode_ == ViewMode::WaveComplete) && aliveCityCount() > 0)
    saveGame();
  if (viewMode_ != ViewMode::Menu) saveHighScore();
  releaseWindowShadow();
  Activity::onExit();
}

void MissileCommandActivity::loop() {
  switch (viewMode_) {
    case ViewMode::Menu:
      loopMenu();
      break;
    case ViewMode::Playing:
      loopPlaying();
      break;
    case ViewMode::WaveComplete:
      loopWaveComplete();
      break;
    case ViewMode::GameOver:
      loopGameOver();
      break;
  }
}

void MissileCommandActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    onGoHome();
    return;
  }

  int resetTapX = 0;
  int resetTapY = 0;
  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(resetTapX, resetTapY) &&
      pointInRect(missileScoreResetButtonRect(renderer, mappedInput), resetTapX, resetTapY)) {
    startActivityForResult(
        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Réinitialiser les scores ?", ""),
        [this](const ActivityResult& result) {
          if (!result.isCancelled) {
            highScores_.fill(0);
            highScore_ = 0;
            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);
          }
          requestUpdate();
        });
    return;
  }

  if (uiReady_) {
    const fui::InputSnapshot snap = touchSnapshotFrom(mappedInput);
    if (snap.touchPressed || snap.touchReleased) {
      const auto event = app_.route(snap);
      if (app_.invalidated()) requestUpdate();
      if (event) return;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    activateRow(selectedIndex_);
    return;
  }

  const auto swipe = mappedInput.wasSwipe();
  if (swipe == MappedInputManager::SwipeDir::Up || swipe == MappedInputManager::SwipeDir::Down) {
    const int delta = swipe == MappedInputManager::SwipeDir::Up ? visibleRows_ : -visibleRows_;
    const int next = scrollListBy(topIndex_, delta, visibleRows_, kMenuRowCount);
    if (next != topIndex_) {
      topIndex_ = next;
      requestUpdate();
    }
    return;
  }

  const auto moveSelection = [this](int index) {
    selectedIndex_ = index;
    topIndex_ = followListSelection(selectedIndex_, topIndex_, visibleRows_, kMenuRowCount);
    requestUpdate();
  };
  buttonNavigator_.onNextRelease(
      [this, &moveSelection] { moveSelection(ButtonNavigator::nextIndex(selectedIndex_, kMenuRowCount)); });
  buttonNavigator_.onPreviousRelease(
      [this, &moveSelection] { moveSelection(ButtonNavigator::previousIndex(selectedIndex_, kMenuRowCount)); });
  buttonNavigator_.onNextContinuous([this, &moveSelection] {
    moveSelection(ButtonNavigator::nextPageIndex(selectedIndex_, kMenuRowCount, visibleRows_));
  });
  buttonNavigator_.onPreviousContinuous([this, &moveSelection] {
    moveSelection(ButtonNavigator::previousPageIndex(selectedIndex_, kMenuRowCount, visibleRows_));
  });
}

void MissileCommandActivity::loopPlaying() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);

  // Capture input continuously, but consume it only at the next synchronized
  // game/display frame. Input, simulation and visible e-ink state never run ahead.
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    pendingBack_ = true;
  }

  int tx = 0;
  int ty = 0;
  if (!pendingBack_ && mappedInput.wasScreenTapped(tx, ty) && pointInRect(geometry.field, tx, ty) &&
      ty < geometry.groundY) {
    pendingTapX_ = static_cast<int16_t>(tx);
    pendingTapY_ = static_cast<int16_t>(ty);
    pendingTap_ = true;
  }

  // A new world step is forbidden until the frame representing the previous
  // step has finished on the panel. This is the core 1:1 game/display lock.
  if (cycleRenderPending_.load()) return;

  const int64_t now = esp_timer_get_time();
  if (lastCycleUs_ == 0) {
    lastCycleUs_ = now;
    return;
  }
  const int64_t cycleElapsedUs = now - lastCycleUs_;
  if (cycleElapsedUs < GAME_FRAME_US) return;
  lastCycleUs_ = now;
  // Keep the original no-catch-up rule: a stall may never advance more than
  // one legacy frame of gameplay. Normal Stage-B frames are shorter and get
  // a proportionally smaller movement increment instead.
  const uint32_t gameplayElapsedUs = static_cast<uint32_t>(
      std::min<int64_t>(cycleElapsedUs, LEGACY_GAMEPLAY_FRAME_US));

  if (pendingBack_) {
    pendingBack_ = false;
    pendingTap_ = false;
    returnToMenu();
    return;
  }

  if (pendingTap_) {
    launchPlayerMissile(pendingTapX_, pendingTapY_);
    pendingTap_ = false;
  }

  tickGame(now, gameplayElapsedUs);
  if (viewMode_ != ViewMode::Playing) return;

  cycleRenderPending_.store(true);
  requestUpdate();
}

void MissileCommandActivity::loopWaveComplete() {
  // Use the human pause between waves for all safe next-wave preparation.
  // Staying in WaveComplete means none of this can advance simulation.
  if (interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    saveGame();
    interWavePrepPending_ = false;
  }

  const Rect header = headerRect(renderer, mappedInput);
  const bool headerBack = mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header);
  int tx = 0;
  int ty = 0;
  const bool touchNext = mappedInput.hasTouchHardware() && !headerBack && mappedInput.wasScreenTapped(tx, ty) &&
                         pointInRect(waveCompleteActionRect(renderer, mappedInput), tx, ty);

  if (headerBack || mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  if (touchNext || mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    beginPreparedWave();
  }
}

void MissileCommandActivity::loopGameOver() {
  const Rect header = headerRect(renderer, mappedInput);
  const bool headerBack = mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header);
  int tx = 0;
  int ty = 0;
  const bool touchReturn = mappedInput.hasTouchHardware() && !headerBack && mappedInput.wasScreenTapped(tx, ty) &&
                           pointInRect(gameOverActionRect(renderer), tx, ty);
  if (headerBack || touchReturn || mappedInput.wasPressed(MappedInputManager::Button::Back) ||
      mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
  }
}

void MissileCommandActivity::activateRow(int row) {
  if (row >= 0 && row < kDifficultyCount) {
    difficulty_ = row;
    selectedIndex_ = row;
    syncCurrentHighScore();
    requestUpdate();
    return;
  }
  if (row == 3) {
    baseMode_ = !baseMode_;
    syncCurrentHighScore();
    requestUpdate();
    return;
  }
  if (row == 4) {
    realisticExplosions_ = !realisticExplosions_;
    requestUpdate();
    return;
  }
  if (row == 5) {
    if (hasSavedGame_ && loadSavedGame()) continueGame();
    return;
  }
  if (row != 6) return;

  if (!hasSavedGame_) {
    newGame();
    return;
  }

  startActivityForResult(
      std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Effacer la partie en cours :", ""),
      [this](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        newGame();
      });
}

void MissileCommandActivity::newGame() {
  syncCurrentHighScore();
  clearSavedGame();
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  citiesAlive_.fill(1);
  batteriesAlive_.fill(1);
  ammo_.fill(10);
  score_ = 0;
  wave_ = 1;
  waveScrubPending_ = false;
  startWave();
  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastCycleUs_ = esp_timer_get_time();
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);
  requestUpdate();
}

void MissileCommandActivity::continueGame() {
  prepareWaveRuntimeConstants();
  waveShotsFired_ = 0;
  waveEnemyKills_ = 0;
  syncCurrentHighScore();
  waveScrubPending_ = false;
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastCycleUs_ = esp_timer_get_time();
  nextSpawnUs_ = lastCycleUs_ + 500000;
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);
  requestUpdate();
}

void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();
  saveHighScore();
  viewMode_ = ViewMode::Menu;
  menuScrubPending_ = true;
  selectedIndex_ = difficulty_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;
  requestUpdate();
}

void MissileCommandActivity::prepareWaveRuntimeConstants() {
  waveTargetCount_ = static_cast<uint16_t>(5 + difficulty_ * 2 + std::min<int>(wave_, 7));
  waveEnemySpeed_ = static_cast<uint16_t>(12 + difficulty_ * 3 + std::min<int>(wave_ / 2, 4) * 3);

  // Seven symmetric hard-mode bands: -25% .. +25%.
  constexpr uint8_t hardSpeedPct[7] = {75, 83, 92, 100, 108, 117, 125};
  for (size_t i = 0; i < waveHardEnemySpeeds_.size(); ++i) {
    waveHardEnemySpeeds_[i] = static_cast<uint16_t>(
        std::max<uint32_t>(1u, (static_cast<uint32_t>(waveEnemySpeed_) * hardSpeedPct[i] + 50u) / 100u));
  }

  // Preselect the ENTIRE next-wave speed sequence now. In the normal flow this
  // runs from loopWaveComplete() while the popup is displayed. Spawns therefore
  // do zero RNG and zero speed multiplications during active gameplay.
  waveEnemySpawnSpeeds_.fill(waveEnemySpeed_);
  if (difficulty_ == 2) {
    const size_t count = std::min<size_t>(waveTargetCount_, waveEnemySpawnSpeeds_.size());
    for (size_t i = 0; i < count; ++i) {
      const uint32_t pick = esp_random() % waveHardEnemySpeeds_.size();
      waveEnemySpawnSpeeds_[i] = waveHardEnemySpeeds_[pick];
    }
  }

  waveSpawnIntervalUs_ = static_cast<uint32_t>(
      std::max(420, 1150 - difficulty_ * 180 - static_cast<int>(wave_) * 45)) * 1000u;
  waveAmmoCapacity_ = static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5));
}

void MissileCommandActivity::startWave() {
  prepareWaveRuntimeConstants();
  waveShotsFired_ = 0;
  waveEnemyKills_ = 0;
  prepareExplosionCache();
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  const uint8_t waveAmmo = waveAmmoCapacity_;
  for (int i = 0; i < kBatteryCount; ++i)
    ammo_[static_cast<size_t>(i)] = (!baseMode_ || batteriesAlive_[static_cast<size_t>(i)]) ? waveAmmo : 0;
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  nextSpawnUs_ = esp_timer_get_time() + 500000;
  sceneNeedsFullRedraw_ = true;
}

void MissileCommandActivity::beginPreparedWave() {
  if (interWavePrepPending_) {
    ++wave_;
    waveScrubPending_ = true;
    startWave();
    saveGame();
    interWavePrepPending_ = false;
  }

  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastCycleUs_ = esp_timer_get_time();
  nextSpawnUs_ = lastCycleUs_ + 500000;
  pendingTap_ = false;
  pendingBack_ = false;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(true);

  // The intermission was a different full-screen image. Force the already
  // accepted clean gameplay-entry HALF baseline, then return to Cluster1.
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  requestUpdate();
}

void MissileCommandActivity::tickGame(int64_t nowUs, uint32_t gameplayElapsedUs) {
  const auto advanceMissile = [gameplayElapsedUs](Missile& missile) {
    const uint64_t scaled = static_cast<uint64_t>(missile.speed) * gameplayElapsedUs +
                            missile.progressRemainderUs;
    const uint32_t delta = static_cast<uint32_t>(scaled / LEGACY_GAMEPLAY_FRAME_US);
    missile.progressRemainderUs = static_cast<uint32_t>(scaled % LEGACY_GAMEPLAY_FRAME_US);
    missile.progress = static_cast<uint16_t>(std::min<uint32_t>(1000, missile.progress + delta));
  };
  if (aliveCityCount() <= 0) {
    finishGame();
    return;
  }

  const int targetCount = waveTargetCount_;
  if (enemiesSpawned_ < targetCount && nowUs >= nextSpawnUs_ && activeEnemyCount() < kMaxEnemyMissiles) {
    spawnEnemy(nowUs);
  }

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  for (auto& missile : enemies_) {
    if (!missile.active) continue;
    advanceMissile(missile);
    if (missile.progress < 1000) continue;
    missile.active = false;
    ++enemiesResolved_;

    if (baseMode_) {
      int nearest = -1;
      int nearestDist = 1 << 30;
      for (int i = 0; i < kBatteryCount; ++i) {
        if (!batteriesAlive_[static_cast<size_t>(i)]) continue;
        const int bx = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
        const int d = std::abs(bx - missile.targetX);
        if (d < nearestDist) { nearestDist = d; nearest = i; }
      }
      if (nearest >= 0 && nearestDist < std::max(24, geometry.field.width / 8)) {
        batteriesAlive_[static_cast<size_t>(nearest)] = 0;
        ammo_[static_cast<size_t>(nearest)] = 0;
      }
    } else {
      int nearest = 0;
      int nearestDist = 1 << 30;
      for (int i = 0; i < kCityCount; ++i) {
        if (!citiesAlive_[static_cast<size_t>(i)]) continue;
        const int cityX = geometry.field.x + (geometry.field.width * (i + 1)) / (kCityCount + 1);
        const int d = std::abs(cityX - missile.targetX);
        if (d < nearestDist) { nearestDist = d; nearest = i; }
      }
      if (nearestDist < std::max(24, geometry.field.width / 10)) citiesAlive_[static_cast<size_t>(nearest)] = 0;
    }
    createExplosion(missile.targetX, missile.targetY);
  }

  for (auto& missile : players_) {
    if (!missile.active) continue;
    advanceMissile(missile);
    if (missile.progress >= 1000) {
      missile.active = false;
      createExplosion(missile.targetX, missile.targetY);
    }
  }

  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    const uint64_t nextAge = static_cast<uint64_t>(explosion.phaseElapsedUs) + gameplayElapsedUs;
    explosion.phaseElapsedUs = static_cast<uint32_t>(std::min<uint64_t>(nextAge, EXPLOSION_TOTAL_US));
    if (explosion.phaseElapsedUs >= EXPLOSION_TOTAL_US) explosion.active = false;
  }

  resolveCollisions();
  finishWaveIfNeeded();
}

void MissileCommandActivity::spawnEnemy(int64_t nowUs) {
  Missile* slot = nullptr;
  for (auto& missile : enemies_) {
    if (!missile.active) {
      slot = &missile;
      break;
    }
  }
  if (!slot) return;

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int margin = 8;
  slot->startX = static_cast<int16_t>(geometry.field.x + margin +
      static_cast<int>(esp_random() % static_cast<uint32_t>(std::max(1, geometry.field.width - margin * 2))));
  slot->startY = static_cast<int16_t>(geometry.field.y + 2);

  if (baseMode_) {
    std::array<int, kBatteryCount> aliveBases{};
    int aliveCount = 0;
    for (int i = 0; i < kBatteryCount; ++i) {
      if (batteriesAlive_[static_cast<size_t>(i)]) aliveBases[static_cast<size_t>(aliveCount++)] = i;
    }
    if (aliveCount <= 0) return;
    const int base = aliveBases[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
    slot->targetX = static_cast<int16_t>(geometry.field.x + geometry.field.width * (base * 2 + 1) / (kBatteryCount * 2));
    slot->targetY = static_cast<int16_t>(geometry.groundY + 18);
  } else {
    std::array<int, kCityCount> alive{};
    int aliveCount = 0;
    for (int i = 0; i < kCityCount; ++i) {
      if (citiesAlive_[static_cast<size_t>(i)]) alive[static_cast<size_t>(aliveCount++)] = i;
    }
    if (aliveCount <= 0) return;
    const int city = alive[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
    slot->targetX = static_cast<int16_t>(geometry.field.x + (geometry.field.width * (city + 1)) / (kCityCount + 1));
    slot->targetY = static_cast<int16_t>(geometry.groundY);
  }
  slot->progress = 0;
  slot->progressRemainderUs = 0;
  // Speeds are legacy per-frame increments; tickGame() now time-normalizes
  // them so Stage-B display acceleration does not accelerate gameplay.
  // Scale from the previous 33 ms
  // cadence so real-world descent time stays approximately unchanged.
  if (difficulty_ == 2 && enemiesSpawned_ < waveEnemySpawnSpeeds_.size()) {
    // enemiesSpawned_ is incremented below, so it is the exact preselected
    // sequence index for this spawn. No RNG or multiplication in gameplay.
    slot->speed = waveEnemySpawnSpeeds_[static_cast<size_t>(enemiesSpawned_)];
  } else {
    slot->speed = waveEnemySpeed_;
  }
  slot->active = true;
  ++enemiesSpawned_;

  nextSpawnUs_ = nowUs + static_cast<int64_t>(waveSpawnIntervalUs_);
}

void MissileCommandActivity::launchPlayerMissile(int x, int y) {
  Missile* slot = nullptr;
  for (auto& missile : players_) {
    if (!missile.active) {
      slot = &missile;
      break;
    }
  }
  if (!slot) return;

  const int battery = nearestBatteryForX(x);
  if (battery < 0 || battery >= kBatteryCount || ammo_[static_cast<size_t>(battery)] == 0) return;

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int batteryX = geometry.field.x + geometry.field.width * (battery * 2 + 1) / (kBatteryCount * 2);
  --ammo_[static_cast<size_t>(battery)];
  ++waveShotsFired_;
  slot->startX = static_cast<int16_t>(batteryX);
  slot->startY = static_cast<int16_t>(geometry.groundY + 18);
  slot->targetX = static_cast<int16_t>(std::clamp(x, geometry.field.x, geometry.field.x + geometry.field.width - 1));
  slot->targetY = static_cast<int16_t>(std::clamp(y, geometry.field.y, geometry.groundY - 4));
  slot->progress = 0;
  slot->progressRemainderUs = 0;
  slot->speed = 140;
  slot->active = true;
}

void MissileCommandActivity::createExplosion(int x, int y) {
  for (auto& explosion : explosions_) {
    if (explosion.active) continue;
    explosion.x = static_cast<int16_t>(x);
    explosion.y = static_cast<int16_t>(y);
    const uint32_t explosionRnd = esp_random();
    const uint8_t shape = static_cast<uint8_t>((explosionRnd >> 8) % EXP_SHAPE_COUNT);
    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3) |
                                           (shape << 4) | (((explosionRnd >> 6) & 0x01u) << 6) |
                                           (((explosionRnd >> 7) & 0x01u) << 7));
    explosion.phaseElapsedUs = 0;
    explosion.active = true;
    return;
  }
}

void MissileCommandActivity::resolveCollisions() {
  for (auto& enemy : enemies_) {
    if (!enemy.active) continue;
    const int ex = lerpInt(enemy.startX, enemy.targetX, enemy.progress);
    const int ey = lerpInt(enemy.startY, enemy.targetY, enemy.progress);
    for (const auto& explosion : explosions_) {
      if (!explosion.active) continue;
      const int radius = explosionRadius(explosion.phaseElapsedUs);
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
      enemy.active = false;
      ++enemiesResolved_;
      ++waveEnemyKills_;
      score_ += static_cast<uint32_t>(25 + wave_ * 2);
      createExplosion(ex, ey);
      break;
    }
  }
}

void MissileCommandActivity::finishWaveIfNeeded() {
  const int targetCount = waveTargetCount_;
  if (enemiesSpawned_ < targetCount || activeEnemyCount() > 0 || activePlayerCount() > 0) return;

  completedWave_ = wave_;
  completedWaveShotsFired_ = waveShotsFired_;
  completedWaveEnemyKills_ = waveEnemyKills_;
  completedWaveEfficiencyPct_ = completedWaveShotsFired_ == 0 ? 0 :
      static_cast<uint16_t>((static_cast<uint32_t>(completedWaveEnemyKills_) * 100u +
                             completedWaveShotsFired_ / 2u) / completedWaveShotsFired_);
  waveEndAmmoRemaining_ = 0;
  for (uint8_t ammo : ammo_) waveEndAmmoRemaining_ = static_cast<uint16_t>(waveEndAmmoRemaining_ + ammo);
  waveEndObjectives_ = static_cast<uint8_t>(std::max(0, aliveCityCount()));

  if (baseMode_) {
    for (int i = 0; i < kBatteryCount; ++i) {
      if (batteriesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  } else {
    for (int i = 0; i < kCityCount; ++i) {
      if (citiesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  }
  for (uint8_t ammo : ammo_) score_ += static_cast<uint32_t>(ammo) * 5;

  if (score_ > highScore_) highScore_ = score_;
  saveHighScore();

  // Freeze gameplay on a clean summary screen. The next normal loop performs
  // next-wave preparation while the user is reading it.
  viewMode_ = ViewMode::WaveComplete;
  interWavePrepPending_ = true;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  pendingTap_ = false;
  pendingBack_ = false;
  requestUpdate();
}

void MissileCommandActivity::finishGame() {
  if (score_ > highScore_) {
    highScore_ = score_;
    saveHighScore();
  }
  clearSavedGame();
  viewMode_ = ViewMode::GameOver;
  sceneNeedsFullRedraw_ = true;
  cycleRenderPending_.store(false);
  requestUpdate();
}

int MissileCommandActivity::aliveCityCount() const {
  int count = 0;
  if (baseMode_) {
    for (uint8_t alive : batteriesAlive_) count += alive ? 1 : 0;
  } else {
    for (uint8_t alive : citiesAlive_) count += alive ? 1 : 0;
  }
  return count;
}

int MissileCommandActivity::activeEnemyCount() const {
  int count = 0;
  for (const auto& missile : enemies_) count += missile.active ? 1 : 0;
  return count;
}

int MissileCommandActivity::activePlayerCount() const {
  int count = 0;
  for (const auto& missile : players_) count += missile.active ? 1 : 0;
  return count;
}

int MissileCommandActivity::nearestBatteryForX(int x) const {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  int best = 0;
  int bestDistance = 1 << 30;
  for (int i = 0; i < kBatteryCount; ++i) {
    const int bx = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const int d = std::abs(bx - x);
    if (d < bestDistance && ammo_[static_cast<size_t>(i)] > 0 &&
        (!baseMode_ || batteriesAlive_[static_cast<size_t>(i)])) {
      bestDistance = d;
      best = i;
    }
  }
  return bestDistance == (1 << 30) ? -1 : best;
}

void MissileCommandActivity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<MissileCommandActivity*>(user);
  if (event.value < 0 || event.value >= kMenuRowCount) return;
  self->selectedIndex_ = event.value;
  self->app_.clearTapFlash();
  self->activateRow(event.value);
}

void MissileCommandActivity::menuScreen(UiApp::ScreenType& screen, void* user) {
  static_cast<MissileCommandActivity*>(user)->buildMenuScreen(screen);
}

void MissileCommandActivity::buildMenuScreen(UiApp::ScreenType& screen) {
  const Rect bounds = menuRect(renderer, mappedInput);
  screen.setContentMargin(fui::Insets{static_cast<int16_t>(bounds.y), 0,
      static_cast<int16_t>(renderer.getScreenHeight() - bounds.y - bounds.height), 0});

  std::array<fui::ListItem, kMenuRowCount> items{};
  for (int i = 0; i < kDifficultyCount; ++i) {
    items[static_cast<size_t>(i)].label = DIFFICULTY_LABELS[i];
    items[static_cast<size_t>(i)].value = nullptr;
    items[static_cast<size_t>(i)].actionValue = static_cast<int16_t>(i);
  }

  items[3].label = "Mode bases";
  items[3].value = nullptr;
  items[3].actionValue = 3;

  items[4].label = "Explosions réalistes";
  items[4].value = nullptr;
  items[4].actionValue = 4;

  items[5].label = "";
  if (hasSavedGame_) {
    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",
                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));
    items[5].value = nullptr;
  } else {
    items[5].value = nullptr;
  }
  items[5].actionValue = 5;

  items[6].label = "";
  items[6].value = nullptr;
  items[6].actionValue = 6;

  fui::ListProps props;
  props.items = items.data();
  props.count = static_cast<uint16_t>(items.size());
  props.selectedIndex = static_cast<int16_t>(selectedIndex_);
  props.action = ACTION_ROW;
  props.inputMask = fui::InputTouch;
  props.valueInset = 8;
  props.labelText = screen.theme().bodyText;
  const auto rows = configureUiList(props, screen.theme(), screen.body());
  visibleRows_ = rows > 0 ? rows : 1;
  topIndex_ = initialViewportPending_ ? followListSelection(selectedIndex_, 0, visibleRows_, kMenuRowCount)
                                      : scrollListBy(topIndex_, 0, visibleRows_, kMenuRowCount);
  initialViewportPending_ = false;
  props.topIndex = static_cast<uint16_t>(topIndex_);
  screen.list(props);
}

void MissileCommandActivity::render(RenderLock&&) {
  switch (viewMode_) {
    case ViewMode::Menu:
      renderMenu();
      break;
    case ViewMode::Playing:
      renderPlaying();
      break;
    case ViewMode::WaveComplete:
      renderWaveComplete();
      break;
    case ViewMode::GameOver:
      renderGameOver();
      break;
  }
}

void MissileCommandActivity::renderMenu() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, header, "Missile Command", nullptr, false);
  }

  uiReady_ = false;
  app_.render();
  uiReady_ = true;

  // Match Minesweeper/2048: real e-ink checkboxes for options, action rows
  // outlined as buttons, and a dithered disabled Continue action.
  const Rect listBounds = menuRect(renderer, mappedInput);
  const int drawnRows = std::max(1, visibleRows_);
  const int boxSize = 22;
  const int innerSize = 10;
  const int boxX = renderer.getScreenWidth() - UITheme::getInstance().getMetrics().contentSidePadding - boxSize - 10;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if ((itemIndex < 0 || itemIndex >= kDifficultyCount) && itemIndex != 3 && itemIndex != 4) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    const bool checked = (itemIndex < kDifficultyCount && itemIndex == difficulty_) ||
                         (itemIndex == 3 && baseMode_) ||
                         (itemIndex == 4 && realisticExplosions_);
    if (checked) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
  }

  const auto& metrics = UITheme::getInstance().getMetrics();
  constexpr int actionInsetY = 4;
  const int actionX = metrics.contentSidePadding;
  const int actionWidth = renderer.getScreenWidth() - 2 * metrics.contentSidePadding;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex != 5 && itemIndex != 6) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int actionY = rowTop + actionInsetY;
    const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);
    renderer.drawRoundedRect(actionX, actionY, actionWidth, actionHeight, 1, 6, true);
    if (itemIndex == 5 && !hasSavedGame_) {
      for (int y = actionY; y < actionY + actionHeight; y += 2)
        renderer.fillRect(actionX, y, actionWidth, 1, false);
    }

    const char* actionLabel = itemIndex == 5 ? "Continuer" : "Nouvelle partie";
    const char* actionValue = itemIndex == 5
                                  ? (hasSavedGame_ ? continueValue_.data() : "Aucune partie")
                                  : DIFFICULTY_LABELS[difficulty_];
    const int textH = renderer.getLineHeight(UI_10_FONT_ID);
    const int textY = actionY + std::max(0, (actionHeight - textH) / 2);
    renderer.drawText(UI_10_FONT_ID, actionX + 10, textY, actionLabel);
    if (actionValue && actionValue[0] != '\0') {
      const int valueW = renderer.getTextWidth(UI_10_FONT_ID, actionValue);
      renderer.drawText(UI_10_FONT_ID, actionX + actionWidth - 10 - valueW, textY, actionValue);
    }
  }

  // Minesweeper-style score panel: rows are difficulty, columns are game mode.
  const Rect scorePanel = missileScoreTableRect(renderer, mappedInput);
  renderer.fillRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, false);
  renderer.drawRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, 1, true);

  constexpr int titleH = 28;
  constexpr int columnHeaderH = 24;
  const int dataTop = scorePanel.y + titleH + columnHeaderH;
  const int labelSplitX = scorePanel.x + (scorePanel.width * 30) / 100;
  const int modeSplitX = labelSplitX + (scorePanel.x + scorePanel.width - labelSplitX) / 2;
  renderer.drawLine(scorePanel.x, scorePanel.y + titleH, scorePanel.x + scorePanel.width, scorePanel.y + titleH, 1, true);
  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);
  renderer.drawLine(labelSplitX, scorePanel.y + titleH, labelSplitX, scorePanel.y + scorePanel.height, 1, true);
  renderer.drawLine(modeSplitX, scorePanel.y + titleH, modeSplitX, scorePanel.y + scorePanel.height, 1, true);

  drawCenteredText(renderer, UI_12_FONT_ID, Rect{scorePanel.x, scorePanel.y, scorePanel.width, titleH},
                   "Meilleurs scores");
  drawCenteredText(renderer, UI_10_FONT_ID,
                   Rect{scorePanel.x, scorePanel.y + titleH, labelSplitX - scorePanel.x, columnHeaderH}, "Niveau");
  drawCenteredText(renderer, UI_10_FONT_ID,
                   Rect{labelSplitX, scorePanel.y + titleH, modeSplitX - labelSplitX, columnHeaderH}, "Villes");
  drawCenteredText(renderer, UI_10_FONT_ID,
                   Rect{modeSplitX, scorePanel.y + titleH, scorePanel.x + scorePanel.width - modeSplitX, columnHeaderH},
                   "Bases");

  const int dataHeight = scorePanel.y + scorePanel.height - dataTop;
  for (int difficulty = 0; difficulty < kDifficultyCount; ++difficulty) {
    const int rowY = dataTop + (dataHeight * difficulty) / kDifficultyCount;
    const int nextY = dataTop + (dataHeight * (difficulty + 1)) / kDifficultyCount;
    if (difficulty > 0) renderer.drawLine(scorePanel.x, rowY, scorePanel.x + scorePanel.width, rowY, 1, true);
    drawCenteredText(renderer, UI_10_FONT_ID, Rect{scorePanel.x, rowY, labelSplitX - scorePanel.x, nextY - rowY},
                     DIFFICULTY_LABELS[difficulty]);
    char scoreValue[16];
    std::snprintf(scoreValue, sizeof(scoreValue), "%lu",
                  static_cast<unsigned long>(highScores_[static_cast<size_t>(difficulty)]));
    drawCenteredText(renderer, UI_10_FONT_ID, Rect{labelSplitX, rowY, modeSplitX - labelSplitX, nextY - rowY},
                     scoreValue);
    std::snprintf(scoreValue, sizeof(scoreValue), "%lu",
                  static_cast<unsigned long>(highScores_[static_cast<size_t>(kDifficultyCount + difficulty)]));
    drawCenteredText(renderer, UI_10_FONT_ID,
                     Rect{modeSplitX, rowY, scorePanel.x + scorePanel.width - modeSplitX, nextY - rowY}, scoreValue);
  }

  const Rect resetButton = missileScoreResetButtonRect(renderer, mappedInput);
  renderer.fillRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, false);
  renderer.drawRoundedRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, resetButton, "Reinitialiser les scores");

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT),
                                             tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  if (menuScrubPending_) {
    renderer.displayBuffer(HalDisplay::HALF_REFRESH);
    menuScrubPending_ = false;
  } else {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
  }
}

void MissileCommandActivity::drawFullPlayingScene() {
  renderer.clearScreen();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }

  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);
  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  sceneNeedsFullRedraw_ = false;
}

void MissileCommandActivity::drawPlayingFrame() {
  {
    constexpr const char* BENCH_PATH = "/missile-command-bm17-preselected-hard-speeds-bench.csv";
    constexpr uint32_t BENCH_TARGET_SAMPLES = 200;
    static int64_t benchLastFrameStartUs = 0;
    static uint32_t benchSamples = 0;
    static uint64_t benchSumCycleUs = 0;
    static uint32_t benchMinCycleUs = 0xFFFFFFFFu;
    static uint32_t benchMaxCycleUs = 0;
    static bool benchFilePrimed = false;
    static bool benchSaved = false;

    if (!benchFilePrimed) {
      FsFile file;
      if (Storage.openFileForWrite("MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF-EXP2-BASE", BENCH_PATH, file)) {
        const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
        file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
        const char started[] = "bm17-preselected-hard-speeds-started,0,0,0,0,0\n";
        file.write(reinterpret_cast<const uint8_t*>(started), sizeof(started) - 1);
        file.close();
        benchFilePrimed = true;
      }
    }

    const int64_t nowUs = esp_timer_get_time();
    if (!benchSaved && benchLastFrameStartUs != 0) {
      const int64_t raw = nowUs - benchLastFrameStartUs;
      if (raw > 0 && raw < 2000000) {
        const uint32_t cycleUs = static_cast<uint32_t>(raw);
        benchSumCycleUs += cycleUs;
        if (cycleUs < benchMinCycleUs) benchMinCycleUs = cycleUs;
        if (cycleUs > benchMaxCycleUs) benchMaxCycleUs = cycleUs;
        ++benchSamples;
        if (benchSamples >= BENCH_TARGET_SAMPLES) {
          const uint32_t avg = static_cast<uint32_t>(benchSumCycleUs / benchSamples);
          const uint32_t fpsX1000 = avg ? static_cast<uint32_t>(1000000000ULL / avg) : 0;
          FsFile file;
          if (Storage.openFileForWrite("MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF-EXP2-BASE", BENCH_PATH, file)) {
            const char header[] = "profile,samples,avg_cycle_us,min_cycle_us,max_cycle_us,fps_x1000\n";
            file.write(reinterpret_cast<const uint8_t*>(header), sizeof(header) - 1);
            char line[128];
            const int n = std::snprintf(line, sizeof(line), "bm17-preselected-hard-speeds,%lu,%lu,%lu,%lu,%lu\n",
                                        static_cast<unsigned long>(benchSamples),
                                        static_cast<unsigned long>(avg),
                                        static_cast<unsigned long>(benchMinCycleUs),
                                        static_cast<unsigned long>(benchMaxCycleUs),
                                        static_cast<unsigned long>(fpsX1000));
            if (n > 0) file.write(reinterpret_cast<const uint8_t*>(line), static_cast<size_t>(n));
            file.close();
            benchSaved = true;
          }
        }
      } else if (raw >= 2000000) {
        benchSamples = 0;
        benchSumCycleUs = 0;
        benchMinCycleUs = 0xFFFFFFFFu;
        benchMaxCycleUs = 0;
      }
    }
    benchLastFrameStartUs = nowUs;
  }

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);

  // Recompose the complete gameplay field from the synchronized world state.
  // Active missiles redraw their FULL trajectory from launch to current point.
  // As soon as a missile dies, reaches its target or hits the ground, it is no
  // longer active and its complete trail is therefore erased on this frame.
  renderer.fillRect(geometry.field.x + 1, geometry.field.y + 1,
                    std::max(1, geometry.field.width - 2), std::max(1, geometry.field.height - 2), false);
  renderer.drawLine(geometry.field.x, geometry.groundY,
                    geometry.field.x + geometry.field.width - 1, geometry.groundY, 1, true);

  if (!baseMode_) {
    for (int i = 0; i < kCityCount; ++i) {
      if (!citiesAlive_[static_cast<size_t>(i)]) continue;
      const int x = geometry.field.x + geometry.field.width * (i + 1) / (kCityCount + 1);
      renderer.drawRect(x - 10, geometry.groundY - 11, 20, 11, 1, true);
      renderer.drawLine(x - 8, geometry.groundY - 11, x, geometry.groundY - 20, 1, true);
      renderer.drawLine(x, geometry.groundY - 20, x + 8, geometry.groundY - 11, 1, true);
    }
  }

  for (int i = 0; i < kBatteryCount; ++i) {
    if (baseMode_ && !batteriesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);

    const int capacity = waveAmmoCapacity_;
    const int remaining = std::clamp<int>(ammo_[static_cast<size_t>(i)], 0, capacity);
    const Rect gauge{battery.x + 4, battery.y + 6, battery.width - 8, battery.height - 12};
    renderer.drawRect(gauge.x, gauge.y, gauge.width, gauge.height, 1, true);

    const int innerW = std::max(1, gauge.width - 2);
    const int innerH = std::max(1, gauge.height - 2);
    const int fillW = capacity > 0 ? (innerW * remaining + capacity - 1) / capacity : 0;
    if (fillW > 0)
      renderer.fillRect(gauge.x + 1, gauge.y + 1, std::min(innerW, fillW), innerH, true);
  }

  for (const auto& missile : enemies_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    drawMissileTrailFade64(renderer, missile.startX, missile.startY, x, y);
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
  }

  for (const auto& missile : players_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    drawMissileTrailFade64(renderer, missile.startX, missile.startY, x, y);
    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);
  }

  const Rect explosionClip{geometry.field.x + 1, geometry.field.y + 1,
                           std::max(1, geometry.field.width - 2),
                           std::max(1, geometry.field.height - 2)};
  for (const auto& explosion : explosions_) {
    if (explosion.active)
      {
        const int explosionR = explosionRadius(explosion.phaseElapsedUs);
        const ExpPt visualOffset =
            explosionVisualOffset(explosion.phaseElapsedUs, explosion.phase, explosionR, realisticExplosions_);
        drawExplosionClipped(renderer, explosionClip, explosion.x + visualOffset.x, explosion.y + visualOffset.y, explosionR,
                             explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase),
                             explosionShapeIndex(explosion.phaseElapsedUs, explosion.phase, realisticExplosions_));
      }
  }

  // Incremental HUD: do not erase/recompose the whole strip each frame. The
  // static labels, separators, wave and city count remain untouched until the
  // next full gameplay redraw (notably a wave boundary).
  // Logical score/high-score still update immediately. The e-ink Score value
  // is intentionally frozen for the whole wave. startWave() requests a full
  // gameplay redraw, so the newly completed-wave score is painted cleanly once
  // at the next wave boundary (which already gets the accepted inter-wave HALF).
  if (score_ > highScore_) highScore_ = score_;
}


void MissileCommandActivity::releaseWindowShadow() {
  if (windowShadow_ != nullptr) {
    heap_caps_free(windowShadow_);
    windowShadow_ = nullptr;
  }
  windowShadowValid_ = false;
}

void MissileCommandActivity::refreshPlayingWindow(bool forceFullRefresh) {
  const int64_t missileDirtyStartUs = esp_timer_get_time();
  uint8_t* const fb = display.getFrameBuffer();
  const uint32_t bufferSize = display.getBufferSize();
  const uint16_t panelW = display.getDisplayWidth();
  const uint16_t panelH = display.getDisplayHeight();
  const uint16_t wb = display.getDisplayWidthBytes();

  if (!fb || bufferSize == 0 || wb == 0) {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    windowShadowValid_ = false;
    return;
  }

  if (windowShadow_ == nullptr) {
    windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    windowShadowValid_ = false;
  }

  if (forceFullRefresh || windowShadow_ == nullptr || !windowShadowValid_) {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    if (windowShadow_ != nullptr) {
      memcpy(windowShadow_, fb, bufferSize);
      windowShadowValid_ = true;
    }
    return;
  }

  uint16_t minByte = wb;
  uint16_t maxByte = 0;
  uint16_t minY = panelH;
  uint16_t maxY = 0;
  bool changed = false;

  for (uint16_t y = 0; y < panelH; ++y) {
    const uint32_t rowOffset = static_cast<uint32_t>(y) * wb;
    for (uint16_t bx = 0; bx < wb; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      changed = true;
      if (bx < minByte) minByte = bx;
      if (bx > maxByte) maxByte = bx;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  if (!changed) return;

  const uint16_t x = static_cast<uint16_t>(minByte * 8);
  const uint16_t y = minY;
  const uint16_t w = static_cast<uint16_t>((maxByte - minByte + 1) * 8);
  const uint16_t h = static_cast<uint16_t>(maxY - minY + 1);

  constexpr uint16_t TILE_W = 32;
  constexpr uint16_t TILE_H = 16;
  constexpr uint16_t TILE_COLS = (HalDisplay::DISPLAY_WIDTH + TILE_W - 1) / TILE_W;
  constexpr uint16_t TILE_ROWS = (HalDisplay::DISPLAY_HEIGHT + TILE_H - 1) / TILE_H;
  constexpr uint16_t TILE_COUNT = TILE_COLS * TILE_ROWS;
  constexpr uint16_t TILE_MASK_BYTES = (TILE_COUNT + 7) / 8;
  std::array<uint8_t, TILE_MASK_BYTES> tileMask{};
  uint16_t dirtyTiles = 0;

  for (uint16_t row = minY; row <= maxY; ++row) {
    const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
    for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
      const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
      const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
      const uint8_t mask = static_cast<uint8_t>(1u << (bit & 7));
      if ((tileMask[bit >> 3] & mask) == 0) {
        tileMask[bit >> 3] |= mask;
        ++dirtyTiles;
      }
    }
  }

  std::array<uint8_t, TILE_MASK_BYTES> refreshMask = tileMask;
  uint16_t refreshTiles = dirtyTiles;
  uint16_t refreshMinByte = minByte;
  uint16_t refreshMaxByte = maxByte;
  uint16_t refreshMinY = minY;
  uint16_t refreshMaxY = maxY;

  // A split frame is always followed by a catch-up frame. Since the app shadow
  // is NOT advanced for the omitted satellite, those pixels remain dirty and
  // the next pass naturally uploads their latest state (skipping only one
  // intermediate visual frame, never simulation state).
  if (clusterCatchupPending_) {
    clusterCatchupPending_ = false;
  } else if (dirtyTiles >= 2 && dirtyTiles <= 128) {
    struct DirtyComponent {
      uint16_t count = 0;
      uint16_t minTx = TILE_COLS;
      uint16_t maxTx = 0;
      uint16_t minTy = TILE_ROWS;
      uint16_t maxTy = 0;
    };
    constexpr uint8_t MAX_COMPONENTS = 32;
    std::array<uint8_t, TILE_COUNT> componentOf{};
    std::array<uint16_t, TILE_COUNT> queue{};
    std::array<DirtyComponent, MAX_COMPONENTS> components{};
    uint8_t componentCount = 0;
    bool componentOverflow = false;

    const auto tileDirty = [&](uint16_t bit) {
      return (tileMask[bit >> 3] & static_cast<uint8_t>(1u << (bit & 7))) != 0;
    };

    for (uint16_t seed = 0; seed < TILE_COUNT && !componentOverflow; ++seed) {
      if (!tileDirty(seed) || componentOf[seed] != 0) continue;
      if (componentCount >= MAX_COMPONENTS) {
        componentOverflow = true;
        break;
      }
      const uint8_t id = static_cast<uint8_t>(++componentCount);
      DirtyComponent& comp = components[id - 1];
      uint16_t qHead = 0;
      uint16_t qTail = 0;
      queue[qTail++] = seed;
      componentOf[seed] = id;

      while (qHead < qTail) {
        const uint16_t bit = queue[qHead++];
        const uint16_t tx = static_cast<uint16_t>(bit % TILE_COLS);
        const uint16_t ty = static_cast<uint16_t>(bit / TILE_COLS);
        ++comp.count;
        comp.minTx = std::min(comp.minTx, tx);
        comp.maxTx = std::max(comp.maxTx, tx);
        comp.minTy = std::min(comp.minTy, ty);
        comp.maxTy = std::max(comp.maxTy, ty);

        const auto visit = [&](int nx, int ny) {
          if (nx < 0 || ny < 0 || nx >= TILE_COLS || ny >= TILE_ROWS) return;
          const uint16_t nbit = static_cast<uint16_t>(ny * TILE_COLS + nx);
          if (!tileDirty(nbit) || componentOf[nbit] != 0) return;
          componentOf[nbit] = id;
          queue[qTail++] = nbit;
        };
        visit(static_cast<int>(tx) - 1, ty);
        visit(static_cast<int>(tx) + 1, ty);
        visit(tx, static_cast<int>(ty) - 1);
        visit(tx, static_cast<int>(ty) + 1);
      }
    }

    if (!componentOverflow && componentCount >= 2) {
      const uint32_t globalArea = static_cast<uint32_t>(w) * h;
      int bestDefer = -1;
      uint32_t bestRemainArea = globalArea;

      for (uint8_t c = 0; c < componentCount; ++c) {
        const DirtyComponent& satellite = components[c];
        if (static_cast<uint32_t>(satellite.count) * 100u > static_cast<uint32_t>(dirtyTiles) * 40u) continue;

        uint16_t rMinTx = TILE_COLS;
        uint16_t rMaxTx = 0;
        uint16_t rMinTy = TILE_ROWS;
        uint16_t rMaxTy = 0;
        uint16_t remainCount = 0;
        for (uint8_t other = 0; other < componentCount; ++other) {
          if (other == c || components[other].count == 0) continue;
          const DirtyComponent& rc = components[other];
          remainCount = static_cast<uint16_t>(remainCount + rc.count);
          rMinTx = std::min(rMinTx, rc.minTx);
          rMaxTx = std::max(rMaxTx, rc.maxTx);
          rMinTy = std::min(rMinTy, rc.minTy);
          rMaxTy = std::max(rMaxTy, rc.maxTy);
        }
        if (remainCount == 0) continue;

        // Require a genuine spatial gap. Then a bbox refresh of the remainder
        // cannot accidentally paint any byte belonging to the deferred island.
        const bool separated = satellite.maxTx < rMinTx || satellite.minTx > rMaxTx ||
                               satellite.maxTy < rMinTy || satellite.minTy > rMaxTy;
        if (!separated) continue;

        const uint32_t rx0 = static_cast<uint32_t>(rMinTx) * TILE_W;
        const uint32_t ry0 = static_cast<uint32_t>(rMinTy) * TILE_H;
        const uint32_t rx1 = std::min<uint32_t>(panelW, static_cast<uint32_t>(rMaxTx + 1) * TILE_W);
        const uint32_t ry1 = std::min<uint32_t>(panelH, static_cast<uint32_t>(rMaxTy + 1) * TILE_H);
        const uint32_t remainArea = (rx1 - rx0) * (ry1 - ry0);
        if (remainArea * 10u > globalArea * 7u) continue;  // need >=30% scan-area reduction
        if (remainArea < bestRemainArea) {
          bestRemainArea = remainArea;
          bestDefer = c;
        }
      }

      if (bestDefer >= 0) {
        const uint8_t deferredId = static_cast<uint8_t>(bestDefer + 1);
        for (uint16_t bit = 0; bit < TILE_COUNT; ++bit) {
          if (componentOf[bit] != deferredId) continue;
          refreshMask[bit >> 3] &= static_cast<uint8_t>(~(1u << (bit & 7)));
        }
        refreshTiles = static_cast<uint16_t>(dirtyTiles - components[bestDefer].count);

        // Tight byte bbox for the non-deferred pixels, not merely the tile bbox.
        refreshMinByte = wb;
        refreshMaxByte = 0;
        refreshMinY = panelH;
        refreshMaxY = 0;
        bool refreshChanged = false;
        for (uint16_t row = minY; row <= maxY; ++row) {
          const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
          for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
            const uint32_t offset = rowOffset + bx;
            if (fb[offset] == windowShadow_[offset]) continue;
            const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
            const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
            const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
            if (componentOf[bit] == deferredId) continue;
            refreshChanged = true;
            refreshMinByte = std::min(refreshMinByte, bx);
            refreshMaxByte = std::max(refreshMaxByte, bx);
            refreshMinY = std::min(refreshMinY, row);
            refreshMaxY = std::max(refreshMaxY, row);
          }
        }
        if (refreshChanged) {
          clusterCatchupPending_ = true;
          missileRefreshClusterSplit = 1;
        }
      }
    }
  }

  const uint16_t refreshX = static_cast<uint16_t>(refreshMinByte * 8);
  const uint16_t refreshY = refreshMinY;
  const uint16_t refreshW = static_cast<uint16_t>((refreshMaxByte - refreshMinByte + 1) * 8);
  const uint16_t refreshH = static_cast<uint16_t>(refreshMaxY - refreshMinY + 1);
  const uint32_t bboxPayload = static_cast<uint32_t>(refreshW / 8) * refreshH;
  const uint32_t sparsePayload = static_cast<uint32_t>(refreshTiles) * (TILE_W / 8) * TILE_H;
  const bool useSparse = refreshTiles > 0 && refreshTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
  missileRefreshDirtyTiles = dirtyTiles;
  missileRefreshTiles = refreshTiles;
  missileRefreshBboxW = refreshW;
  missileRefreshBboxH = refreshH;
  missileRefreshAppMode = useSparse ? 2 : 1;
  missileRefreshDirtyPrepUs = static_cast<uint32_t>(esp_timer_get_time() - missileDirtyStartUs);
  const int64_t missilePanelCallStartUs = esp_timer_get_time();
  if (useSparse) {
    display.displaySparseWindow(refreshMask.data(), TILE_COLS, TILE_ROWS, TILE_W, TILE_H,
                                refreshX, refreshY, refreshW, refreshH, false);
  } else {
    display.displayWindow(refreshX, refreshY, refreshW, refreshH, false);
  }
  missileRefreshPanelCallUs = static_cast<uint32_t>(esp_timer_get_time() - missilePanelCallStartUs);

  // The deferred component is guaranteed outside this bbox on at least one
  // axis, so copying the refreshed bbox cannot falsely acknowledge it. It stays
  // different from windowShadow_ and is therefore mandatory on the next frame.
  const int64_t missileShadowCopyStartUs = esp_timer_get_time();
  const uint16_t copyBytes = static_cast<uint16_t>(refreshW / 8);
  for (uint16_t row = 0; row < refreshH; ++row) {
    const uint32_t offset = static_cast<uint32_t>(refreshY + row) * wb + refreshMinByte;
    memcpy(windowShadow_ + offset, fb + offset, copyBytes);
  }
  missileRefreshShadowCopyUs = static_cast<uint32_t>(esp_timer_get_time() - missileShadowCopyStartUs);
}

void MissileCommandActivity::renderPlaying() {
  const int64_t missileProfileFrameStartUs = esp_timer_get_time();
  const bool forceFullRefresh = sceneNeedsFullRedraw_ || !windowShadowValid_;
  const bool missileProfileWaveScrub = waveScrubPending_;
  const bool missileProfileFullScene = sceneNeedsFullRedraw_;
  const bool missileProfileCatchupStart = clusterCatchupPending_;
  beginMissileProfile1Frame(missileProfileFrameStartUs, forceFullRefresh, missileProfileWaveScrub,
                            missileProfileFullScene, missileProfileCatchupStart);
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  drawPlayingFrame();
  const int64_t missileProfileAfterDrawUs = esp_timer_get_time();

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

  // First frame establishes a complete controller baseline. Then one exact
  // dirty rectangle is refreshed per synchronized game step. The call is
  // blocking, so input/simulation still cannot outrun the physical panel.
  if (forceFullRefresh) {
    // Starting/re-entering gameplay without a valid app shadow must begin from
    // a genuinely clean panel. Use the proven full-surface HALF charge scrub so
    // the Missile menu cannot remain parked behind wave 1. Once this baseline is
    // established, normal gameplay returns to 4P + Cluster1 dirty refreshes.
    const bool entryCleanScrub = !windowShadowValid_;
    missileRefreshAppMode = (missileProfileWaveScrub || entryCleanScrub) ? 3 : 4;
    if (waveScrubPending_ || entryCleanScrub) {
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
      clusterCatchupPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }
    uint8_t* const fb = display.getFrameBuffer();
    const uint32_t bufferSize = display.getBufferSize();
    if (windowShadow_ == nullptr && bufferSize != 0) {
      windowShadow_ = static_cast<uint8_t*>(heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    }
    if (windowShadow_ != nullptr && fb != nullptr && bufferSize != 0) {
      memcpy(windowShadow_, fb, bufferSize);
      windowShadowValid_ = true;
    }
  } else {
    refreshPlayingWindow(false);
  }
  const int64_t missileProfileAfterRefreshUs = esp_timer_get_time();
  if (missileProfilePendingValid) {
    missileProfilePending.drawUs = static_cast<uint32_t>(missileProfileAfterDrawUs - missileProfileFrameStartUs);
    missileProfilePending.refreshUs = static_cast<uint32_t>(missileProfileAfterRefreshUs - missileProfileAfterDrawUs);
    missileProfilePending.dirtyPrepUs = missileRefreshDirtyPrepUs;
    missileProfilePending.panelCallUs = missileRefreshPanelCallUs;
    missileProfilePending.shadowCopyUs = missileRefreshShadowCopyUs;
    missileProfilePending.dirtyTiles = missileRefreshDirtyTiles;
    missileProfilePending.refreshTiles = missileRefreshTiles;
    missileProfilePending.bboxW = missileRefreshBboxW;
    missileProfilePending.bboxH = missileRefreshBboxH;
    missileProfilePending.appMode = missileRefreshAppMode;
    missileProfilePending.clusterSplit = missileRefreshClusterSplit;
    missileProfilePending.panelKind = static_cast<uint8_t>(crossink_missile_panel_kind);
    missileProfilePending.panelUploadUs = crossink_missile_panel_upload_us;
    missileProfilePending.panelSetupUs = crossink_missile_panel_setup_us;
    missileProfilePending.panelDrfUs = crossink_missile_panel_drf_us;
    missileProfilePending.panelResyncUs = crossink_missile_panel_resync_us;
  }
  cycleRenderPending_.store(false);
}

void MissileCommandActivity::renderWaveComplete() {
  // TRUE popup: keep the exact last gameplay framebuffer as the backdrop.
  // Only paint an opaque white card over it. No clearScreen(), no header redraw,
  // no full-screen UI reconstruction.
  const Rect box = waveCompleteBox(renderer, mappedInput);
  const Rect action = waveCompleteActionRect(renderer, mappedInput);

  renderer.fillRect(box.x, box.y, box.width, box.height, false);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 2, 8, true);

  char line[72];
  std::snprintf(line, sizeof(line), "Vague %u terminee", static_cast<unsigned>(completedWave_));
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 16, box.y + 10, box.width - 32, 32}, line);

  std::snprintf(line, sizeof(line), "Score %lu   Record %lu",
                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 48, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Munitions %u   %s %u",
                static_cast<unsigned>(waveEndAmmoRemaining_),
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 76, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Tirs %u   Detruits %u",
                static_cast<unsigned>(completedWaveShotsFired_),
                static_cast<unsigned>(completedWaveEnemyKills_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 104, box.width - 36, 24}, line);

  std::snprintf(line, sizeof(line), "Efficacite : %u%%",
                static_cast<unsigned>(completedWaveEfficiencyPct_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 132, box.width - 36, 24}, line);

  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Vague suivante");

  // Keep the frozen battlefield physically untouched. Reuse the already proven
  // dirty-window path so only the popup rectangle is driven on the panel.
  //
  // IMPORTANT: do NOT invalidate the gameplay shadow here. When the user presses
  // "Vague suivante", beginPreparedWave() invalidates it and the accepted
  // EntryHalf path performs the full clean transition AFTER the popup disappears.
  refreshPlayingWindow(false);
  cycleRenderPending_.store(false);
}

void MissileCommandActivity::renderGameOver() {
  drawFullPlayingScene();
  drawPlayingFrame();
  const Rect box = gameOverBox(renderer);
  const Rect action = gameOverActionRect(renderer);
  renderer.fillRect(box.x, box.y, box.width, box.height, false);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 2, 8, true);
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 12, box.y + 18, box.width - 24, 36},
                   "Toutes les villes sont perdues");
  char scoreText[64];
  std::snprintf(scoreText, sizeof(scoreText), "Score final : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 12, box.y + 68, box.width - 24, 30}, scoreText);
  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Retour au menu");
  renderer.displayBuffer();
  sceneNeedsFullRedraw_ = true;
}


bool MissileCommandActivity::saveGame() {
  if (aliveCityCount() <= 0) return false;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE", SAVE_PATH, file)) return false;
  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));
  const uint8_t baseMode = baseMode_ ? 1 : 0;
  const uint8_t realisticExplosions = realisticExplosions_ ? 1 : 0;
  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&
            writeValue(file, wave_) && writeValue(file, score_) && writeValue(file, baseMode) &&
            writeValue(file, realisticExplosions);
  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();
  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();
  if (ok) ok = file.write(batteriesAlive_.data(), batteriesAlive_.size()) == batteriesAlive_.size();
  file.close();
  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    return false;
  }
  hasSavedGame_ = true;
  return true;
}

bool MissileCommandActivity::loadSavedGame() {
  if (!Storage.exists(SAVE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MISSILE", SAVE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t difficulty = 0;
  uint16_t wave = 0;
  uint32_t score = 0;
  uint8_t baseMode = 0;
  uint8_t realisticExplosions = 0;
  std::array<uint8_t, kCityCount> cities{};
  std::array<uint8_t, kBatteryCount> ammo{};
  std::array<uint8_t, kBatteryCount> batteries{{1, 1, 1}};
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, difficulty) &&
            readValue(file, wave) && readValue(file, score);
  if (ok) ok = readValue(file, baseMode);
  if (ok) ok = readValue(file, realisticExplosions);
  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());
  if (ok) ok = file.read(ammo.data(), ammo.size()) == static_cast<int>(ammo.size());
  if (ok) ok = file.read(batteries.data(), batteries.size()) == static_cast<int>(batteries.size());
  file.close();
  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0 || baseMode > 1 ||
      realisticExplosions > 1) {
    clearSavedGame();
    return false;
  }
  for (uint8_t alive : cities) {
    if (alive > 1) {
      clearSavedGame();
      return false;
    }
  }
  for (uint8_t alive : batteries) {
    if (alive > 1) {
      clearSavedGame();
      return false;
    }
  }
  difficulty_ = difficulty;
  wave_ = wave;
  score_ = score;
  baseMode_ = baseMode != 0;
  realisticExplosions_ = realisticExplosions != 0;
  citiesAlive_ = cities;
  ammo_ = ammo;
  batteriesAlive_ = batteries;
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  hasSavedGame_ = aliveCityCount() > 0;
  return hasSavedGame_;
}

void MissileCommandActivity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
}

int MissileCommandActivity::scoreSlot() const {
  const int difficulty = std::clamp(difficulty_, 0, kDifficultyCount - 1);
  return difficulty + (baseMode_ ? kDifficultyCount : 0);
}

void MissileCommandActivity::syncCurrentHighScore() {
  highScore_ = highScores_[static_cast<size_t>(scoreSlot())];
}

bool MissileCommandActivity::loadHighScore() {
  highScores_.fill(0);
  highScore_ = 0;
  if (!Storage.exists(SCORE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MISSILE", SCORE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t count = 0;
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, count);
  if (!ok || magic != SCORE_MAGIC || version != SCORE_VERSION || count != kScoreSlotCount) {
    file.close();
    highScores_.fill(0);
    syncCurrentHighScore();
    return false;
  }
  for (int i = 0; i < kScoreSlotCount && ok; ++i) ok = readValue(file, highScores_[static_cast<size_t>(i)]);
  file.close();
  if (!ok) highScores_.fill(0);
  syncCurrentHighScore();
  return ok;
}

bool MissileCommandActivity::saveHighScore() {
  if (score_ > highScore_) highScore_ = score_;
  uint32_t& slot = highScores_[static_cast<size_t>(scoreSlot())];
  if (highScore_ > slot) slot = highScore_;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE", SCORE_PATH, file)) return false;
  const uint8_t count = kScoreSlotCount;
  bool ok = writeValue(file, SCORE_MAGIC) && writeValue(file, SCORE_VERSION) && writeValue(file, count);
  for (int i = 0; i < kScoreSlotCount && ok; ++i) ok = writeValue(file, highScores_[static_cast<size_t>(i)]);
  file.close();
  return ok;
}
