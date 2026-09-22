from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  if (score_ > highScore_) highScore_ = score_;

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

new = r'''  // Logical score/high-score still update immediately. The e-ink Score value
  // is intentionally frozen for the whole wave. startWave() requests a full
  // gameplay redraw, so the newly completed-wave score is painted cleanly once
  // at the next wave boundary (which already gets the accepted inter-wave HALF).
  if (score_ > highScore_) highScore_ = score_;
'''

if old not in text:
    raise SystemExit("BaseMode8 2-second Score block not found")
text = text.replace(old, new, 1)

# The 2-second score scrub hook remains compiled but permanently dormant because
# hudScoreCleanPending_ is never set during gameplay in this variant. Keeping it
# untouched minimizes risk to the frozen Cluster1/display pipeline.

text = text.replace("/missile-command-bm8-score2s-hitpoly-bench.csv",
                    "/missile-command-bm9-score-wave-hitpoly-bench.csv")
text = text.replace("/missile-command-bm8-score2s-hitpoly-trace.csv",
                    "/missile-command-bm9-score-wave-hitpoly-trace.csv")
text = text.replace("bm8-score2s-hitpoly-started", "bm9-score-wave-hitpoly-started")
text = text.replace("bm8-score2s-hitpoly,%lu,%lu,%lu,%lu,%lu",
                    "bm9-score-wave-hitpoly,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM8-SCORE2S-HITPOLY", "MISSILE-BM9-SCORE-WAVE-HITPOLY")

CPP.write_text(text)
print("Missile BaseMode9: Score display refreshes only on full scene / wave boundary")
