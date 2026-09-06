from pathlib import Path


def replace_one(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected source block not found in {path}")
    p.write_text(text.replace(old, new, 1))


# Keyboard: avoid a full e-ink redraw solely for transient touch highlight changes.
replace_one(
    "src/activities/util/KeyboardEntryActivity.cpp",
    "    if (result.activeChanged) {\n      requestUpdate();\n    }\n",
    "    // Do not refresh e-ink only for transient touch highlighting.\n"
    "    // The key event below performs the single useful redraw after text changes.\n",
)

# Predictive cache state.
replace_one(
    "src/activities/util/PredictiveText.h",
    "  std::vector<PersonalWord> personal_;\n  bool dirty_ = false;\n\n",
    "  std::vector<PersonalWord> personal_;\n"
    "  bool dirty_ = false;\n"
    "  uint32_t revision_ = 1;\n"
    "  mutable uint32_t cachedRevision_ = 0;\n"
    "  mutable std::string cachedKey_;\n"
    "  mutable std::array<std::string, 3> cachedSuggestions_{};\n\n",
)
replace_one(
    "src/activities/util/PredictiveText.h",
    "  void addPersonalWord(const std::string& word, uint16_t increment, bool allowBuiltin);\n",
    "  void addPersonalWord(const std::string& word, uint16_t increment, bool allowBuiltin);\n"
    "  void invalidateSuggestionCache();\n",
)

replace_one(
    "src/activities/util/PredictiveText.cpp",
    "bool asciiUpper(const unsigned char c) { return c >= 'A' && c <= 'Z'; }\n\n}  // namespace\n\n",
    "bool asciiUpper(const unsigned char c) { return c >= 'A' && c <= 'Z'; }\n\n"
    "char foldedInitial(const char* word) {\n"
    "  if (!word || !*word) return '\\0';\n"
    "  const unsigned char c = static_cast<unsigned char>(word[0]);\n"
    "  if (c < 0x80) {\n"
    "    char ch = static_cast<char>(c);\n"
    "    if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');\n"
    "    return ch;\n"
    "  }\n"
    "  if (c == 0xC3 && word[1]) {\n"
    "    switch (static_cast<unsigned char>(word[1])) {\n"
    "      case 0x80: case 0x81: case 0x82: case 0x83: case 0x84: case 0x85:\n"
    "      case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5: return 'a';\n"
    "      case 0x87: case 0xA7: return 'c';\n"
    "      case 0x88: case 0x89: case 0x8A: case 0x8B:\n"
    "      case 0xA8: case 0xA9: case 0xAA: case 0xAB: return 'e';\n"
    "      case 0x8C: case 0x8D: case 0x8E: case 0x8F:\n"
    "      case 0xAC: case 0xAD: case 0xAE: case 0xAF: return 'i';\n"
    "      case 0x92: case 0x93: case 0x94: case 0x95: case 0x96:\n"
    "      case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: return 'o';\n"
    "      case 0x99: case 0x9A: case 0x9B: case 0x9C:\n"
    "      case 0xB9: case 0xBA: case 0xBB: case 0xBC: return 'u';\n"
    "      case 0x9D: case 0xBD: case 0xBF: return 'y';\n"
    "      default: break;\n"
    "    }\n"
    "  }\n"
    "  return '\\0';\n"
    "}\n\n"
    "}  // namespace\n\n"
    "void PredictiveText::invalidateSuggestionCache() {\n"
    "  ++revision_;\n"
    "  if (revision_ == 0) revision_ = 1;\n"
    "  cachedRevision_ = 0;\n"
    "  cachedKey_.clear();\n"
    "  cachedSuggestions_ = {};\n"
    "}\n\n",
)
replace_one(
    "src/activities/util/PredictiveText.cpp",
    "        item.count = static_cast<uint16_t>(std::min<uint32_t>(next, 65535));\n        dirty_ = true;\n",
    "        item.count = static_cast<uint16_t>(std::min<uint32_t>(next, 65535));\n"
    "        dirty_ = true;\n"
    "        invalidateSuggestionCache();\n",
)
replace_one(
    "src/activities/util/PredictiveText.cpp",
    "  personal_.push_back(PersonalWord{normalized, static_cast<uint16_t>(std::max<uint16_t>(1, increment))});\n  dirty_ = true;\n",
    "  personal_.push_back(PersonalWord{normalized, static_cast<uint16_t>(std::max<uint16_t>(1, increment))});\n"
    "  dirty_ = true;\n"
    "  invalidateSuggestionCache();\n",
)
replace_one(
    "src/activities/util/PredictiveText.cpp",
    "void PredictiveText::load() {\n  personal_.clear();\n  dirty_ = false;\n",
    "void PredictiveText::load() {\n  personal_.clear();\n  dirty_ = false;\n  invalidateSuggestionCache();\n",
)

start = "std::array<std::string, 3> PredictiveText::suggestions(const std::string& text, const size_t cursorPos) const {"
end = "\nbool PredictiveText::applySuggestion("
p = Path("src/activities/util/PredictiveText.cpp")
text = p.read_text()
a = text.index(start)
b = text.index(end, a)
new_func = r'''std::array<std::string, 3> PredictiveText::suggestions(const std::string& text, const size_t cursorPos) const {
  std::array<std::string, 3> result{};
  size_t start = 0;
  size_t end = 0;
  currentWordRange(text, cursorPos, start, end);
  if (cursorPos <= start) return result;

  const std::string typed = normalizeWord(text.substr(start, cursorPos - start));
  const std::string foldedPrefix = foldForMatch(typed);
  if (foldedPrefix.size() < 2) return result;

  std::string cacheKey = foldedPrefix;
  cacheKey.push_back(!typed.empty() && asciiUpper(static_cast<unsigned char>(text[start])) ? 'U' : 'L');
  if (cachedRevision_ == revision_ && cachedKey_ == cacheKey) return cachedSuggestions_;

  std::vector<const PersonalWord*> matches;
  matches.reserve(personal_.size());
  for (const auto& item : personal_) {
    if (foldedInitial(item.word.c_str()) != foldedPrefix[0]) continue;
    const std::string foldedWord = foldForMatch(item.word);
    if (foldedWord.size() >= foldedPrefix.size() &&
        foldedWord.compare(0, foldedPrefix.size(), foldedPrefix) == 0 && foldedWord != foldedPrefix) {
      matches.push_back(&item);
    }
  }
  std::sort(matches.begin(), matches.end(), [](const PersonalWord* a, const PersonalWord* b) {
    if (a->count != b->count) return a->count > b->count;
    return a->word < b->word;
  });

  size_t slot = 0;
  auto add = [&](std::string candidate) {
    if (slot >= result.size()) return;
    const std::string foldedCandidate = foldForMatch(candidate);
    for (size_t i = 0; i < slot; ++i) {
      if (foldForMatch(result[i]) == foldedCandidate) return;
    }
    if (!typed.empty() && asciiUpper(static_cast<unsigned char>(text[start])) && !candidate.empty() &&
        candidate[0] >= 'a' && candidate[0] <= 'z') {
      candidate[0] = static_cast<char>(candidate[0] - 'a' + 'A');
    }
    result[slot++] = std::move(candidate);
  };

  for (const PersonalWord* item : matches) {
    add(item->word);
    if (slot >= result.size()) break;
  }
  for (size_t i = 0; i < kFrenchWordCount && slot < result.size(); ++i) {
    if (foldedInitial(kFrenchWords[i]) != foldedPrefix[0]) continue;
    const std::string word = kFrenchWords[i];
    const std::string foldedWord = foldForMatch(word);
    if (foldedWord.size() >= foldedPrefix.size() &&
        foldedWord.compare(0, foldedPrefix.size(), foldedPrefix) == 0 && foldedWord != foldedPrefix) {
      add(word);
    }
  }

  cachedKey_ = std::move(cacheKey);
  cachedSuggestions_ = result;
  cachedRevision_ = revision_;
  return cachedSuggestions_;
}
'''
p.write_text(text[:a] + new_func + text[b:])

# Minesweeper score area.
replace_one(
    "src/activities/home/MinesweeperActivity.cpp",
    "constexpr int BEST_SCORE_PANEL_HEIGHT = 184;\nconstexpr int SCORE_GRID_COUNT = 4;\n",
    "constexpr int SCORE_TABLE_HEIGHT = 152;\n"
    "constexpr int SCORE_RESET_GAP = 8;\n"
    "constexpr int SCORE_RESET_BUTTON_HEIGHT = 44;\n"
    "constexpr int SCORE_AREA_HEIGHT = SCORE_TABLE_HEIGHT + SCORE_RESET_GAP + SCORE_RESET_BUTTON_HEIGHT;\n"
    "constexpr int SCORE_GRID_COUNT = 4;\n",
)
replace_one(
    "src/activities/home/MinesweeperActivity.cpp",
    "              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing -\n                  BEST_SCORE_PANEL_HEIGHT};\n}\n\nRect headerRect",
    "              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing -\n"
    "                  SCORE_AREA_HEIGHT};\n"
    "}\n\n"
    "Rect scoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n"
    "  const auto& metrics = UITheme::getInstance().getMetrics();\n"
    "  const Rect list = menuListRect(renderer, mappedInput);\n"
    "  return Rect{metrics.contentSidePadding, list.y + list.height,\n"
    "              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, SCORE_TABLE_HEIGHT};\n"
    "}\n\n"
    "Rect scoreResetButtonRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n"
    "  const Rect table = scoreTableRect(renderer, mappedInput);\n"
    "  return Rect{table.x, table.y + table.height + SCORE_RESET_GAP, table.width, SCORE_RESET_BUTTON_HEIGHT};\n"
    "}\n\n"
    "Rect headerRect",
)
replace_one(
    "src/activities/home/MinesweeperActivity.cpp",
    "  if (uiReady_) {\n    const fui::InputSnapshot snap = touchSnapshotFrom(mappedInput);\n",
    "  int resetTapX = 0;\n"
    "  int resetTapY = 0;\n"
    "  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(resetTapX, resetTapY) &&\n"
    "      pointInRect(scoreResetButtonRect(renderer, mappedInput), resetTapX, resetTapY)) {\n"
    "    startActivityForResult(\n"
    "        std::make_unique<ConfirmationActivity>(renderer, mappedInput, \"Reinitialiser les scores\",\n"
    "                                               \"Effacer tous les meilleurs scores ?\"),\n"
    "        [this](const ActivityResult& result) {\n"
    "          if (!result.isCancelled) {\n"
    "            bestScores.fill(0);\n"
    "            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);\n"
    "          }\n"
    "          requestUpdate();\n"
    "        });\n"
    "    return;\n"
    "  }\n\n"
    "  if (uiReady_) {\n"
    "    const fui::InputSnapshot snap = touchSnapshotFrom(mappedInput);\n",
)

p = Path("src/activities/home/MinesweeperActivity.cpp")
text = p.read_text()
start = "  const auto& metrics = UITheme::getInstance().getMetrics();\n  const Rect listBounds = menuListRect(renderer, mappedInput);"
end = "\n  const auto labels =\n      mappedInput.mapLabels"
a = text.index(start, text.index("void MinesweeperActivity::renderMenu()"))
b = text.index(end, a)
new_render = r'''  const Rect scorePanel = scoreTableRect(renderer, mappedInput);
  renderer.fillRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, false);
  renderer.drawRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, 1, true);
  const int headerRowHeight = 28;
  const int dataTop = scorePanel.y + headerRowHeight;
  const int dataHeight = scorePanel.height - headerRowHeight;
  const int splitX = scorePanel.x + scorePanel.width * 2 / 5;

  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);
  renderer.drawLine(splitX, scorePanel.y, splitX, scorePanel.y + scorePanel.height, 1, true);

  auto drawCenteredCellText = [this](const int fontId, const Rect& cell, const char* text) {
    const int textWidth = renderer.getTextWidth(fontId, text);
    const int textHeight = renderer.getLineHeight(fontId);
    renderer.drawText(fontId, cell.x + std::max(0, (cell.width - textWidth) / 2),
                      cell.y + std::max(0, (cell.height - textHeight) / 2) + 1, text);
  };

  const Rect gridHeader{scorePanel.x, scorePanel.y, splitX - scorePanel.x, headerRowHeight};
  const Rect bestHeader{splitX, scorePanel.y, scorePanel.x + scorePanel.width - splitX, headerRowHeight};
  drawCenteredCellText(UI_10_FONT_ID, gridHeader, "GRILLE");
  drawCenteredCellText(UI_10_FONT_ID, bestHeader, "MEILLEUR SCORE");

  constexpr const char* SCORE_GRID_LABELS[SCORE_GRID_COUNT] = {"5 x 5", "9 x 9", "12 x 12", "16 x 16"};
  for (int row = 0; row < SCORE_GRID_COUNT; ++row) {
    const int rowY = dataTop + dataHeight * row / SCORE_GRID_COUNT;
    const int nextRowY = dataTop + dataHeight * (row + 1) / SCORE_GRID_COUNT;
    const int rowHeight = nextRowY - rowY;
    if (row > 0) renderer.drawLine(scorePanel.x, rowY, scorePanel.x + scorePanel.width, rowY, 1, true);

    const Rect gridCell{scorePanel.x, rowY, splitX - scorePanel.x, rowHeight};
    const Rect bestCell{splitX, rowY, scorePanel.x + scorePanel.width - splitX, rowHeight};
    char scoreValue[16];
    std::snprintf(scoreValue, sizeof(scoreValue), "%03u", static_cast<unsigned>(bestScores[row]));
    drawCenteredCellText(UI_10_FONT_ID, gridCell, SCORE_GRID_LABELS[row]);
    drawCenteredCellText(UI_10_FONT_ID, bestCell, scoreValue);
  }

  const Rect resetButton = scoreResetButtonRect(renderer, mappedInput);
  renderer.fillRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, false);
  renderer.drawRoundedRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, 1, 6, true);
  drawCenteredCellText(UI_10_FONT_ID, resetButton, "Reinitialiser les scores");
'''
p.write_text(text[:a] + new_render + text[b:])

for path, needles in {
    "src/activities/util/KeyboardEntryActivity.cpp": ["Do not refresh e-ink only for transient touch highlighting"],
    "src/activities/util/PredictiveText.cpp": ["foldedInitial", "cachedSuggestions_"],
    "src/activities/home/MinesweeperActivity.cpp": ["Reinitialiser les scores", "SCORE_AREA_HEIGHT"],
}.items():
    text = Path(path).read_text()
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"sanity check failed: {needle} missing from {path}")
