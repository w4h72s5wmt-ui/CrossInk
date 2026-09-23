from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  // Inter-wave is static and can use the stock clean HALF. The visible pixels
  // outside the card are unchanged, so the user still sees the frozen battlefield.
  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  cycleRenderPending_.store(false);
}
'''

new = r'''  // Keep the frozen battlefield physically untouched. Reuse the already proven
  // dirty-window path so only the popup rectangle is driven on the panel.
  //
  // IMPORTANT: do NOT invalidate the gameplay shadow here. When the user presses
  // "Vague suivante", beginPreparedWave() invalidates it and the accepted
  // EntryHalf path performs the full clean transition AFTER the popup disappears.
  refreshPlayingWindow(false);
  cycleRenderPending_.store(false);
}
'''

if old not in text:
    raise SystemExit("BaseMode13 popup HALF-refresh tail not found")
text = text.replace(old, new, 1)

text = text.replace("/missile-command-bm13-true-popup-bench.csv",
                    "/missile-command-bm14-popup-local-refresh-bench.csv")
text = text.replace("/missile-command-bm13-true-popup-trace.csv",
                    "/missile-command-bm14-popup-local-refresh-trace.csv")
text = text.replace("bm13-true-popup-started", "bm14-popup-local-refresh-started")
text = text.replace("bm13-true-popup,%lu,%lu,%lu,%lu,%lu",
                    "bm14-popup-local-refresh,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM13-TRUE-POPUP", "MISSILE-BM14-POPUP-LOCAL")

CPP.write_text(text)
print("Missile BaseMode14: popup uses local dirty refresh; full clean deferred until popup dismissal")
