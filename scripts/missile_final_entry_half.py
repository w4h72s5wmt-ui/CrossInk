from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  if (forceFullRefresh) {
    if (waveScrubPending_) {
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }
'''

new = r'''  if (forceFullRefresh) {
    // Entering/re-entering gameplay without a valid gameplay shadow starts from
    // the proven full-surface HALF charge scrub. This removes menu retention
    // before wave 1. Once the baseline is valid, ordinary gameplay remains on
    // the accepted 4P + OPT12 + Cluster1 dirty-refresh path.
    const bool entryCleanScrub = !windowShadowValid_;
    if (waveScrubPending_ || entryCleanScrub) {
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
      clusterCatchupPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }
'''

if old not in text:
    raise SystemExit("force-full refresh block not found")
text = text.replace(old, new, 1)

# Final release identity only. Keep the normal lightweight 200-frame summary
# benchmark produced by the established patch chain, but no PROFILE1 tracing,
# no PSRAM trace buffers, and no extra driver telemetry.
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-bench.csv',
    '/missile-command-final-entryhalf-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1', 'MISSILE-FINAL-ENTRYHALF')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-started',
    'missile-final-entryhalf-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1,%lu,%lu,%lu,%lu,%lu',
    'missile-final-entryhalf,%lu,%lu,%lu,%lu,%lu',
)

CPP.write_text(text)
print("Final Missile release: clean entry HALF + accepted 4P OPT12 Cluster1 applied")
