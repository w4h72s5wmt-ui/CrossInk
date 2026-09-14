from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  if (forceFullRefresh) {
    missileRefreshAppMode = missileProfileWaveScrub ? 3 : 4;
    if (waveScrubPending_) {
      renderer.displayBuffer(HalDisplay::HALF_REFRESH);
      waveScrubPending_ = false;
    } else {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    }
'''

new = r'''  if (forceFullRefresh) {
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
'''

if old not in text:
    raise SystemExit("PROFILE1 force-full refresh block not found")
text = text.replace(old, new, 1)

# Keep this A/B unmistakable in both summary and detailed trace filenames.
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-trace.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-trace.csv',
)
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1',
                    'MISSILE-A2-OPT12-4P-CLUSTER1-PROFILE1-ENTRYHALF')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-profile1-entryhalf,%lu,%lu,%lu,%lu,%lu',
)

CPP.write_text(text)
print("PROFILE1 EntryHalf: clean full-screen HALF baseline on gameplay entry applied")
