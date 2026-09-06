from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"missing replacement: {label}")
    return text.replace(old, new, 1)


def replace_span(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"missing start marker: {label}")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"missing end marker: {label}")
    return text[:start] + replacement + text[end:]


# Notes: filtered results become compact indices and content search streams from SD.
header = Path("src/activities/home/NotesActivity.h")
text = header.read_text()
text = replace_once(text, "#include <string>\n#include <vector>\n", "#include <cstddef>\n#include <string>\n#include <vector>\n", "notes cstddef")
text = replace_once(text, "  std::vector<std::string> filteredNotes;\n", "  std::vector<size_t> filteredNotes;\n", "notes filtered indices")
text = replace_once(text, "  bool loadNote(const std::string& path, std::string& text) const;\n", "  bool loadNote(const std::string& path, std::string& text) const;\n  bool noteContains(const std::string& path, const std::string& needle) const;\n", "notes noteContains decl")
header.write_text(text)

notes = Path("src/activities/home/NotesActivity.cpp")
text = notes.read_text()
text = replace_once(text, "#include <algorithm>\n#include <cctype>\n", "#include <algorithm>\n#include <array>\n#include <cctype>\n", "notes array include")

apply_filter = r'''void NotesActivity::applyFilter() {
  filteredNotes.clear();
  filteredNotes.reserve(notes.size());
  if (searchQuery.empty()) {
    for (size_t i = 0; i < notes.size(); ++i) filteredNotes.push_back(i);
  } else {
    const std::string needle = lowerAscii(searchQuery);
    for (size_t i = 0; i < notes.size(); ++i) {
      const auto& filename = notes[i];
      bool matches = lowerAscii(displayName(filename)).find(needle) != std::string::npos;
      if (!matches) matches = noteContains(std::string(kNotesDir) + "/" + filename, needle);
      if (matches) filteredNotes.push_back(i);
    }
  }

  if (filteredNotes.empty()) {
    selectorIndex = 0;
    topIndex = 0;
  } else {
    selectorIndex = std::clamp(selectorIndex, 0, static_cast<int>(filteredNotes.size()) - 1);
    topIndex = std::clamp(topIndex, 0, selectorIndex);
  }
}

'''
text = replace_span(text, "void NotesActivity::applyFilter() {", "std::string NotesActivity::displayName", apply_filter, "notes filter")

search_method = r'''bool NotesActivity::noteContains(const std::string& path, const std::string& needle) const {
  if (needle.empty()) return true;
  constexpr size_t kSearchBufferSize = 512;
  constexpr size_t kMaxSearchBytes = 80;
  if (needle.size() > kMaxSearchBytes) return false;

  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  if (file.size() > kMaxNoteBytes) {
    file.close();
    return false;
  }

  const auto foldByte = [](const unsigned char c) {
    return static_cast<unsigned char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
  };

  std::array<uint8_t, kMaxSearchBytes> prefix{};
  for (size_t i = 1, matched = 0; i < needle.size(); ++i) {
    const unsigned char current = foldByte(static_cast<unsigned char>(needle[i]));
    while (matched > 0 && current != foldByte(static_cast<unsigned char>(needle[matched]))) matched = prefix[matched - 1];
    if (current == foldByte(static_cast<unsigned char>(needle[matched]))) ++matched;
    prefix[i] = static_cast<uint8_t>(matched);
  }

  std::array<uint8_t, kSearchBufferSize> buffer{};
  size_t matched = 0;
  while (true) {
    const int count = file.read(buffer.data(), buffer.size());
    if (count <= 0) break;
    for (int i = 0; i < count; ++i) {
      const unsigned char current = foldByte(buffer[static_cast<size_t>(i)]);
      while (matched > 0 && current != foldByte(static_cast<unsigned char>(needle[matched]))) matched = prefix[matched - 1];
      if (current == foldByte(static_cast<unsigned char>(needle[matched]))) ++matched;
      if (matched == needle.size()) {
        file.close();
        return true;
      }
    }
  }
  file.close();
  return false;
}

'''
marker = "bool NotesActivity::saveNote(const std::string& path, const std::string& text) const {"
pos = text.find(marker)
if pos < 0:
    raise SystemExit("missing notes noteContains insertion point")
text = text[:pos] + search_method + text[pos:]
text = text.replace("const std::string filename = filteredNotes[static_cast<size_t>(index)];", "const std::string& filename = notes[filteredNotes[static_cast<size_t>(index)]];")
text = replace_once(text, "displayName(filteredNotes[index]).c_str(),", "displayName(notes[filteredNotes[static_cast<size_t>(index)]]).c_str(),", "notes render index")
notes.write_text(text)

# Minesweeper: compact undo state, deferred score writes, fixed menu storage, cached geometry.
mine = Path("src/activities/home/MinesweeperActivity.cpp")
text = mine.read_text()
text = replace_once(text, "#include <memory>\n#include <vector>\n", "#include <memory>\n", "mine vector include")
old_undo = r'''constexpr int UNDO_MAX_CELLS = 16 * 16;
constexpr int64_t LOSS_UNDO_WINDOW_US = 5LL * 1000LL * 1000LL;
constexpr int SCORE_TABLE_HEIGHT = 152;
constexpr int SCORE_RESET_GAP = 8;
constexpr int SCORE_RESET_BUTTON_HEIGHT = 44;
constexpr int SCORE_AREA_HEIGHT = SCORE_TABLE_HEIGHT + SCORE_RESET_GAP + SCORE_RESET_BUTTON_HEIGHT;
constexpr int SCORE_GRID_COUNT = 4;

std::array<uint8_t, UNDO_MAX_CELLS> undoMines{};
std::array<uint8_t, UNDO_MAX_CELLS> undoRevealed{};
std::array<uint8_t, UNDO_MAX_CELLS> undoFlagged{};
bool undoAvailable = false;
bool undoMinesPlaced = false;
int undoRevealedSafeCells = 0;
int undoSelectedCellIndex = 0;
int64_t lossUndoDeadlineUs = 0;
'''
new_undo = r'''constexpr int64_t LOSS_UNDO_WINDOW_US = 5LL * 1000LL * 1000LL;
constexpr int SCORE_TABLE_HEIGHT = 152;
constexpr int SCORE_RESET_GAP = 8;
constexpr int SCORE_RESET_BUTTON_HEIGHT = 44;
constexpr int SCORE_AREA_HEIGHT = SCORE_TABLE_HEIGHT + SCORE_RESET_GAP + SCORE_RESET_BUTTON_HEIGHT;
constexpr int SCORE_GRID_COUNT = 4;

bool undoAvailable = false;
int undoMineIndex = -1;
int64_t lossUndoDeadlineUs = 0;
'''
text = replace_once(text, old_undo, new_undo, "mine undo globals")
text = replace_once(text, "std::array<uint16_t, SCORE_GRID_COUNT> bestScores{};\n", "std::array<uint16_t, SCORE_GRID_COUNT> bestScores{};\nbool scoresDirty = false;\n", "mine dirty scores")
text = replace_once(text, "bool loadBestScores() {\n  bestScores.fill(0);\n", "bool loadBestScores() {\n  bestScores.fill(0);\n  scoresDirty = false;\n", "mine load dirty")

score_funcs = r'''bool saveBestScores() {
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MINE", SCORE_PATH, file)) return false;
  const uint8_t count = SCORE_GRID_COUNT;
  bool ok = writeValue(file, SCORE_MAGIC) && writeValue(file, SCORE_VERSION) && writeValue(file, count);
  for (int i = 0; i < SCORE_GRID_COUNT && ok; ++i) ok = writeValue(file, bestScores[i]);
  file.close();
  if (ok) scoresDirty = false;
  return ok;
}

void flushBestScores() {
  if (!scoresDirty) return;
  if (!saveBestScores()) LOG_ERR("MINE", "Failed to save best scores");
}

void updateBestScore(const int gridIndex, const int score) {
  if (gridIndex < 0 || gridIndex >= SCORE_GRID_COUNT || score < 0) return;
  const uint16_t bounded = static_cast<uint16_t>(std::min(score, 0xFFFF));
  if (bounded <= bestScores[gridIndex]) return;
  bestScores[gridIndex] = bounded;
  scoresDirty = true;
}

'''
text = replace_span(text, "bool saveBestScores() {", "void drawHiddenCellPattern", score_funcs, "mine score funcs")
text = replace_once(text, "  undoAvailable = false;\n  lossUndoDeadlineUs = 0;\n  assistedCounterChoice = false;", "  undoAvailable = false;\n  undoMineIndex = -1;\n  lossUndoDeadlineUs = 0;\n  assistedCounterChoice = false;", "mine onEnter undo")

on_exit = r'''void MinesweeperActivity::onExit() {
  if (viewMode_ == ViewMode::Grid && !gameOver_) saveGame();
  flushBestScores();
  Activity::onExit();
}

'''
text = replace_span(text, "void MinesweeperActivity::onExit() {", "void MinesweeperActivity::loop() {", on_exit, "mine onExit")
text = replace_once(text, "            bestScores.fill(0);\n            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);", "            bestScores.fill(0);\n            scoresDirty = false;\n            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);", "mine reset scores")
text = replace_once(text, "    undoAvailable = false;\n    lossUndoDeadlineUs = 0;\n    for (int i = 0; i < totalCells(); ++i) revealed_[i] = 1;", "    undoAvailable = false;\n    undoMineIndex = -1;\n    lossUndoDeadlineUs = 0;\n    for (int i = 0; i < totalCells(); ++i) revealed_[i] = 1;", "mine undo timeout")

old_loss = r'''  const auto undoLoss = [this]() {
    if (won_ || !undoAvailable) return;
    if (lossUndoDeadlineUs > 0 && esp_timer_get_time() >= lossUndoDeadlineUs) return;
    if (!scoreFrozen) {
      scoreFrozen = true;
      officialScore = undoRevealedSafeCells;
      updateBestScore(gridSizeIndex_, officialScore);
    }
    mines_ = undoMines;
    revealed_ = undoRevealed;
    flagged_ = undoFlagged;
    minesPlaced_ = undoMinesPlaced;
    revealedSafeCells_ = undoRevealedSafeCells;
    selectedCellIndex_ = undoSelectedCellIndex;
    gameOver_ = false;
    won_ = false;
    viewMode_ = ViewMode::Grid;
    undoAvailable = false;
    lossUndoDeadlineUs = 0;
    saveGame();
    requestUpdate();
  };
'''
new_loss = r'''  const auto undoLoss = [this]() {
    if (won_ || !undoAvailable) return;
    if (lossUndoDeadlineUs > 0 && esp_timer_get_time() >= lossUndoDeadlineUs) return;
    if (!scoreFrozen) {
      scoreFrozen = true;
      officialScore = revealedSafeCells_;
      updateBestScore(gridSizeIndex_, officialScore);
    }
    if (undoMineIndex >= 0 && undoMineIndex < totalCells()) revealed_[undoMineIndex] = 0;
    gameOver_ = false;
    won_ = false;
    viewMode_ = ViewMode::Grid;
    undoAvailable = false;
    undoMineIndex = -1;
    lossUndoDeadlineUs = 0;
    saveGame();
    requestUpdate();
  };
'''
text = replace_once(text, old_loss, new_loss, "mine undo action")

return_menu = r'''void MinesweeperActivity::returnToMenu() {
  if (!gameOver_) saveGame();
  flushBestScores();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  confirmHoldHandled_ = false;
  undoAvailable = false;
  undoMineIndex = -1;
  lossUndoDeadlineUs = 0;
  requestUpdate();
}

'''
text = replace_span(text, "void MinesweeperActivity::returnToMenu() {", "int MinesweeperActivity::gridDimension() const {", return_menu, "mine return menu")

adjacent = r'''int MinesweeperActivity::adjacentMineCount(const int index) const {
  const int dimension = gridDimension();
  const int row = index / dimension;
  const int col = index % dimension;
  int count = 0;
  for (int dr = -1; dr <= 1; ++dr) {
    for (int dc = -1; dc <= 1; ++dc) {
      if (dr == 0 && dc == 0) continue;
      const int nr = row + dr;
      const int nc = col + dc;
      if (nr >= 0 && nr < dimension && nc >= 0 && nc < dimension && mines_[nr * dimension + nc]) ++count;
    }
  }
  return count;
}

'''
text = replace_span(text, "int MinesweeperActivity::adjacentMineCount(const int index) const {", "void MinesweeperActivity::resetGame() {", adjacent, "mine adjacent")
text = replace_once(text, "  undoAvailable = false;\n  lossUndoDeadlineUs = 0;\n}\n\nvoid MinesweeperActivity::placeMines", "  undoAvailable = false;\n  undoMineIndex = -1;\n  lossUndoDeadlineUs = 0;\n}\n\nvoid MinesweeperActivity::placeMines", "mine reset undo")

place = r'''void MinesweeperActivity::placeMines(const int firstIndex) {
  mines_.fill(0);
  const int dimension = gridDimension();
  const int cellCount = dimension * dimension;
  const int firstRow = firstIndex / dimension;
  const int firstCol = firstIndex % dimension;
  const int wanted = mineCount();
  int placed = 0;

  while (placed < wanted) {
    const int index = static_cast<int>(esp_random() % static_cast<uint32_t>(cellCount));
    if (mines_[index]) continue;
    const int row = index / dimension;
    const int col = index % dimension;
    if (std::abs(row - firstRow) <= 1 && std::abs(col - firstCol) <= 1) continue;
    mines_[index] = 1;
    ++placed;
  }
  minesPlaced_ = true;
}

'''
text = replace_span(text, "void MinesweeperActivity::placeMines(const int firstIndex) {", "void MinesweeperActivity::revealCell", place, "mine place")

reveal = r'''void MinesweeperActivity::revealCell(const int index) {
  if (gameOver_ || index < 0 || index >= totalCells() || flagged_[index] || revealed_[index]) return;

  if (!minesPlaced_) placeMines(index);
  if (mines_[index]) {
    undoAvailable = true;
    undoMineIndex = index;
    revealed_[index] = 1;
    finishGame(false);
    return;
  }
  revealFlood(index);
  if (!scoreFrozen) {
    officialScore = revealedSafeCells_;
    updateBestScore(gridSizeIndex_, officialScore);
  }
  checkWin();
}

'''
text = replace_span(text, "void MinesweeperActivity::revealCell(const int index) {", "void MinesweeperActivity::revealFlood", reveal, "mine reveal")

flood = r'''void MinesweeperActivity::revealFlood(const int startIndex) {
  std::array<int16_t, kMaxCells> queue{};
  const int dimension = gridDimension();
  const int cellCount = dimension * dimension;
  int head = 0;
  int tail = 0;
  queue[tail++] = static_cast<int16_t>(startIndex);

  while (head < tail) {
    const int index = queue[head++];
    if (index < 0 || index >= cellCount || revealed_[index] || flagged_[index] || mines_[index]) continue;
    revealed_[index] = 1;
    ++revealedSafeCells_;
    if (adjacentMineCount(index) != 0) continue;

    const int row = index / dimension;
    const int col = index % dimension;
    for (int dr = -1; dr <= 1; ++dr) {
      for (int dc = -1; dc <= 1; ++dc) {
        if (dr == 0 && dc == 0) continue;
        const int nr = row + dr;
        const int nc = col + dc;
        if (nr < 0 || nr >= dimension || nc < 0 || nc >= dimension) continue;
        const int next = nr * dimension + nc;
        if (!revealed_[next] && !flagged_[next] && !mines_[next] && tail < kMaxCells) queue[tail++] = static_cast<int16_t>(next);
      }
    }
  }
}

'''
text = replace_span(text, "void MinesweeperActivity::revealFlood(const int startIndex) {", "void MinesweeperActivity::toggleFlag", flood, "mine flood")

toggle = r'''void MinesweeperActivity::toggleFlag(const int index) {
  if (gameOver_ || index < 0 || index >= totalCells() || revealed_[index]) return;
  flagged_[index] = flagged_[index] ? 0 : 1;
  saveGame();
  flushBestScores();
}

'''
text = replace_span(text, "void MinesweeperActivity::toggleFlag(const int index) {", "void MinesweeperActivity::checkWin()", toggle, "mine flag")

finish = r'''void MinesweeperActivity::finishGame(const bool won) {
  gameOver_ = true;
  won_ = won;

  if (won) {
    undoAvailable = false;
    undoMineIndex = -1;
    lossUndoDeadlineUs = 0;
    for (int i = 0; i < totalCells(); ++i) {
      revealed_[i] = 1;
      if (mines_[i]) flagged_[i] = 1;
    }
  } else {
    lossUndoDeadlineUs = 0;
  }

  flushBestScores();
  clearSavedGame();
  viewMode_ = ViewMode::Result;
  requestUpdate();
}

'''
text = replace_span(text, "void MinesweeperActivity::finishGame(const bool won) {", "bool MinesweeperActivity::saveGame() {", finish, "mine finish")
text = replace_once(text, "bool MinesweeperActivity::loadSavedGame() {\n  undoAvailable = false;\n  lossUndoDeadlineUs = 0;", "bool MinesweeperActivity::loadSavedGame() {\n  undoAvailable = false;\n  undoMineIndex = -1;\n  lossUndoDeadlineUs = 0;", "mine load undo")

menu = r'''void MinesweeperActivity::buildMenuScreen(UiApp::ScreenType& screen) {
  const Rect bounds = menuListRect(renderer, mappedInput);
  screen.setContentMargin(fui::Insets{
      static_cast<int16_t>(bounds.y), 0,
      static_cast<int16_t>(renderer.getScreenHeight() - bounds.y - bounds.height), 0});

  std::array<fui::ListItem, kMenuRowCount> items{};
  for (int i = 0; i < kGridOptionCount; ++i) {
    items[static_cast<size_t>(i)].label = GRID_LABELS[i];
    items[static_cast<size_t>(i)].value = nullptr;
    items[static_cast<size_t>(i)].actionValue = static_cast<int16_t>(i);
  }
  items[4].label = "Aide compteur de mines";
  items[4].actionValue = 4;
  items[5].label = "Continuer";
  items[5].value = hasSavedGame_ ? "Partie sauvegardee" : "Aucune partie";
  items[5].actionValue = 5;
  items[6].label = "Nouvelle partie";
  items[6].value = GRID_DIMS[gridSizeIndex_];
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
  topIndex_ = initialViewportPending_
                  ? followListSelection(selectedIndex_, 0, visibleRows_, kMenuRowCount)
                  : scrollListBy(topIndex_, 0, visibleRows_, kMenuRowCount);
  initialViewportPending_ = false;
  props.topIndex = static_cast<uint16_t>(topIndex_);
  screen.list(props);
}

'''
text = replace_span(text, "void MinesweeperActivity::buildMenuScreen(UiApp::ScreenType& screen) {", "void MinesweeperActivity::render(RenderLock&&)", menu, "mine menu")
mine.write_text(text)

mine_h = Path("src/activities/home/MinesweeperActivity.h")
text = mine_h.read_text()
text = replace_once(text, "  bool isValidCell(int row, int col) const;\n", "", "mine isValid decl")
mine_h.write_text(text)

text = mine.read_text()
start = text.find("bool MinesweeperActivity::isValidCell(const int row, const int col) const {")
end = text.find("int MinesweeperActivity::adjacentMineCount", start)
if start < 0 or end < 0:
    raise SystemExit("missing mine isValid implementation")
text = text[:start] + text[end:]
mine.write_text(text)
