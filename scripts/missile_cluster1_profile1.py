from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:240]!r}")
    p.write_text(text.replace(old, new, 1))


def replace_after(path: str, after: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    pos = text.find(after)
    if pos < 0:
        raise SystemExit(f"function anchor not found in {path}: {after!r}")
    hit = text.find(old, pos)
    if hit < 0:
        raise SystemExit(f"post-anchor text not found in {path}: {old[:240]!r}")
    p.write_text(text[:hit] + new + text[hit + len(old):])


DRIVER = "freeink-sdk/libs/display/FreeInkDisplay/src/driver/Uc8279X4Driver.cpp"
CPP = "src/activities/home/MissileCommandActivity.cpp"

# ---------------------------------------------------------------------------
# UC8279 telemetry. Pure timing instrumentation: no refresh policy, LUT, PLL,
# SPI, analog, or waveform changes. The app reads these C-linkage counters after
# each blocking panel call.
# kind: 1=bbox window, 2=sparse window, 3=HALF scrub, 4=FULL, 5=full-surface FAST.
# ---------------------------------------------------------------------------
replace_once(DRIVER, '#include <Arduino.h>\n', '#include <Arduino.h>\n#include <esp_timer.h>\n')
replace_once(
    DRIVER,
    'namespace freeink {\n',
    r'''extern "C" {
volatile uint32_t crossink_missile_panel_kind = 0;
volatile uint32_t crossink_missile_panel_upload_us = 0;
volatile uint32_t crossink_missile_panel_setup_us = 0;
volatile uint32_t crossink_missile_panel_drf_us = 0;
volatile uint32_t crossink_missile_panel_resync_us = 0;
}

namespace freeink {
''',
)

replace_after(
    DRIVER,
    'bool Uc8279X4Driver::displayStart(',
    '  (void)prev;\n',
    r'''  (void)prev;
  crossink_missile_panel_kind =
      mode == RefreshMode::Half ? 3u : (mode == RefreshMode::Full ? 4u : 5u);
  crossink_missile_panel_upload_us = 0;
  crossink_missile_panel_setup_us = 0;
  crossink_missile_panel_drf_us = 0;
  crossink_missile_panel_resync_us = 0;
''',
)
replace_after(
    DRIVER,
    'bool Uc8279X4Driver::displayStart(',
    '  streamPlane(bus, CMD_DTM2, fb);\n',
    r'''  const int64_t profileUploadStartUs = esp_timer_get_time();
  streamPlane(bus, CMD_DTM2, fb);
''',
)
replace_after(
    DRIVER,
    'bool Uc8279X4Driver::displayStart(',
    '  _redriveAfterGray = false;\n\n  // Built-in refresh setup',
    r'''  _redriveAfterGray = false;
  crossink_missile_panel_upload_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileUploadStartUs);
  const int64_t profileSetupStartUs = esp_timer_get_time();

  // Built-in refresh setup''',
)
replace_after(
    DRIVER,
    'bool Uc8279X4Driver::displayStart(',
    '  _pendingPartial = fast;\n',
    r'''  crossink_missile_panel_setup_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileSetupStartUs);
  _pendingPartial = fast;
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayFinish(',
    '  bus.waitRefreshComplete(" 8279x4_DRF");\n',
    r'''  const int64_t profileDrfStartUs = esp_timer_get_time();
  bus.waitRefreshComplete(" 8279x4_DRF");
  crossink_missile_panel_drf_us = static_cast<uint32_t>(esp_timer_get_time() - profileDrfStartUs);
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayFinish(',
    '  streamPlane(bus, CMD_DTM1, fb);\n  _oldPlaneValid = true;\n',
    r'''  const int64_t profileResyncStartUs = esp_timer_get_time();
  streamPlane(bus, CMD_DTM1, fb);
  crossink_missile_panel_resync_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileResyncStartUs);
  _oldPlaneValid = true;
''',
)

# Ordinary bbox window.
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayWindow(',
    '  _grayBaseValid = false;\n',
    r'''  crossink_missile_panel_kind = 1;
  crossink_missile_panel_upload_us = 0;
  crossink_missile_panel_setup_us = 0;
  crossink_missile_panel_drf_us = 0;
  crossink_missile_panel_resync_us = 0;
  _grayBaseValid = false;
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayWindow(',
    '  if (prev != nullptr) streamWindowPlane(bus, CMD_DTM1, prev, x, y, w, h);\n  streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);\n',
    r'''  const int64_t profileUploadStartUs = esp_timer_get_time();
  if (prev != nullptr) streamWindowPlane(bus, CMD_DTM1, prev, x, y, w, h);
  streamWindowPlane(bus, CMD_DTM2, fb, x, y, w, h);
  crossink_missile_panel_upload_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileUploadStartUs);
  const int64_t profileSetupStartUs = esp_timer_get_time();
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayWindow(',
    '  bus.waitRefreshComplete(" 8279x4_window_gameA2Lite_pll0f_DRF");\n',
    r'''  crossink_missile_panel_setup_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileSetupStartUs);
  const int64_t profileDrfStartUs = esp_timer_get_time();
  bus.waitRefreshComplete(" 8279x4_window_gameA2Lite_pll0f_DRF");
  crossink_missile_panel_drf_us = static_cast<uint32_t>(esp_timer_get_time() - profileDrfStartUs);
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayWindow(',
    '  // Keep DTM1 synchronized only inside the region that actually changed. Pixels\n',
    r'''  const int64_t profileResyncStartUs = esp_timer_get_time();
  // Keep DTM1 synchronized only inside the region that actually changed. Pixels
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displayWindow(',
    '  streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h);\n  bus.cmd(CMD_PARTIAL_OUT);\n',
    r'''  streamWindowPlane(bus, CMD_DTM1, fb, x, y, w, h);
  crossink_missile_panel_resync_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileResyncStartUs);
  bus.cmd(CMD_PARTIAL_OUT);
''',
)

# Sparse window (OPT12 already removed the redundant pre-DRF DTM1 upload).
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  _grayBaseValid = false;\n',
    r'''  crossink_missile_panel_kind = 2;
  crossink_missile_panel_upload_us = 0;
  crossink_missile_panel_setup_us = 0;
  crossink_missile_panel_drf_us = 0;
  crossink_missile_panel_resync_us = 0;
  _grayBaseValid = false;
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  bus.cmd(CMD_PARTIAL_IN);\n\n  // DTM1 and DTM2 are kept equal',
    r'''  bus.cmd(CMD_PARTIAL_IN);
  const int64_t profileUploadStartUs = esp_timer_get_time();

  // DTM1 and DTM2 are kept equal''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '      ++dirtyCount;\n    }\n  }\n\n  if (dirtyCount == 0) {\n',
    r'''      ++dirtyCount;
    }
  }
  crossink_missile_panel_upload_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileUploadStartUs);

  if (dirtyCount == 0) {
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  // One DRF only: last PTL becomes the physical scan bbox; RAM upload itself was sparse.\n',
    r'''  const int64_t profileSetupStartUs = esp_timer_get_time();
  // One DRF only: last PTL becomes the physical scan bbox; RAM upload itself was sparse.
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  bus.waitRefreshComplete(" 8279x4_sparse_gameA2Lite_pll0f_DRF");\n',
    r'''  crossink_missile_panel_setup_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileSetupStartUs);
  const int64_t profileDrfStartUs = esp_timer_get_time();
  bus.waitRefreshComplete(" 8279x4_sparse_gameA2Lite_pll0f_DRF");
  crossink_missile_panel_drf_us = static_cast<uint32_t>(esp_timer_get_time() - profileDrfStartUs);
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  // Re-establish the global invariant only for tiles that actually changed.\n',
    r'''  const int64_t profileResyncStartUs = esp_timer_get_time();
  // Re-establish the global invariant only for tiles that actually changed.
''',
)
replace_after(
    DRIVER,
    'void Uc8279X4Driver::displaySparseWindow(',
    '  bus.cmd(CMD_PARTIAL_OUT);\n  _oldPlaneValid = true;\n',
    r'''  crossink_missile_panel_resync_us =
      static_cast<uint32_t>(esp_timer_get_time() - profileResyncStartUs);
  bus.cmd(CMD_PARTIAL_OUT);
  _oldPlaneValid = true;
''',
)

# ---------------------------------------------------------------------------
# App-side trace: 200 aligned render-start -> next-render-start cycles, buffered
# in PSRAM so SD writes do not contaminate the captured sample timings.
# ---------------------------------------------------------------------------
replace_once(CPP, '#include <esp_heap_caps.h>\n', '#include <esp_heap_caps.h>\n#include <esp_timer.h>\n')
replace_once(
    CPP,
    '#include <esp_timer.h>\n',
    r'''#include <esp_timer.h>

extern "C" {
extern volatile uint32_t crossink_missile_panel_kind;
extern volatile uint32_t crossink_missile_panel_upload_us;
extern volatile uint32_t crossink_missile_panel_setup_us;
extern volatile uint32_t crossink_missile_panel_drf_us;
extern volatile uint32_t crossink_missile_panel_resync_us;
}
''',
)

profile_defs = r'''
constexpr const char MISSILE_PROFILE1_TRACE_PATH[] =
    "/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-trace.csv";
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

'''
replace_once(
    CPP,
    'constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";\n',
    'constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";\n' + profile_defs,
)

# Dirty pipeline timings around the existing Cluster1 algorithm.
replace_once(
    CPP,
    'void MissileCommandActivity::refreshPlayingWindow(bool forceFullRefresh) {\n',
    'void MissileCommandActivity::refreshPlayingWindow(bool forceFullRefresh) {\n'
    '  const int64_t missileDirtyStartUs = esp_timer_get_time();\n',
)
replace_once(
    CPP,
    '        if (refreshChanged) clusterCatchupPending_ = true;\n',
    '        if (refreshChanged) {\n'
    '          clusterCatchupPending_ = true;\n'
    '          missileRefreshClusterSplit = 1;\n'
    '        }\n',
)
old_panel = r'''  const bool useSparse = refreshTiles > 0 && refreshTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
  if (useSparse) {
    display.displaySparseWindow(refreshMask.data(), TILE_COLS, TILE_ROWS, TILE_W, TILE_H,
                                refreshX, refreshY, refreshW, refreshH, false);
  } else {
    display.displayWindow(refreshX, refreshY, refreshW, refreshH, false);
  }

  // The deferred component is guaranteed outside this bbox on at least one
  // axis, so copying the refreshed bbox cannot falsely acknowledge it. It stays
  // different from windowShadow_ and is therefore mandatory on the next frame.
  const uint16_t copyBytes = static_cast<uint16_t>(refreshW / 8);
  for (uint16_t row = 0; row < refreshH; ++row) {
    const uint32_t offset = static_cast<uint32_t>(refreshY + row) * wb + refreshMinByte;
    memcpy(windowShadow_ + offset, fb + offset, copyBytes);
  }
'''
new_panel = r'''  const bool useSparse = refreshTiles > 0 && refreshTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
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
'''
replace_once(CPP, old_panel, new_panel)

# Frame-aligned trace capture around draw + refresh. The normal 200-frame summary
# benchmark remains active as a cross-check and gets a PROFILE1 identity below.
replace_once(
    CPP,
    'void MissileCommandActivity::renderPlaying() {\n  const bool forceFullRefresh = sceneNeedsFullRedraw_ || !windowShadowValid_;\n',
    r'''void MissileCommandActivity::renderPlaying() {
  const int64_t missileProfileFrameStartUs = esp_timer_get_time();
  const bool forceFullRefresh = sceneNeedsFullRedraw_ || !windowShadowValid_;
  const bool missileProfileWaveScrub = waveScrubPending_;
  const bool missileProfileFullScene = sceneNeedsFullRedraw_;
  const bool missileProfileCatchupStart = clusterCatchupPending_;
  beginMissileProfile1Frame(missileProfileFrameStartUs, forceFullRefresh, missileProfileWaveScrub,
                            missileProfileFullScene, missileProfileCatchupStart);
''',
)
replace_once(
    CPP,
    '  drawPlayingFrame();\n\n  // First frame establishes a complete controller baseline.',
    r'''  drawPlayingFrame();
  const int64_t missileProfileAfterDrawUs = esp_timer_get_time();

  // First frame establishes a complete controller baseline.''',
)
replace_once(
    CPP,
    '  if (forceFullRefresh) {\n    if (waveScrubPending_) {\n',
    r'''  if (forceFullRefresh) {
    missileRefreshAppMode = missileProfileWaveScrub ? 3 : 4;
    if (waveScrubPending_) {
''',
)
replace_once(
    CPP,
    '  } else {\n    refreshPlayingWindow(false);\n  }\n  cycleRenderPending_.store(false);\n',
    r'''  } else {
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
''',
)

# Distinct normal-summary identity so this instrumented run cannot be confused
# with the accepted uninstrumented Cluster1 baseline.
text = Path(CPP).read_text()
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1', 'MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1,%lu,%lu,%lu,%lu,%lu',
)
Path(CPP).write_text(text)

print("Cluster1 PROFILE1 instrumentation applied (draw/dirty/upload/setup/DRF/resync trace)")
