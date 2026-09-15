from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:260]!r}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Header: six independent records = 3 difficulties x 2 gameplay modes.
# Keep highScore_ as the hot-path mirror used by the existing HUD, while the
# complete table is persisted separately and rendered only in the menu.
# ---------------------------------------------------------------------------
h = HDR.read_text()
h = replace_once(
    h,
    "  static constexpr int kDifficultyCount = 3;\n",
    "  static constexpr int kDifficultyCount = 3;\n"
    "  static constexpr int kScoreSlotCount = kDifficultyCount * 2;\n",
    "score slot count",
)
h = replace_once(
    h,
    "  uint32_t score_ = 0;\n  uint32_t highScore_ = 0;\n",
    "  uint32_t score_ = 0;\n"
    "  std::array<uint32_t, kScoreSlotCount> highScores_{};\n"
    "  uint32_t highScore_ = 0;\n",
    "score state",
)
h = replace_once(
    h,
    "  int nearestBatteryForX(int x) const;\n\n"
    "  bool loadSavedGame();\n",
    "  int nearestBatteryForX(int x) const;\n"
    "  int scoreSlot() const;\n"
    "  void syncCurrentHighScore();\n\n"
    "  bool loadSavedGame();\n",
    "score helpers declarations",
)
HDR.write_text(h)

c = CPP.read_text()

# ---------------------------------------------------------------------------
# Explosion renderer: regular convex polygons only. Each explosion randomly
# chooses a pentagon, hexagon or octagon, a start orientation and a rotation
# direction. Geometry for every radius/orientation/shape is still precomputed at
# load/wave setup; recurrent frames only index the cache and draw the edges.
# ---------------------------------------------------------------------------
old_cache_decl = '''constexpr uint8_t EXP_ROT_COUNT = 8;\nconstexpr uint32_t EXP_ROT_STEP_US = 120000;\nconstexpr uint8_t EXP_VERTS = 8;\nstruct ExpPt { int8_t x; int8_t y; };\nusing ExpContour = std::array<ExpPt, EXP_VERTS>;\nstd::array<std::array<ExpContour, EXPLOSION_MAX_RADIUS + 1>, EXP_ROT_COUNT> expCache{};\nbool expCacheReady = false;\n'''
new_cache_decl = '''constexpr uint8_t EXP_ROT_COUNT = 8;\nconstexpr uint8_t EXP_SHAPE_COUNT = 3;\nconstexpr uint8_t EXP_VERTS = 8;\nconstexpr uint32_t EXP_ROT_STEP_US = 120000;\nstruct ExpPt { int8_t x = 0; int8_t y = 0; };\nstruct ExpContour {\n  std::array<ExpPt, EXP_VERTS> points{};\n  uint8_t count = 0;\n};\nstd::array<std::array<std::array<ExpContour, EXPLOSION_MAX_RADIUS + 1>, EXP_ROT_COUNT>, EXP_SHAPE_COUNT>\n    expCache{};\nbool expCacheReady = false;\n'''
c = replace_once(c, old_cache_decl, new_cache_decl, "polygon cache declaration")

old_prepare = r'''void prepareExplosionCache(bool rebuild = false) {
  if (expCacheReady && !rebuild) return;
  constexpr int16_t cq[32] = {1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200,0,200,392,569,724,851,946,1004};
  constexpr int16_t sq[32] = {0,200,392,569,724,851,946,1004,1024,1004,946,851,724,569,392,200,0,-200,-392,-569,-724,-851,-946,-1004,-1024,-1004,-946,-851,-724,-569,-392,-200};
  // Deliberately asymmetric radial profile. The longest spike still reaches the
  // accepted Explosion2 radius, so the overall explosion size is not reduced.
  constexpr uint16_t radialQ10[EXP_VERTS] = {1024, 540, 900, 620, 980, 500, 860, 680};
  const auto q10 = [](int32_t v) { return static_cast<int8_t>((v >= 0 ? v + 512 : v - 512) / 1024); };
  for (uint8_t rot = 0; rot < EXP_ROT_COUNT; ++rot) {
    for (int radius = EXPLOSION_MIN_RADIUS; radius <= EXPLOSION_MAX_RADIUS; ++radius) {
      for (uint8_t v = 0; v < EXP_VERTS; ++v) {
        // 32-entry table = 11.25 degrees. rot*4 therefore advances by a very
        // visible 45 degrees, not the subtle BaseMode3 11.25-degree offset.
        const uint8_t a = static_cast<uint8_t>(((rot * 4) + v * 4) & 31);
        const int32_t scaledRadius =
            (static_cast<int32_t>(radius) * radialQ10[v] + 512) / 1024;
        expCache[rot][radius][v] = {q10(scaledRadius * cq[a]), q10(scaledRadius * sq[a])};
      }
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
'''
new_prepare = r'''void prepareExplosionCache(bool rebuild = false) {
  if (expCacheReady && !rebuild) return;

  // Q10 unit vectors for regular pentagon / hexagon / octagon vertices.
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
  expCacheReady = true;
}

uint8_t explosionRotationIndex(uint32_t ageUs, uint8_t seed) {
  const uint8_t start = static_cast<uint8_t>(seed & 0x07u);
  const uint8_t step = static_cast<uint8_t>((ageUs / EXP_ROT_STEP_US) & 0x07u);
  if ((seed & 0x08u) != 0)
    return static_cast<uint8_t>((start + EXP_ROT_COUNT - step) & 0x07u);
  return static_cast<uint8_t>((start + step) & 0x07u);
}

uint8_t explosionShapeIndex(uint8_t seed) {
  return static_cast<uint8_t>((seed >> 4) % EXP_SHAPE_COUNT);
}
'''
c = replace_once(c, old_prepare, new_prepare, "regular polygon cache")

c = replace_once(
    c,
    "void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius, uint8_t rot) {\n",
    "void drawExplosionClipped(GfxRenderer& renderer, const Rect& clip, int x, int y, int radius, uint8_t rot, uint8_t shape) {\n",
    "polygon draw signature",
)
c = replace_once(
    c,
    '''  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);\n  const ExpContour& c = expCache[rot % EXP_ROT_COUNT][cr];\n  for (uint8_t i = 0; i < EXP_VERTS; ++i) {\n    const ExpPt& a = c[i];\n    const ExpPt& b = c[(i + 1) & 7];\n    drawClippedLine1px(renderer, clip, x + a.x, y + a.y, x + b.x, y + b.y);\n  }\n''',
    '''  const int cr = std::clamp(radius, EXPLOSION_MIN_RADIUS, EXPLOSION_MAX_RADIUS);\n  const ExpContour& contour = expCache[shape % EXP_SHAPE_COUNT][rot % EXP_ROT_COUNT][cr];\n  for (uint8_t i = 0; i < contour.count; ++i) {\n    const ExpPt& a = contour.points[i];\n    const ExpPt& b = contour.points[(i + 1) % contour.count];\n    drawClippedLine1px(renderer, clip, x + a.x, y + a.y, x + b.x, y + b.y);\n  }\n''',
    "polygon draw body",
)
c = replace_once(
    c,
    '''    const uint32_t explosionRnd = esp_random();\n    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3));\n    explosion.phaseElapsedUs = 0;\n''',
    '''    const uint32_t explosionRnd = esp_random();\n    const uint8_t shape = static_cast<uint8_t>((explosionRnd >> 4) % EXP_SHAPE_COUNT);\n    explosion.phase = static_cast<uint8_t>((explosionRnd & 0x07u) | (((explosionRnd >> 3) & 0x01u) << 3) |\n                                           (shape << 4));\n    explosion.phaseElapsedUs = 0;\n''',
    "random polygon shape",
)
c = replace_once(
    c,
    '''drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs),\n                           explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase));''',
    '''drawExplosionClipped(renderer, explosionClip, explosion.x, explosion.y, explosionRadius(explosion.phaseElapsedUs),\n                           explosionRotationIndex(explosion.phaseElapsedUs, explosion.phase),\n                           explosionShapeIndex(explosion.phase));''',
    "polygon draw call",
)

# ---------------------------------------------------------------------------
# Mode/difficulty records and Minesweeper-style menu table.
# No legacy score-file compatibility: v1 single-record files are rejected and a
# clean six-slot v2 table starts from zero, matching the development policy.
# ---------------------------------------------------------------------------
c = replace_once(c, "constexpr uint8_t SCORE_VERSION = 1;\n", "constexpr uint8_t SCORE_VERSION = 2;\n", "score version")

old_menu_rect = r'''Rect menuRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + metrics.verticalSpacing;
  return Rect{0, top, renderer.getScreenWidth(),
              renderer.getScreenHeight() - top - metrics.buttonHintsHeight - metrics.verticalSpacing};
}
'''
new_menu_rect = r'''constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;
constexpr int MISSILE_SCORE_TABLE_GAP = 6;

Rect menuRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + metrics.verticalSpacing;
  return Rect{0, top, renderer.getScreenWidth(),
              std::max(1, renderer.getScreenHeight() - top - metrics.buttonHintsHeight -
                              metrics.verticalSpacing - MISSILE_SCORE_TABLE_HEIGHT - MISSILE_SCORE_TABLE_GAP)};
}

Rect missileScoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect list = menuRect(renderer, mappedInput);
  return Rect{metrics.contentSidePadding, list.y + list.height + MISSILE_SCORE_TABLE_GAP,
              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, MISSILE_SCORE_TABLE_HEIGHT};
}
'''
c = replace_once(c, old_menu_rect, new_menu_rect, "menu score area")

old_score_io = r'''bool MissileCommandActivity::loadHighScore() {
  highScore_ = 0;
  if (!Storage.exists(SCORE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MISSILE", SCORE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint32_t score = 0;
  const bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, score);
  file.close();
  if (!ok || magic != SCORE_MAGIC || version != SCORE_VERSION) return false;
  highScore_ = score;
  return true;
}

bool MissileCommandActivity::saveHighScore() {
  if (score_ > highScore_) highScore_ = score_;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE", SCORE_PATH, file)) return false;
  const bool ok = writeValue(file, SCORE_MAGIC) && writeValue(file, SCORE_VERSION) && writeValue(file, highScore_);
  file.close();
  return ok;
}
'''
new_score_io = r'''int MissileCommandActivity::scoreSlot() const {
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
'''
c = replace_once(c, old_score_io, new_score_io, "six-slot score IO")

c = replace_once(
    c,
    "  hasSavedGame_ = loadSavedGame();\n  selectedIndex_ = difficulty_;\n",
    "  hasSavedGame_ = loadSavedGame();\n  syncCurrentHighScore();\n  selectedIndex_ = difficulty_;\n",
    "score sync after saved settings",
)
c = replace_once(
    c,
    '''  if (row >= 0 && row < kDifficultyCount) {\n    difficulty_ = row;\n    selectedIndex_ = row;\n    requestUpdate();\n    return;\n  }\n''',
    '''  if (row >= 0 && row < kDifficultyCount) {\n    difficulty_ = row;\n    selectedIndex_ = row;\n    syncCurrentHighScore();\n    requestUpdate();\n    return;\n  }\n''',
    "difficulty record sync",
)
c = replace_once(
    c,
    '''  if (row == 3) {\n    baseMode_ = !baseMode_;\n    requestUpdate();\n    return;\n  }\n''',
    '''  if (row == 3) {\n    baseMode_ = !baseMode_;\n    syncCurrentHighScore();\n    requestUpdate();\n    return;\n  }\n''',
    "mode record sync",
)
c = replace_once(
    c,
    "void MissileCommandActivity::newGame() {\n  clearSavedGame();\n",
    "void MissileCommandActivity::newGame() {\n  syncCurrentHighScore();\n  clearSavedGame();\n",
    "new game record sync",
)
c = replace_once(
    c,
    "void MissileCommandActivity::continueGame() {\n  waveScrubPending_ = false;\n",
    "void MissileCommandActivity::continueGame() {\n  syncCurrentHighScore();\n  waveScrubPending_ = false;\n",
    "continue record sync",
)
c = replace_once(
    c,
    "void MissileCommandActivity::returnToMenu() {\n  if (aliveCityCount() > 0) saveGame();\n  viewMode_ = ViewMode::Menu;\n",
    "void MissileCommandActivity::returnToMenu() {\n  if (aliveCityCount() > 0) saveGame();\n  saveHighScore();\n  viewMode_ = ViewMode::Menu;\n",
    "menu score persistence",
)

old_record = r'''  char record[48];
  std::snprintf(record, sizeof(record), "Meilleur score : %lu", static_cast<unsigned long>(highScore_));
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  drawCenteredText(renderer, UI_10_FONT_ID,
                   Rect{metrics.contentSidePadding, std::max(listBounds.y, footerTop - 34),
                        renderer.getScreenWidth() - 2 * metrics.contentSidePadding, 28}, record);
'''
new_record = r'''  // Minesweeper-style score panel: rows are difficulty, columns are game mode.
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
'''
c = replace_once(c, old_record, new_record, "menu score table")

# Distinct PROFILE1/summary identity for this visual+menu candidate.
c = c.replace("/missile-command-bm4-rotanim-bench.csv", "/missile-command-bm5-polyscores-bench.csv")
c = c.replace("/missile-command-bm4-rotanim-trace.csv", "/missile-command-bm5-polyscores-trace.csv")
c = c.replace("bm4-rotanim-started", "bm5-polyscores-started")
c = c.replace("bm4-rotanim,%lu,%lu,%lu,%lu,%lu", "bm5-polyscores,%lu,%lu,%lu,%lu,%lu")
c = c.replace("MISSILE-BM4-ROTANIM", "MISSILE-BM5-POLYSCORES")

CPP.write_text(c)
print("Missile BaseMode5: regular rotating pentagon/hexagon/octagon explosions + 6-record menu table applied")
