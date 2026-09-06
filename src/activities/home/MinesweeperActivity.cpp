#include "MinesweeperActivity.h"

#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <esp_random.h>
#include <esp_timer.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>

#include "AlertActivity.h"
#include "CrossPointState.h"
#include "MappedInputManager.h"
#include "activities/util/ConfirmationActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "fontIds.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;
constexpr const char SAVE_DIR[] = "/.crosspoint";
constexpr const char SAVE_PATH[] = "/.crosspoint/minesweeper.bin";
constexpr const char SCORE_PATH[] = "/.crosspoint/minesweeper-scores.bin";
constexpr uint32_t SAVE_MAGIC = 0x4D535734;  // MSW4: packed, intentionally incompatible with old saves.
constexpr uint32_t SCORE_MAGIC = 0x4D534353;
constexpr uint8_t SCORE_VERSION = 1;
constexpr int64_t LOSS_UNDO_WINDOW_US = 5LL * 1000LL * 1000LL;
constexpr int SCORE_TABLE_HEIGHT = 152;
constexpr int SCORE_RESET_GAP = 8;
constexpr int SCORE_RESET_BUTTON_HEIGHT = 44;
constexpr int SCORE_AREA_HEIGHT = SCORE_TABLE_HEIGHT + SCORE_RESET_GAP + SCORE_RESET_BUTTON_HEIGHT;
constexpr int SCORE_GRID_COUNT = 4;

bool undoAvailable = false;
int undoMineIndex = -1;
int64_t lossUndoDeadlineUs = 0;

// The menu choice applies to newly-created games. The active value is saved
// with the game so Continue always keeps the same counter behaviour.
bool assistedCounterChoice = false;
bool assistedCounterActive = false;
bool scoreFrozen = false;
int officialScore = 0;
std::array<uint16_t, SCORE_GRID_COUNT> bestScores{};
bool scoresDirty = false;

constexpr const char* GRID_LABELS[] = {
    "Enfant - 5 x 5 - 3 Mines",
    "Petite - 9 x 9 - 10 Mines",
    "Moyenne - 12 x 12 - 24 Mines",
    "Grande - 16 x 16 - 40 Mines",
};

constexpr const char* GRID_DIMS[] = {
    "5 x 5",
    "9 x 9",
    "12 x 12",
    "16 x 16",
};

constexpr int GRID_SIZES[] = {5, 9, 12, 16};
constexpr int MINE_COUNTS[] = {3, 10, 24, 40};

Rect menuListRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int contentTop =
      metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) + metrics.verticalSpacing;
  return Rect{0, contentTop, renderer.getScreenWidth(),
              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing -
                  SCORE_AREA_HEIGHT};
}

Rect scoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect list = menuListRect(renderer, mappedInput);
  return Rect{metrics.contentSidePadding, list.y + list.height,
              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, SCORE_TABLE_HEIGHT};
}

Rect scoreResetButtonRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect table = scoreTableRect(renderer, mappedInput);
  return Rect{table.x, table.y + table.height + SCORE_RESET_GAP, table.width, SCORE_RESET_BUTTON_HEIGHT};
}

Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int height = mappedInput.hasTouchHardware() ? TouchHeaderBackButton::height(metrics, mappedInput)
                                                     : metrics.headerHeight;
  return Rect{0, metrics.topPadding, renderer.getScreenWidth(), height};
}

bool pointInRect(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

struct GridGeometry {
  Rect header;
  Rect counterBar;
  Rect scoreMessage;
  Rect grid;
  int cellSize = 1;
};

GridGeometry gridGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput, const int dimension) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  const Rect header = headerRect(renderer, mappedInput);
  const int contentTop = header.y + header.height + metrics.verticalSpacing;
  const int counterHeight = std::max(40, renderer.getLineHeight(UI_12_FONT_ID) + 14);
  const int counterWidth = std::max(1, screenWidth - 2 * metrics.contentSidePadding);
  const Rect counterBar{metrics.contentSidePadding, contentTop, counterWidth, counterHeight};
  const int scoreMessageHeight = scoreFrozen ? renderer.getLineHeight(UI_10_FONT_ID) * 2 + 8 : 0;
  const Rect scoreMessage{metrics.contentSidePadding, counterBar.y + counterBar.height + metrics.verticalSpacing,
                          counterWidth, scoreMessageHeight};
  const int gridTop = scoreMessageHeight > 0
                          ? scoreMessage.y + scoreMessage.height + metrics.verticalSpacing
                          : counterBar.y + counterBar.height + metrics.verticalSpacing;
  const int footerTop = screenHeight - metrics.buttonHintsHeight;
  const int availableHeight = std::max(1, footerTop - gridTop - metrics.verticalSpacing);
  const int availableWidth = std::max(1, screenWidth - 2 * metrics.contentSidePadding);
  const int cellSize = std::max(1, std::min(availableWidth / dimension, availableHeight / dimension));
  const int gridWidth = cellSize * dimension;
  const int gridHeight = cellSize * dimension;
  const int gridX = (screenWidth - gridWidth) / 2;
  const int gridY = gridTop + std::max(0, (availableHeight - gridHeight) / 2);
  return GridGeometry{header, counterBar, scoreMessage, Rect{gridX, gridY, gridWidth, gridHeight}, cellSize};
}

template <typename T>
bool writeValue(FsFile& file, const T& value) {
  return file.write(reinterpret_cast<const uint8_t*>(&value), sizeof(T)) == sizeof(T);
}

template <typename T>
bool readValue(FsFile& file, T& value) {
  return file.read(reinterpret_cast<uint8_t*>(&value), sizeof(T)) == static_cast<int>(sizeof(T));
}

bool loadBestScores() {
  bestScores.fill(0);
  scoresDirty = false;
  if (!Storage.exists(SCORE_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("MINE", SCORE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t count = 0;
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, count);
  if (!ok || magic != SCORE_MAGIC || version != SCORE_VERSION || count != SCORE_GRID_COUNT) {
    file.close();
    bestScores.fill(0);
    return false;
  }
  for (int i = 0; i < SCORE_GRID_COUNT && ok; ++i) ok = readValue(file, bestScores[i]);
  file.close();
  if (!ok) bestScores.fill(0);
  return ok;
}

bool saveBestScores() {
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

void drawHiddenCellPattern(GfxRenderer& renderer, const int x, const int y, const int size) {
  if (size <= 4) return;

  renderer.fillRect(x + 1, y + 1, std::max(1, size - 1), std::max(1, size - 1), false);
  for (int py = y + 4; py < y + size - 3; py += 4) {
    const int offset = (((py - y) / 4) & 1) ? 2 : 0;
    for (int px = x + 4 + offset; px < x + size - 3; px += 4) {
      renderer.fillRect(px, py, 1, 1, true);
    }
  }

  const int bevel = size >= 20 ? 2 : 1;
  renderer.fillRect(x + 1, y + size - 1 - bevel, std::max(1, size - 2), bevel, true);
  renderer.fillRect(x + size - 1 - bevel, y + 1, bevel, std::max(1, size - 2), true);
}
}  // namespace

MinesweeperActivity::MinesweeperActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Minesweeper", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

void MinesweeperActivity::onEnter() {
  Activity::onEnter();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  uiReady_ = false;
  confirmHoldHandled_ = false;
  undoAvailable = false;
  undoMineIndex = -1;
  lossUndoDeadlineUs = 0;
  assistedCounterChoice = false;
  assistedCounterActive = false;
  scoreFrozen = false;
  officialScore = 0;
  loadBestScores();

  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  hasSavedGame_ = loadSavedGame();
  selectedIndex_ = gridSizeIndex_;

  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &MinesweeperActivity::onRowEvent, this);
  app_.setScreen(&MinesweeperActivity::menuScreen, this);
  requestUpdate();
}

void MinesweeperActivity::onExit() {
  if (viewMode_ == ViewMode::Grid && !gameOver_) saveGame();
  flushBestScores();
  Activity::onExit();
}

void MinesweeperActivity::loop() {
  if (viewMode_ == ViewMode::Grid) {
    loopGrid();
  } else if (viewMode_ == ViewMode::Result) {
    loopResult();
  } else {
    loopMenu();
  }
}

void MinesweeperActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
    return;
  }

  int resetTapX = 0;
  int resetTapY = 0;
  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(resetTapX, resetTapY) &&
      pointInRect(scoreResetButtonRect(renderer, mappedInput), resetTapX, resetTapY)) {
    startActivityForResult(
        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Reinitialiser les scores",
                                               "Effacer tous les meilleurs scores ?"),
        [this](const ActivityResult& result) {
          if (!result.isCancelled) {
            bestScores.fill(0);
            scoresDirty = false;
            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);
          }
          requestUpdate();
        });
    return;
  }

  if (uiReady_) {
    const fui::InputSnapshot snap = touchSnapshotFrom(mappedInput);
    if (snap.touchPressed || snap.touchReleased) {
      const auto event = app_.route(snap);
      if (app_.invalidated()) requestUpdate();
      if (event) return;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    activateRow(selectedIndex_);
    return;
  }

  const auto swipe = mappedInput.wasSwipe();
  if (swipe == MappedInputManager::SwipeDir::Up || swipe == MappedInputManager::SwipeDir::Down) {
    const int delta = swipe == MappedInputManager::SwipeDir::Up ? visibleRows_ : -visibleRows_;
    const int next = scrollListBy(topIndex_, delta, visibleRows_, kMenuRowCount);
    if (next != topIndex_) {
      topIndex_ = next;
      requestUpdate();
    }
    return;
  }

  const auto moveSelection = [this](const int index) {
    selectedIndex_ = index;
    topIndex_ = followListSelection(selectedIndex_, topIndex_, visibleRows_, kMenuRowCount);
    requestUpdate();
  };

  buttonNavigator_.onNextRelease(
      [this, &moveSelection] { moveSelection(ButtonNavigator::nextIndex(selectedIndex_, kMenuRowCount)); });
  buttonNavigator_.onPreviousRelease(
      [this, &moveSelection] { moveSelection(ButtonNavigator::previousIndex(selectedIndex_, kMenuRowCount)); });
  buttonNavigator_.onNextContinuous([this, &moveSelection] {
    moveSelection(ButtonNavigator::nextPageIndex(selectedIndex_, kMenuRowCount, visibleRows_));
  });
  buttonNavigator_.onPreviousContinuous([this, &moveSelection] {
    moveSelection(ButtonNavigator::previousPageIndex(selectedIndex_, kMenuRowCount, visibleRows_));
  });
}

void MinesweeperActivity::loopGrid() {
  const int dimension = gridDimension();
  const int count = totalCells();
  const GridGeometry geometry = gridGeometry(renderer, mappedInput, dimension);

  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenLongPress(tx, ty) && pointInRect(geometry.grid, tx, ty)) {
    const int col = std::clamp((tx - geometry.grid.x) / geometry.cellSize, 0, dimension - 1);
    const int row = std::clamp((ty - geometry.grid.y) / geometry.cellSize, 0, dimension - 1);
    selectedCellIndex_ = row * dimension + col;
    toggleFlag(selectedCellIndex_);
    mappedInput.suppressNextTouchTap();
    requestUpdate();
    return;
  }

  if (mappedInput.wasScreenTapped(tx, ty) && pointInRect(geometry.grid, tx, ty)) {
    const int col = std::clamp((tx - geometry.grid.x) / geometry.cellSize, 0, dimension - 1);
    const int row = std::clamp((ty - geometry.grid.y) / geometry.cellSize, 0, dimension - 1);
    selectedCellIndex_ = row * dimension + col;
    revealCell(selectedCellIndex_);
    requestUpdate();
    return;
  }

  if (mappedInput.isPressed(MappedInputManager::Button::Confirm) &&
      mappedInput.getHeldTime() >= kFlagHoldMs && !confirmHoldHandled_) {
    confirmHoldHandled_ = true;
    toggleFlag(selectedCellIndex_);
    requestUpdate();
    return;
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (confirmHoldHandled_) {
      confirmHoldHandled_ = false;
    } else {
      revealCell(selectedCellIndex_);
      requestUpdate();
    }
    return;
  }

  const auto moveCell = [this, count](const int index) {
    selectedCellIndex_ = std::clamp(index, 0, count - 1);
    requestUpdate();
  };

  buttonNavigator_.onNextRelease(
      [this, count, &moveCell] { moveCell(ButtonNavigator::nextIndex(selectedCellIndex_, count)); });
  buttonNavigator_.onPreviousRelease(
      [this, count, &moveCell] { moveCell(ButtonNavigator::previousIndex(selectedCellIndex_, count)); });
  buttonNavigator_.onNextContinuous(
      [this, count, &moveCell] { moveCell(ButtonNavigator::nextIndex(selectedCellIndex_, count)); });
  buttonNavigator_.onPreviousContinuous(
      [this, count, &moveCell] { moveCell(ButtonNavigator::previousIndex(selectedCellIndex_, count)); });
}

void MinesweeperActivity::loopResult() {
  const Rect header = headerRect(renderer, mappedInput);

  if (!gameOver_) {
    if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
        mappedInput.wasPressed(MappedInputManager::Button::Back)) {
      mappedInput.suppressNextBackRelease();
      viewMode_ = ViewMode::Menu;
      selectedIndex_ = gridSizeIndex_;
      topIndex_ = 0;
      initialViewportPending_ = true;
      requestUpdate();
    }
    return;
  }

  if (!won_ && undoAvailable && lossUndoDeadlineUs > 0 && esp_timer_get_time() >= lossUndoDeadlineUs) {
    undoAvailable = false;
    undoMineIndex = -1;
    lossUndoDeadlineUs = 0;
    for (int i = 0; i < totalCells(); ++i) revealed_[i] = 1;
    requestUpdate();
  }

  const auto undoLoss = [this]() {
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

  if (!won_ && undoAvailable && mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    undoLoss();
    return;
  }

  int tx = 0;
  int ty = 0;
  const GridGeometry geometry = gridGeometry(renderer, mappedInput, gridDimension());
  const int undoWidth = std::min(260, renderer.getScreenWidth() - 40);
  const int undoHeight = 48;
  const int undoX = (renderer.getScreenWidth() - undoWidth) / 2;
  const int undoY = std::min(renderer.getScreenHeight() - undoHeight - 16,
                             geometry.grid.y + geometry.grid.height + 16);
  const Rect undoTouchArea{undoX, undoY, undoWidth, undoHeight};
  if (!won_ && undoAvailable && mappedInput.wasScreenTapped(tx, ty) && pointInRect(undoTouchArea, tx, ty)) {
    undoLoss();
    return;
  }

  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
  }
}

void MinesweeperActivity::activateRow(const int row) {
  if (row >= 0 && row < kGridOptionCount) {
    gridSizeIndex_ = row;
    selectedIndex_ = row;
    requestUpdate();
    return;
  }
  if (row == 4) {
    assistedCounterChoice = !assistedCounterChoice;
    selectedIndex_ = row;
    requestUpdate();
    return;
  }
  if (row == 5) {
    continueGame();
    return;
  }
  if (row == 6) {
    if (!hasSavedGame_) {
      newGame();
      return;
    }
    startActivityForResult(
        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Nouvelle partie",
                                               "Ecraser la partie en cours ?"),
        [this](const ActivityResult& result) {
          if (result.isCancelled) {
            requestUpdate();
            return;
          }
          newGame();
        });
  }
}

void MinesweeperActivity::continueGame() {
  if (!hasSavedGame_) {
    gameOver_ = false;
    viewMode_ = ViewMode::Result;
    requestUpdate();
    return;
  }
  assistedCounterChoice = assistedCounterActive;
  enterGrid();
}

void MinesweeperActivity::newGame() {
  assistedCounterActive = assistedCounterChoice;
  resetGame();
  clearSavedGame();
  enterGrid();
}

void MinesweeperActivity::enterGrid() {
  viewMode_ = ViewMode::Grid;
  uiReady_ = false;
  confirmHoldHandled_ = false;
  selectedCellIndex_ = std::clamp(selectedCellIndex_, 0, totalCells() - 1);
  requestUpdate();
}

void MinesweeperActivity::returnToMenu() {
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

int MinesweeperActivity::gridDimension() const {
  return GRID_SIZES[std::clamp(gridSizeIndex_, 0, kGridOptionCount - 1)];
}

int MinesweeperActivity::mineCount() const {
  return MINE_COUNTS[std::clamp(gridSizeIndex_, 0, kGridOptionCount - 1)];
}

int MinesweeperActivity::totalCells() const {
  const int dimension = gridDimension();
  return dimension * dimension;
}

int MinesweeperActivity::adjacentMineCount(const int index) const {
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

void MinesweeperActivity::resetGame() {
  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  minesPlaced_ = false;
  gameOver_ = false;
  won_ = false;
  revealedSafeCells_ = 0;
  scoreFrozen = false;
  officialScore = 0;
  selectedCellIndex_ = 0;
  confirmHoldHandled_ = false;
  undoAvailable = false;
  undoMineIndex = -1;
  lossUndoDeadlineUs = 0;
}

void MinesweeperActivity::placeMines(const int firstIndex) {
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

void MinesweeperActivity::revealCell(const int index) {
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

void MinesweeperActivity::revealFlood(const int startIndex) {
  std::array<uint8_t, kMaxCells> queue{};
  const int dimension = gridDimension();
  const int cellCount = dimension * dimension;
  int head = 0;
  int tail = 0;
  queue[tail++] = static_cast<uint8_t>(startIndex);

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
        if (!revealed_[next] && !flagged_[next] && !mines_[next] && tail < kMaxCells) {
          queue[tail++] = static_cast<uint8_t>(next);
        }
      }
    }
  }
}

void MinesweeperActivity::toggleFlag(const int index) {
  if (gameOver_ || index < 0 || index >= totalCells() || revealed_[index]) return;
  flagged_[index] = flagged_[index] ? 0 : 1;
  saveGame();
  flushBestScores();
}

void MinesweeperActivity::checkWin() {
  if (revealedSafeCells_ >= totalCells() - mineCount()) finishGame(true);
}

void MinesweeperActivity::finishGame(const bool won) {
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

bool MinesweeperActivity::saveGame() {
  if (gameOver_) return false;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MINE", SAVE_PATH, file)) return false;

  const int cellCount = totalCells();
  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);
  const uint8_t grid = static_cast<uint8_t>(gridSizeIndex_);
  const uint8_t stateFlags = static_cast<uint8_t>((assistedCounterActive ? 0x01 : 0x00) |
                                                   (scoreFrozen ? 0x02 : 0x00));
  const uint8_t selected = static_cast<uint8_t>(std::clamp(selectedCellIndex_, 0, cellCount - 1));
  const uint8_t savedOfficialScore = static_cast<uint8_t>(std::clamp(officialScore, 0, 255));

  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, grid) && writeValue(file, stateFlags) &&
            writeValue(file, selected) && writeValue(file, savedOfficialScore);
  if (ok) ok = file.write(mines_.data(), packedBytes) == packedBytes;
  if (ok) ok = file.write(revealed_.data(), packedBytes) == packedBytes;
  if (ok) ok = file.write(flagged_.data(), packedBytes) == packedBytes;
  file.close();

  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    return false;
  }
  hasSavedGame_ = true;
  return true;
}

bool MinesweeperActivity::loadSavedGame() {
  undoAvailable = false;
  undoMineIndex = -1;
  lossUndoDeadlineUs = 0;
  assistedCounterActive = false;
  assistedCounterChoice = false;
  if (!Storage.exists(SAVE_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("MINE", SAVE_PATH, file)) return false;

  uint32_t magic = 0;
  uint8_t grid = 0;
  uint8_t stateFlags = 0;
  uint8_t selected = 0;
  uint8_t savedOfficialScore = 0;
  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&
            readValue(file, selected) && readValue(file, savedOfficialScore);

  if (!ok || magic != SAVE_MAGIC || grid >= kGridOptionCount) {
    file.close();
    clearSavedGame();
    return false;
  }

  gridSizeIndex_ = grid;
  const int cellCount = totalCells();
  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);
  constexpr size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t);
  const size_t expectedSize = headerBytes + 3 * packedBytes;
  if (file.size() != expectedSize || selected >= cellCount) {
    file.close();
    clearSavedGame();
    resetGame();
    return false;
  }

  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  ok = file.read(mines_.data(), packedBytes) == static_cast<int>(packedBytes);
  if (ok) ok = file.read(revealed_.data(), packedBytes) == static_cast<int>(packedBytes);
  if (ok) ok = file.read(flagged_.data(), packedBytes) == static_cast<int>(packedBytes);
  file.close();

  if (!ok) {
    clearSavedGame();
    resetGame();
    return false;
  }

  minesPlaced_ = mines_.any();
  assistedCounterActive = (stateFlags & 0x01) != 0;
  assistedCounterChoice = assistedCounterActive;
  selectedCellIndex_ = selected;
  revealedSafeCells_ = 0;
  for (int i = 0; i < cellCount; ++i) {
    if (revealed_[i] && !mines_[i]) ++revealedSafeCells_;
  }

  scoreFrozen = (stateFlags & 0x02) != 0;
  if (scoreFrozen && savedOfficialScore > revealedSafeCells_) {
    clearSavedGame();
    resetGame();
    return false;
  }
  officialScore = scoreFrozen ? savedOfficialScore : revealedSafeCells_;
  updateBestScore(gridSizeIndex_, officialScore);
  gameOver_ = false;
  won_ = false;
  return true;
}

void MinesweeperActivity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
}

void MinesweeperActivity::showInfo(const char* title, const char* body) {
  std::strcpy(APP_STATE.pendingAlertTitle, title);
  std::strcpy(APP_STATE.pendingAlertBody, body);
  APP_STATE.pendingAlertGoHomeOnBack.store(false, std::memory_order_relaxed);
  startActivityForResult(std::make_unique<AlertActivity>(renderer, mappedInput), [](const ActivityResult&) {});
}

void MinesweeperActivity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<MinesweeperActivity*>(user);
  if (event.value < 0 || event.value >= kMenuRowCount) return;
  self->selectedIndex_ = event.value;
  self->app_.clearTapFlash();
  self->activateRow(event.value);
}

void MinesweeperActivity::menuScreen(UiApp::ScreenType& screen, void* user) {
  static_cast<MinesweeperActivity*>(user)->buildMenuScreen(screen);
}

void MinesweeperActivity::buildMenuScreen(UiApp::ScreenType& screen) {
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

void MinesweeperActivity::render(RenderLock&&) {
  if (viewMode_ == ViewMode::Grid) {
    renderGrid();
  } else if (viewMode_ == ViewMode::Result) {
    renderResult();
  } else {
    renderMenu();
  }
}

void MinesweeperActivity::renderMenu() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Demineur", false);
  } else {
    GUI.drawHeader(renderer, header, "Demineur", nullptr, false);
  }

  uiReady_ = false;
  app_.render();
  uiReady_ = true;

  // Draw option states as real e-ink checkboxes: white square with a black
  // inset square when enabled. This avoids font-dependent checkbox glyphs.
  const Rect listBounds = menuListRect(renderer, mappedInput);
  const int drawnRows = std::max(1, visibleRows_);
  const int boxSize = 22;
  const int innerSize = 10;
  const int boxX = renderer.getScreenWidth() - UITheme::getInstance().getMetrics().contentSidePadding - boxSize - 10;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex < 0 || itemIndex > 4) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    const bool checked = itemIndex < kGridOptionCount ? itemIndex == gridSizeIndex_ : assistedCounterChoice;
    if (checked) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
  }

  // Make Continue and New Game visually read as action buttons.
  const auto& menuMetrics = UITheme::getInstance().getMetrics();
  constexpr int actionInsetY = 4;
  const int actionX = menuMetrics.contentSidePadding;
  const int actionWidth = renderer.getScreenWidth() - 2 * menuMetrics.contentSidePadding;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex != 5 && itemIndex != 6) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int actionY = rowTop + actionInsetY;
    const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);
    renderer.drawRoundedRect(actionX, actionY, actionWidth, actionHeight, 1, 6, true);
  }

  const Rect scorePanel = scoreTableRect(renderer, mappedInput);
  renderer.fillRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, false);
  renderer.drawRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, 1, true);
  const int headerRowHeight = 30;
  const int dataTop = scorePanel.y + headerRowHeight;
  const int dataHeight = scorePanel.height - headerRowHeight;
  const int splitX = scorePanel.x + scorePanel.width * 2 / 5;

  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);
  renderer.drawLine(splitX, dataTop, splitX, scorePanel.y + scorePanel.height, 1, true);

  auto drawCenteredCellText = [this](const int fontId, const Rect& cell, const char* text) {
    const int textWidth = renderer.getTextWidth(fontId, text);
    const int textHeight = renderer.getLineHeight(fontId);
    renderer.drawText(fontId, cell.x + std::max(0, (cell.width - textWidth) / 2),
                      cell.y + std::max(0, (cell.height - textHeight) / 2) + 1, text);
  };

  const Rect scoreHeader{scorePanel.x, scorePanel.y, scorePanel.width, headerRowHeight};
  drawCenteredCellText(UI_12_FONT_ID, scoreHeader, "SCORES");

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

  const auto labels =
      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}

void MinesweeperActivity::renderGrid() {
  renderer.clearScreen();
  const int dimension = gridDimension();
  const GridGeometry geometry = gridGeometry(renderer, mappedInput, dimension);

  int flags = 0;
  int correctFlags = 0;
  for (int i = 0; i < totalCells(); ++i) {
    if (!flagged_[i]) continue;
    ++flags;
    if (minesPlaced_ && mines_[i]) ++correctFlags;
  }

  char title[64];
  if (gameOver_) {
    std::snprintf(title, sizeof(title), "%s - %s", won_ ? "Victoire !" : "Perdu !", GRID_DIMS[gridSizeIndex_]);
  } else {
    std::snprintf(title, sizeof(title), "Demineur - %s", GRID_DIMS[gridSizeIndex_]);
  }
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, title, false);
  } else {
    GUI.drawHeader(renderer, geometry.header, title);
  }

  renderer.fillRect(geometry.counterBar.x, geometry.counterBar.y, geometry.counterBar.width,
                    geometry.counterBar.height, false);
  renderer.drawRect(geometry.counterBar.x, geometry.counterBar.y, geometry.counterBar.width,
                    geometry.counterBar.height, 2, true);

  const int gap = 8;
  const int panelWidth = std::max(1, (geometry.counterBar.width - 3 * gap) / 2);
  const int panelHeight = std::max(1, geometry.counterBar.height - 2 * gap);
  const Rect leftPanel{geometry.counterBar.x + gap, geometry.counterBar.y + gap, panelWidth, panelHeight};
  const Rect rightPanel{geometry.counterBar.x + 2 * gap + panelWidth, geometry.counterBar.y + gap,
                        panelWidth, panelHeight};
  renderer.drawRect(leftPanel.x, leftPanel.y, leftPanel.width, leftPanel.height, 1, true);
  renderer.drawRect(rightPanel.x, rightPanel.y, rightPanel.width, rightPanel.height, 1, true);

  const int leftValue = assistedCounterActive ? std::max(0, mineCount() - correctFlags) : flags;
  char leftText[32];
  std::snprintf(leftText, sizeof(leftText), "%s %03d", assistedCounterActive ? "Mines" : "Drapeaux", leftValue);
  char pointsText[32];
  std::snprintf(pointsText, sizeof(pointsText), "Points %03d", std::max(0, scoreFrozen ? officialScore : revealedSafeCells_));
  const int counterFont = UI_12_FONT_ID;
  auto drawCenteredCounter = [this, counterFont](const Rect& panel, const char* text) {
    const int textWidth = renderer.getTextWidth(counterFont, text);
    const int textHeight = renderer.getTextHeight(counterFont);
    const int textX = panel.x + (panel.width - textWidth) / 2;
    const int textY = panel.y + (panel.height - textHeight) / 2;
    renderer.drawText(counterFont, textX, textY, text);
  };
  drawCenteredCounter(leftPanel, leftText);
  drawCenteredCounter(rightPanel, pointsText);

  if (scoreFrozen && geometry.scoreMessage.height > 0) {
    char scoreMessage[96];
    std::snprintf(scoreMessage, sizeof(scoreMessage),
                  "Vous etes tombe sur une mine, votre score aurait ete de : %03d", revealedSafeCells_);
    const auto lines = renderer.wrappedText(UI_10_FONT_ID, scoreMessage, geometry.scoreMessage.width, 2);
    int textY = geometry.scoreMessage.y + 2;
    for (const auto& line : lines) {
      const int textWidth = renderer.getTextWidth(UI_10_FONT_ID, line.c_str());
      renderer.drawText(UI_10_FONT_ID,
                        geometry.scoreMessage.x + std::max(0, (geometry.scoreMessage.width - textWidth) / 2), textY,
                        line.c_str());
      textY += renderer.getLineHeight(UI_10_FONT_ID);
    }
  }

  renderer.drawRect(geometry.grid.x, geometry.grid.y, geometry.grid.width + 1, geometry.grid.height + 1, 1, true);

  for (int row = 0; row < dimension; ++row) {
    for (int col = 0; col < dimension; ++col) {
      const int index = row * dimension + col;
      const int x = geometry.grid.x + col * geometry.cellSize;
      const int y = geometry.grid.y + row * geometry.cellSize;

      if (!revealed_[index]) {
        drawHiddenCellPattern(renderer, x, y, geometry.cellSize);
      }

      if (revealed_[index]) {
        renderer.fillRect(x + 1, y + 1, std::max(1, geometry.cellSize - 1),
                          std::max(1, geometry.cellSize - 1), false);
        if (mines_[index]) {
          const int margin = std::max(2, geometry.cellSize / 4);
          renderer.fillRect(x + margin, y + margin, std::max(1, geometry.cellSize - 2 * margin),
                            std::max(1, geometry.cellSize - 2 * margin), true);
        } else {
          const int adjacent = adjacentMineCount(index);
          if (adjacent > 0) {
            char number[2] = {static_cast<char>('0' + adjacent), '\0'};
            const int font = geometry.cellSize >= 26 ? UI_12_FONT_ID : UI_10_FONT_ID;
            const int textWidth = renderer.getTextWidth(font, number);
            const int textHeight = renderer.getLineHeight(font);
            renderer.drawText(font, x + std::max(1, (geometry.cellSize - textWidth) / 2),
                              y + std::max(1, (geometry.cellSize - textHeight) / 2), number);
          }
        }
      } else if (flagged_[index]) {
        const int boxMargin = std::max(2, geometry.cellSize / 5);
        renderer.fillRect(x + boxMargin, y + boxMargin, std::max(1, geometry.cellSize - 2 * boxMargin),
                          std::max(1, geometry.cellSize - 2 * boxMargin), false);
        const char* flag = "F";
        const int font = geometry.cellSize >= 26 ? UI_12_FONT_ID : UI_10_FONT_ID;
        const int textWidth = renderer.getTextWidth(font, flag);
        const int textHeight = renderer.getLineHeight(font);
        renderer.drawText(font, x + std::max(1, (geometry.cellSize - textWidth) / 2),
                          y + std::max(1, (geometry.cellSize - textHeight) / 2), flag);
      }
    }
  }

  for (int i = 1; i < dimension; ++i) {
    const int x = geometry.grid.x + i * geometry.cellSize;
    renderer.drawLine(x, geometry.grid.y, x, geometry.grid.y + geometry.grid.height, 1, true);
  }
  for (int i = 1; i < dimension; ++i) {
    const int y = geometry.grid.y + i * geometry.cellSize;
    renderer.drawLine(geometry.grid.x, y, geometry.grid.x + geometry.grid.width, y, 1, true);
  }

  if (!gameOver_) {
    const int selectedRow = selectedCellIndex_ / dimension;
    const int selectedCol = selectedCellIndex_ % dimension;
    const int selectedX = geometry.grid.x + selectedCol * geometry.cellSize;
    const int selectedY = geometry.grid.y + selectedRow * geometry.cellSize;
    if (geometry.cellSize >= 7) {
      renderer.drawRect(selectedX + 2, selectedY + 2, std::max(1, geometry.cellSize - 3),
                        std::max(1, geometry.cellSize - 3), 2, true);
      renderer.drawRect(selectedX + 5, selectedY + 5, std::max(1, geometry.cellSize - 9),
                        std::max(1, geometry.cellSize - 9), 1, true);
    }
  }

  const bool showUndoButton = gameOver_ && !won_ && undoAvailable;
  if (showUndoButton) {
    const int buttonWidth = std::min(260, renderer.getScreenWidth() - 40);
    const int buttonHeight = 48;
    const int buttonX = (renderer.getScreenWidth() - buttonWidth) / 2;
    const int buttonY = std::min(renderer.getScreenHeight() - buttonHeight - 16,
                                 geometry.grid.y + geometry.grid.height + 16);
    const char* undoLabel = "ANNULER (5 s)";
    const int font = UI_12_FONT_ID;
    const int textWidth = renderer.getTextWidth(font, undoLabel);
    const int textHeight = renderer.getLineHeight(font);

    renderer.fillRect(buttonX, buttonY, buttonWidth, buttonHeight, false);
    renderer.drawRect(buttonX, buttonY, buttonWidth, buttonHeight, 2, true);
    renderer.drawText(font, buttonX + std::max(2, (buttonWidth - textWidth) / 2),
                      buttonY + std::max(1, (buttonHeight - textHeight) / 2), undoLabel);
  } else {
    const auto labels = gameOver_
                            ? mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", "", "")
                            : mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)),
                                                    "Ouvrir / tenir: drapeau", tr(STR_DIR_UP), tr(STR_DIR_DOWN));
    GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  }
  renderer.displayBuffer();

  if (showUndoButton && lossUndoDeadlineUs == 0) {
    lossUndoDeadlineUs = esp_timer_get_time() + LOSS_UNDO_WINDOW_US;
  }
}

void MinesweeperActivity::renderResult() {
  if (gameOver_) {
    renderGrid();
    return;
  }

  renderer.clearScreen();
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Continuer", false);
  } else {
    GUI.drawHeader(renderer, header, "Continuer", nullptr, false);
  }

  const int x = metrics.contentSidePadding;
  const int y = header.y + header.height + metrics.verticalSpacing * 2;
  renderer.drawText(UI_12_FONT_ID, x, y, "Aucune partie sauvegardee");
  renderer.drawText(UI_10_FONT_ID, x, y + renderer.getLineHeight(UI_12_FONT_ID) + metrics.verticalSpacing,
                    "pour le moment.");

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}