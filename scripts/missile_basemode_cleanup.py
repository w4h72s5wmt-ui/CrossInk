from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:220]!r}")
    text = text.replace(old, new, 1)


# Base mode uses exactly the same visual checkbox treatment as the difficulty
# rows: same box, same centered filled inner square. No special X rendering.
replace_once(
'''    if (itemIndex < kDifficultyCount && itemIndex == difficulty_) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    } else if (itemIndex == 3 && baseMode_) {
      renderer.drawLine(boxX + 5, boxY + 5, boxX + boxSize - 6, boxY + boxSize - 6, 2, true);
      renderer.drawLine(boxX + boxSize - 6, boxY + 5, boxX + 5, boxY + boxSize - 6, 2, true);
    }
''',
'''    const bool checked = (itemIndex < kDifficultyCount && itemIndex == difficulty_) ||
                         (itemIndex == 3 && baseMode_);
    if (checked) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
''',
"uniform Base checkbox")

# Continue always reloads the saved payload immediately before resuming. Menu
# selections are therefore settings for a NEW game only and cannot mutate an
# existing saved game's difficulty or mode.
replace_once(
'''  if (row == 4) {
    if (hasSavedGame_) continueGame();
    return;
  }
''',
'''  if (row == 4) {
    if (hasSavedGame_ && loadSavedGame()) continueGame();
    return;
  }
''',
"locked Continue settings")

# Development save format is intentionally strict v2 only. Remove all v1
# compatibility branches: old saves are simply rejected and cleared.
replace_once(
'''  if (ok && version >= 2) ok = readValue(file, baseMode);
''',
'''  if (ok) ok = readValue(file, baseMode);
''',
"strict Base-mode field")
replace_once(
'''  if (ok && version >= 2)
    ok = file.read(batteries.data(), batteries.size()) == static_cast<int>(batteries.size());
''',
'''  if (ok) ok = file.read(batteries.data(), batteries.size()) == static_cast<int>(batteries.size());
''',
"strict batteries field")
replace_once(
'''  if (!ok || magic != SAVE_MAGIC || (version != 1 && version != 2) || difficulty > 2 || wave == 0 || baseMode > 1) {
''',
'''  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0 || baseMode > 1) {
''',
"strict save version")
replace_once(
'''  baseMode_ = version >= 2 && baseMode != 0;
''',
'''  baseMode_ = baseMode != 0;
''',
"strict Base-mode restore")

# Explosion2 keeps only the black outer contour. The field is recomposed white
# before entities are drawn, so removing the inner diamond/core leaves a clean
# white explosion interior while retaining the smoother octagonal silhouette.
replace_once(
'''  const int inner = std::max(2, radius * 3 / 5);
  drawClippedLine1px(renderer, clip, x, y - inner, x + inner, y);
  drawClippedLine1px(renderer, clip, x + inner, y, x, y + inner);
  drawClippedLine1px(renderer, clip, x, y + inner, x - inner, y);
  drawClippedLine1px(renderer, clip, x - inner, y, x, y - inner);

  const int core = std::max(1, radius / 7);
  const int x0 = std::max(x - core, clip.x);
  const int y0 = std::max(y - core, clip.y);
  const int x1 = std::min(x + core, clip.x + clip.width - 1);
  const int y1 = std::min(y + core, clip.y + clip.height - 1);
  if (x0 <= x1 && y0 <= y1) renderer.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, true);
''',
'''  // White interior by design: outer 1-bit contour only.
''',
"white explosion interior")

# Give the next A/B its own PROFILE1 files.
text = text.replace("profile1-entryhalf-explosion2-basemode-trace.csv",
                    "profile1-entryhalf-explosion2-basemode2-trace.csv")
text = text.replace("profile1-entryhalf-explosion2-basemode-bench.csv",
                    "profile1-entryhalf-explosion2-basemode2-bench.csv")
text = text.replace("PROFILE1-ENTRYHALF-EXP2-BASEMODE", "PROFILE1-ENTRYHALF-EXP2-BASEMODE2")
text = text.replace("profile1-entryhalf-explosion2-basemode-started",
                    "profile1-entryhalf-explosion2-basemode2-started")
text = text.replace("profile1-entryhalf-explosion2-basemode,%lu,%lu,%lu,%lu,%lu",
                    "profile1-entryhalf-explosion2-basemode2,%lu,%lu,%lu,%lu,%lu")

CPP.write_text(text)
print("Missile BaseMode2: uniform checkbox, locked continue, strict saves, white explosions applied")
