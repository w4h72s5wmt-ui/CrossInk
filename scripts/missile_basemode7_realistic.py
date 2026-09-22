from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:280]!r}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# State/menu: add a seventh row and persist the Realistic Explosions setting.
# It is intentionally visual-only: collision radius/centre remain the accepted
# Explosion2 gameplay values, so the existing Villes/Bases score classes stay
# comparable. Continue reloads the saved setting just like Base mode.
# ---------------------------------------------------------------------------
h = HDR.read_text()
h = replace_once(h, "  static constexpr int kMenuRowCount = 6;\n",
                 "  static constexpr int kMenuRowCount = 7;\n", "menu row count")
h = replace_once(h, "  bool baseMode_ = false;\n",
                 "  bool baseMode_ = false;\n  bool realisticExplosions_ = false;\n",
                 "realistic explosion state")
HDR.write_text(h)

c = CPP.read_text()

c = replace_once(c, "constexpr uint8_t SAVE_VERSION = 2;\n",
                 "constexpr uint8_t SAVE_VERSION = 3;\n", "save v3")

# ---------------------------------------------------------------------------
# Explosion cache extension.
# BaseMode5 already precalculates regular pentagon/hexagon/octagon contours for
# every radius and 45-degree orientation. Add tiny precalculated X/Y offsets.
# With the checkbox off, BaseMode5 behaviour is unchanged (fixed shape + angle
# animation). With it on, shape and centre offset both evolve every 220 ms.
# ---------------------------------------------------------------------------
c = replace_once(
    c,
    "constexpr uint32_t EXP_ROT_STEP_US = 120000;\n",
    "constexpr uint32_t EXP_ROT_STEP_US = 120000;\n"
    "constexpr uint32_t EXP_REAL_SHAPE_STEP_US = 190000;\n"
    "constexpr uint8_t EXP_REAL_OFFSET_COUNT = 8;\n",
    "realistic explosion timing",
)
c = replace_once(
    c,
    "    expCache{};\n"
    "bool expCacheReady = false;\n",
    "    expCache{};\n"
    "std::array<std::array<ExpPt, EXPLOSION_MAX_RADIUS + 1>, EXP_REAL_OFFSET_COUNT> expOffsetCache{};\n"
    "bool expCacheReady = false;\n",
    "offset cache declaration",
)

c = replace_once(
    c,
    "  expCacheReady = true;\n"
    "}\n\n"
    "uint8_t explosionRotationIndex(uint32_t ageUs, uint8_t seed) {\n",
    "  // Precalculate subtle visual centre motion as a function of radius. At\n"
    "  // max radius the displacement reaches ~6-8 px and naturally tends to\n"
    "  // zero for the smallest explosion frames.\n"
    "  constexpr int16_t offsetXQ10[EXP_REAL_OFFSET_COUNT] = {0, 171, -171, 228, -228, 114, -114, 200};\n"
    "  constexpr int16_t offsetYQ10[EXP_REAL_OFFSET_COUNT] = {0, -143, 143, 114, -114, 228, -228, 171};\n"
    "  for (uint8_t stage = 0; stage < EXP_REAL_OFFSET_COUNT; ++stage) {\n"
    "    for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {\n"
    "      expOffsetCache[stage][radius] = {\n"
    "          toPixel(static_cast<int32_t>(radius) * offsetXQ10[stage]),\n"
    "          toPixel(static_cast<int32_t>(radius) * offsetYQ10[stage])};\n"
    "    }\n"
    "  }\n"
    "  expCacheReady = true;\n"
    "}\n\n"
    "uint8_t explosionRotationIndex(uint32_t ageUs, uint8_t seed) {\n",
    "offset cache precompute",
)

old_shape_fn = '''uint8_t explosionShapeIndex(uint8_t seed) {\n  return static_cast<uint8_t>((seed >> 4) % EXP_SHAPE_COUNT);\n}\n'''
new_shape_fn = '''uint8_t explosionBaseShape(uint8_t seed) {\n  const uint8_t shape = static_cast<uint8_t>((seed >> 4) & 0x03u);\n  return static_cast<uint8_t>(shape % EXP_SHAPE_COUNT);\n}\n\nuint8_t explosionShapeIndex(uint32_t ageUs, uint8_t seed, bool realistic) {\n  const uint8_t base = explosionBaseShape(seed);\n  if (!realistic) return base;\n\n  // Eight random-looking morph profiles. Adjacent states never repeat, so the\n  // pentagon / hexagon / octagon change is visible inside each explosion.\n  constexpr uint8_t shapeProfiles[8][8] = {\n      {0, 1, 2, 1, 0, 2, 0, 1}, {1, 0, 2, 0, 1, 2, 1, 0},\n      {2, 0, 1, 0, 2, 1, 2, 0}, {0, 2, 1, 2, 0, 1, 0, 2},\n      {1, 2, 0, 2, 1, 0, 1, 2}, {2, 1, 0, 1, 2, 0, 2, 1},\n      {0, 1, 0, 2, 1, 2, 0, 2}, {2, 0, 2, 1, 0, 1, 2, 1},\n  };\n  const uint8_t stage = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);\n  const uint8_t profile = static_cast<uint8_t>((seed >> 5) & 0x07u);\n  return static_cast<uint8_t>((base + shapeProfiles[profile][stage]) % EXP_SHAPE_COUNT);\n}\n\nExpPt explosionVisualOffset(uint32_t ageUs, uint8_t seed, int radius, bool realistic) {\n  if (!realistic) return ExpPt{};\n  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);\n  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);\n  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_REAL_SHAPE_STEP_US) & 0x07u);\n  const uint8_t stride = (seed & 0x40u) != 0 ? 5u : 3u;\n  const uint8_t travel = static_cast<uint8_t>((step * stride) & 0x07u);\n  const uint8_t stage = (seed & 0x08u) != 0\n                            ? static_cast<uint8_t>((start + EXP_REAL_OFFSET_COUNT - travel) & 0x07u)\n                            : static_cast<uint8_t>((start + travel) & 0x07u);\n  return expOffsetCache[stage][cr];\n}\n'''
c = replace_once(c, old_shape_fn, new_shape_fn, "dynamic shape/offset helpers")

old_spawn = '''    const uint32_t explosionRnd = esp_random();\n    const uint8_t shape = static_cast<uint8_t>((explosionRnd >> 4) % EXP_SHAPE_COUNT);\n    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3) |\n                                           (shape << 4));\n    explosion.phaseElapsedUs = 0;\n'''
new_spawn = '''    const uint32_t explosionRnd = esp_random();\n    const uint8_t shape = static_cast<uint8_t>((explosionRnd >> 8) % EXP_SHAPE_COUNT);\n    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3) |\n                                           (shape << 4) | (((explosionRnd >> 6) & 0x01u) << 6) |\n                                           (((explosionRnd >> 7) & 0x01u) << 7));\n    explosion.phaseElapsedUs = 0;\n'''
c = replace_once(c, old_spawn, new_spawn, "realistic explosion seed")

old_draw = '''      drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs),\n                           explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase),\n                           explosionShapeIndex(explosion.phase));\n'''
new_draw = '''      {\n        const int explosionR = explosionRadius(explosion.phaseElapsedUs);\n        const ExpPt visualOffset =\n            explosionVisualOffset(explosion.phaseElapsedUs, explosion.phase, explosionR, realisticExplosions_);\n        drawExplosionClipped(renderer, explosionClip, explosion.x + visualOffset.x, explosion.y + visualOffset.y, explosionR,\n                             explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase),\n                             explosionShapeIndex(explosion.phaseElapsedUs, explosion.phase, realisticExplosions_));\n      }\n'''
c = replace_once(c, old_draw, new_draw, "realistic explosion draw")

# ---------------------------------------------------------------------------
# Menu rows: difficulty 0..2, Base mode 3, Realistic Explosions 4,
# Continue 5, New Game 6.
# ---------------------------------------------------------------------------
old_activate = '''  if (row == 3) {\n    baseMode_ = !baseMode_;\n    syncCurrentHighScore();\n    requestUpdate();\n    return;\n  }\n  if (row == 4) {\n    if (hasSavedGame_ && loadSavedGame()) continueGame();\n    return;\n  }\n  if (row != 5) return;\n'''
new_activate = '''  if (row == 3) {\n    baseMode_ = !baseMode_;\n    syncCurrentHighScore();\n    requestUpdate();\n    return;\n  }\n  if (row == 4) {\n    realisticExplosions_ = !realisticExplosions_;\n    requestUpdate();\n    return;\n  }\n  if (row == 5) {\n    if (hasSavedGame_ && loadSavedGame()) continueGame();\n    return;\n  }\n  if (row != 6) return;\n'''
c = replace_once(c, old_activate, new_activate, "realistic menu activation")

old_items = '''  items[3].label = "Mode bases";\n  items[3].value = nullptr;\n  items[3].actionValue = 3;\n\n  items[4].label = "Continuer";\n  if (hasSavedGame_) {\n    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",\n                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));\n    items[4].value = continueValue_.data();\n  } else {\n    items[4].value = "Aucune partie";\n  }\n  items[4].actionValue = 4;\n\n  items[5].label = "Nouvelle partie";\n  items[5].value = DIFFICULTY_LABELS[difficulty_];\n  items[5].actionValue = 5;\n'''
new_items = '''  items[3].label = "Mode bases";\n  items[3].value = nullptr;\n  items[3].actionValue = 3;\n\n  items[4].label = "Explosions réalistes";\n  items[4].value = nullptr;\n  items[4].actionValue = 4;\n\n  items[5].label = "";\n  if (hasSavedGame_) {\n    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",\n                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));\n    items[5].value = nullptr;\n  } else {\n    items[5].value = nullptr;\n  }\n  items[5].actionValue = 5;\n\n  items[6].label = "";\n  items[6].value = nullptr;\n  items[6].actionValue = 6;\n'''
c = replace_once(c, old_items, new_items, "realistic menu row")

c = replace_once(
    c,
    "    if ((itemIndex < 0 || itemIndex >= kDifficultyCount) && itemIndex != 3) continue;\n",
    "    if ((itemIndex < 0 || itemIndex >= kDifficultyCount) && itemIndex != 3 && itemIndex != 4) continue;\n",
    "checkbox rows",
)
c = replace_once(
    c,
    "    const bool checked = (itemIndex < kDifficultyCount && itemIndex == difficulty_) ||\n"
    "                         (itemIndex == 3 && baseMode_);\n",
    "    const bool checked = (itemIndex < kDifficultyCount && itemIndex == difficulty_) ||\n"
    "                         (itemIndex == 3 && baseMode_) ||\n"
    "                         (itemIndex == 4 && realisticExplosions_);\n",
    "realistic checkbox state",
)
c = replace_once(c, "    if (itemIndex != 4 && itemIndex != 5) continue;\n",
                 "    if (itemIndex != 5 && itemIndex != 6) continue;\n", "action rows")
c = replace_once(c, "    if (itemIndex == 4 && !hasSavedGame_) {\n",
                 "    if (itemIndex == 5 && !hasSavedGame_) {\n", "disabled Continue")

old_action_loop = '''  for (int visible = 0; visible < drawnRows; ++visible) {\n    const int itemIndex = topIndex_ + visible;\n    if (itemIndex != 5 && itemIndex != 6) continue;\n    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;\n    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;\n    const int actionY = rowTop + actionInsetY;\n    const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);\n    renderer.drawRoundedRect(actionX, actionY, actionWidth, actionHeight, 1, 6, true);\n    if (itemIndex == 5 && !hasSavedGame_) {\n      for (int y = actionY; y < actionY + actionHeight; y += 2) {\n        renderer.fillRect(actionX, y, actionWidth, 1, false);\n      }\n    }\n  }\n'''
new_action_loop = '''  for (int visible = 0; visible < drawnRows; ++visible) {\n    const int itemIndex = topIndex_ + visible;\n    if (itemIndex != 5 && itemIndex != 6) continue;\n    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;\n    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;\n    const int actionY = rowTop + actionInsetY;\n    const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);\n    renderer.drawRoundedRect(actionX, actionY, actionWidth, actionHeight, 1, 6, true);\n    if (itemIndex == 5 && !hasSavedGame_) {\n      for (int y = actionY; y < actionY + actionHeight; y += 2)\n        renderer.fillRect(actionX, y, actionWidth, 1, false);\n    }\n\n    const char* actionLabel = itemIndex == 5 ? "Continuer" : "Nouvelle partie";\n    const char* actionValue = itemIndex == 5\n                                  ? (hasSavedGame_ ? continueValue_.data() : "Aucune partie")\n                                  : DIFFICULTY_LABELS[difficulty_];\n    const int textH = renderer.getLineHeight(UI_10_FONT_ID);\n    const int textY = actionY + std::max(0, (actionHeight - textH) / 2);\n    renderer.drawText(UI_10_FONT_ID, actionX + 10, textY, actionLabel);\n    if (actionValue && actionValue[0] != '\\0') {\n      const int valueW = renderer.getTextWidth(UI_10_FONT_ID, actionValue);\n      renderer.drawText(UI_10_FONT_ID, actionX + actionWidth - 10 - valueW, textY, actionValue);\n    }\n  }\n'''
c = replace_once(c, old_action_loop, new_action_loop, "vertically centered action text")

# ---------------------------------------------------------------------------
# Strict v3 save: add the Realistic Explosions flag. No legacy compatibility.
# ---------------------------------------------------------------------------
old_save = '''  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));\n  const uint8_t baseMode = baseMode_ ? 1 : 0;\n  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&\n            writeValue(file, wave_) && writeValue(file, score_) && writeValue(file, baseMode);\n  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();\n  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();\n  if (ok) ok = file.write(batteriesAlive_.data(), batteriesAlive_.size()) == batteriesAlive_.size();\n'''
new_save = '''  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));\n  const uint8_t baseMode = baseMode_ ? 1 : 0;\n  const uint8_t realisticExplosions = realisticExplosions_ ? 1 : 0;\n  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&\n            writeValue(file, wave_) && writeValue(file, score_) && writeValue(file, baseMode) &&\n            writeValue(file, realisticExplosions);\n  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();\n  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();\n  if (ok) ok = file.write(batteriesAlive_.data(), batteriesAlive_.size()) == batteriesAlive_.size();\n'''
c = replace_once(c, old_save, new_save, "save realistic setting")

c = replace_once(c, "  uint8_t baseMode = 0;\n  std::array<uint8_t, kCityCount> cities{};\n",
                 "  uint8_t baseMode = 0;\n  uint8_t realisticExplosions = 0;\n  std::array<uint8_t, kCityCount> cities{};\n",
                 "load realistic local")
c = replace_once(
    c,
    "  if (ok) ok = readValue(file, baseMode);\n"
    "  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());\n",
    "  if (ok) ok = readValue(file, baseMode);\n"
    "  if (ok) ok = readValue(file, realisticExplosions);\n"
    "  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());\n",
    "read realistic setting",
)
c = replace_once(
    c,
    "  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0 || baseMode > 1) {\n",
    "  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0 || baseMode > 1 ||\n"
    "      realisticExplosions > 1) {\n",
    "validate realistic setting",
)
c = replace_once(c, "  baseMode_ = baseMode != 0;\n  citiesAlive_ = cities;\n",
                 "  baseMode_ = baseMode != 0;\n  realisticExplosions_ = realisticExplosions != 0;\n  citiesAlive_ = cities;\n",
                 "restore realistic setting")

# ---------------------------------------------------------------------------
# Minesweeper-style score reset control. Fix the failed BaseMode6 approach by
# anchoring directly to the BaseMode5 score-table block rather than button-hint
# formatting that changes between UI patches.
# ---------------------------------------------------------------------------
c = replace_once(
    c,
    "constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;\n"
    "constexpr int MISSILE_SCORE_TABLE_GAP = 6;\n",
    "constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;\n"
    "constexpr int MISSILE_SCORE_TABLE_GAP = 6;\n"
    "constexpr int MISSILE_SCORE_RESET_GAP = 8;\n"
    "constexpr int MISSILE_SCORE_RESET_BUTTON_HEIGHT = 44;\n"
    "constexpr int MISSILE_SCORE_AREA_HEIGHT = MISSILE_SCORE_TABLE_HEIGHT + MISSILE_SCORE_TABLE_GAP +\n"
    "                                          MISSILE_SCORE_RESET_GAP + MISSILE_SCORE_RESET_BUTTON_HEIGHT;\n",
    "reset geometry constants",
)
c = replace_once(
    c,
    "                              metrics.verticalSpacing - MISSILE_SCORE_TABLE_HEIGHT - MISSILE_SCORE_TABLE_GAP)};\n",
    "                              metrics.verticalSpacing - MISSILE_SCORE_AREA_HEIGHT)};\n",
    "reserve score reset area",
)
score_rect = '''Rect missileScoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n  const auto& metrics = UITheme::getInstance().getMetrics();\n  const Rect list = menuRect(renderer, mappedInput);\n  return Rect{metrics.contentSidePadding, list.y + list.height + MISSILE_SCORE_TABLE_GAP,\n              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, MISSILE_SCORE_TABLE_HEIGHT};\n}\n'''
c = replace_once(
    c,
    score_rect,
    score_rect + '''\nRect missileScoreResetButtonRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n  const Rect table = missileScoreTableRect(renderer, mappedInput);\n  return Rect{table.x, table.y + table.height + MISSILE_SCORE_RESET_GAP, table.width,\n              MISSILE_SCORE_RESET_BUTTON_HEIGHT};\n}\n''',
    "score reset rect",
)

loop_start = c.find("void MissileCommandActivity::loopMenu() {")
if loop_start < 0:
    raise SystemExit("loopMenu not found")
ui_anchor = c.find("  if (uiReady_) {", loop_start)
if ui_anchor < 0:
    raise SystemExit("loopMenu ui routing anchor not found")
reset_handler = '''  int resetTapX = 0;\n  int resetTapY = 0;\n  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(resetTapX, resetTapY) &&\n      pointInRect(missileScoreResetButtonRect(renderer, mappedInput), resetTapX, resetTapY)) {\n    startActivityForResult(\n        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Réinitialiser les scores ?", ""),\n        [this](const ActivityResult& result) {\n          if (!result.isCancelled) {\n            highScores_.fill(0);\n            highScore_ = 0;\n            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);\n          }\n          requestUpdate();\n        });\n    return;\n  }\n\n'''
c = c[:ui_anchor] + reset_handler + c[ui_anchor:]

score_loop_end = '''    drawCenteredText(renderer, UI_10_FONT_ID,\n                     Rect{modeSplitX, rowY, scorePanel.x + scorePanel.width - modeSplitX, nextY - rowY}, scoreValue);\n  }\n'''
reset_draw = '''\n  const Rect resetButton = missileScoreResetButtonRect(renderer, mappedInput);\n  renderer.fillRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, false);\n  renderer.drawRoundedRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, 1, 6, true);\n  drawCenteredText(renderer, UI_10_FONT_ID, resetButton, "Reinitialiser les scores");\n'''
c = replace_once(c, score_loop_end, score_loop_end + reset_draw, "draw score reset button")

# Do not re-seed a freshly reset table merely by exiting from the menu. Scores
# are already persisted when returning from gameplay / finishing a game.
c = replace_once(c, "  saveHighScore();\n  releaseWindowShadow();\n  Activity::onExit();\n",
                 "  if (viewMode_ != ViewMode::Menu) saveHighScore();\n  releaseWindowShadow();\n  Activity::onExit();\n",
                 "preserve reset on menu exit")

# Distinct profiling/benchmark files for clean comparison.
c = c.replace("/missile-command-bm5-polyscores-bench.csv", "/missile-command-bm7-realistic-bench.csv")
c = c.replace("/missile-command-bm5-polyscores-trace.csv", "/missile-command-bm7-realistic-trace.csv")
c = c.replace("bm5-polyscores-started", "bm7-realistic-started")
c = c.replace("bm5-polyscores,%lu,%lu,%lu,%lu,%lu", "bm7-realistic,%lu,%lu,%lu,%lu,%lu")
c = c.replace("MISSILE-BM5-POLYSCORES", "MISSILE-BM7-REALISTIC")

CPP.write_text(c)
print("Missile BaseMode7: reset scores + Realistic Explosions shape morph/XY offsets applied")
