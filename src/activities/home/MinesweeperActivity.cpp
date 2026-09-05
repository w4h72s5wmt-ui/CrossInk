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
#include <vector>

#include "AlertActivity.h"
#include "CrossPointState.h"
#include "MappedInputManager.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "fontIds.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;
constexpr const char SAVE_DIR[] = "/.crosspoint";
constexpr const char SAVE_PATH[] = "/.crosspoint/minesweeper.bin";
constexpr uint32_t SAVE_MAGIC = 0x4D535731;
constexpr uint8_t SAVE_VERSION = 2;
constexpr uint8_t PREVIOUS_SAVE_VERSION = 1;
constexpr int UNDO_MAX_CELLS = 16 * 16;
constexpr int64_t LOSS_UNDO_WINDOW_US = 5LL * 1000LL * 1000LL;

std::array<uint8_t, UNDO_MAX_CELLS> undoMines{};
std::array<uint8_t, UNDO_MAX_CELLS> undoRevealed{};
std::array<uint8_t, UNDO_MAX_CELLS> undoFlagged{};
bool undoAvailable = false;
bool undoMinesPlaced = false;
int undoRevealedSafeCells = 0;
int undoSelectedCellIndex = 0;
int64_t lossUndoDeadlineUs = 0;

// New-game counter option. It is configured before starting a new game and
// the active value is saved with the game so Continue keeps the same mode.
bool newGameSetupActive = false;
bool assistedCounterChoice = false;
bool assistedCounterActive = false;

constexpr const char* GRID_LABELS[] = {
    "Petite - 9 x 9 - 10 Mines",
    "Moyenne - 12 x 12 - 24 Mines",
    "Grande - 16 x 16 - 40 Mines",
};

constexpr const char* GRID_DIMS[] = {
    "9 x 9",
    "12 x 12",
    "16 x 16",
};

constexpr int GRID_SIZES[] = {9, 12, 16};
constexpr int MINE_COUNTS[] = {10, 24, 40};

Rect menuListRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int contentTop =
      metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) + metrics.verticalSpacing;
  return Rect{0, contentTop, renderer.getScreenWidth(),
              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing};
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
  Rect grid;
  int cellSize = 1;
};

GridGeometry gridGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput, const int dimension) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  const Rect header = headerRect(renderer, mappedInput);
  const int contentTop = header.y + header.height + metrics.verticalSpacing;
  const int footerTop = screenHeight - metrics.buttonHintsHeight;
  const int availableHeight = std::max(1, footerTop - contentTop - metrics.verticalSpacing);
  const int availableWidth = std::max(1, screenWidth - 2 * metrics.contentSidePadding);
  const int cellSize = std::max(1, std::min(availableWidth / dimension, availableHeight / dimension));
  const int gridWidth = cellSize * dimension;
  const int gridHeight = cellSize * dimension;
  const int gridX = (screenWidth - gridWidth) / 2;
  const int gridY = contentTop + std::max(0, (availableHeight - gridHeight) / 2);
  return GridGeometry{header, Rect{gridX, gridY, gridWidth, gridHeight}, cellSize};
}

struct NewGameSetupGeometry {
  Rect header;
  Rect assistRow;
  Rect startButton;
};

NewGameSetupGeometry newGameSetupGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int x = metrics.contentSidePadding;
  const int width = std::max(1, renderer.getScreenWidth() - 2 * x);
  const int contentTop = header.y + header.height + metrics.verticalSpacing * 2;
  const int assistY = contentTop + renderer.getLineHeight(UI_12_FONT_ID) + metrics.verticalSpacing * 2;
  const Rect assistRow{x, assistY, width, 72};
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  const Rect startButton{x, std::max(assistY + 88, footerTop - 60), width, 48};
  return NewGameSetupGeometry{header, assistRow, startButton};
}

template <typename T>
bool writeValue(FsFile& file, const T& value) {
  return file.write(reinterpret_cast<const uint8_t*>(&value), sizeof(T)) == sizeof(T);
}

template <typename T>
bool readValue(FsFile& file, T& value) {
  return file.read(reinterpret_cast<uint8_t*>(&value), sizeof(T)) == static_cast<int>(sizeof(T));
}

void drawHiddenCellPattern(GfxRenderer& renderer, const int x, const int y, const int size) {
  if (size <= 4) return;

  // Light Windows-style raised cell: dotted grey face with dark bottom/right bevel.
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
  lossUndoDeadlineUs = 0;
  newGameSetupActive = false;
  assistedCounterChoice = false;
  assistedCounterActive = false;

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

  if (!gameOver_ && newGameSetupActive) {
    const NewGameSetupGeometry setup = newGameSetupGeometry(renderer, mappedInput);

    const auto backToMenu = [this]() {
      newGameSetupActive = false;
      viewMode_ = ViewMode::Menu;
      selectedIndex_ = gridSizeIndex_;
      topIndex_ = 0;
      initialViewportPending_ = true;
      requestUpdate();
    };

    const auto startConfiguredGame = [this]() {
      assistedCounterActive = assistedCounterChoice;
      newGameSetupActive = false;
      resetGame();
      clearSavedGame();
      enterGrid();
    };

    if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, setup.header)) ||
        mappedInput.wasPressed(MappedInputManager::Button::Back)) {
      mappedInput.suppressNextBackRelease();
      backToMenu();
      return;
    }

    int tx = 0;
    int ty = 0;
    if (mappedInput.wasScreenTapped(tx, ty)) {
      if (pointInRect(setup.assistRow, tx, ty)) {
        assistedCounterChoice = !assistedCounterChoice;
        selectedIndex_ = 0;
        requestUpdate();
        return;
      }
      if (pointInRect(setup.startButton, tx, ty)) {
        selectedIndex_ = 1;
        startConfiguredGame();
        return;
      }
    }

    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      if (selectedIndex_ == 0) {
        assistedCounterChoice = !assistedCounterChoice;
        requestUpdate();
      } else {
        startConfiguredGame();
      }
      return;
    }

    const auto moveSetupSelection = [this](const int index) {
      selectedIndex_ = std::clamp(index, 0, 1);
      requestUpdate();
    };
    buttonNavigator_.onNextRelease(
        [this, &moveSetupSelection] { moveSetupSelection(ButtonNavigator::nextIndex(selectedIndex_, 2)); });
    buttonNavigator_.onPreviousRelease(
        [this, &moveSetupSelection] { moveSetupSelection(ButtonNavigator::previousIndex(selectedIndex_, 2)); });
    buttonNavigator_.onNextContinuous(
        [this, &moveSetupSelection] { moveSetupSelection(ButtonNavigator::nextIndex(selectedIndex_, 2)); });
    buttonNavigator_.onPreviousContinuous(
        [this, &moveSetupSelection] { moveSetupSelection(ButtonNavigator::previousIndex(selectedIndex_, 2)); });
    return;
  }

  // Result is also reused for the no-save information screen. It must return to
  // the menu without creating a bogus save file.
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

  // Start the five-second countdown only after the loss screen has actually
  // been rendered. A zero deadline means the visible undo screen is still
  // being presented for the first time.
  if (!won_ && undoAvailable && lossUndoDeadlineUs > 0 && esp_timer_get_time() >= lossUndoDeadlineUs) {
    undoAvailable = false;
    lossUndoDeadlineUs = 0;
    for (int i = 0; i < totalCells(); ++i) revealed_[i] = 1;
    requestUpdate();
  }

  const auto undoLoss = [this]() {
    if (won_ || !undoAvailable) return;
    if (lossUndoDeadlineUs > 0 && esp_timer_get_time() >= lossUndoDeadlineUs) return;
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
  if (row == 3) {
    continueGame();
    return;
  }
  if (row == 4) newGame();
}

void MinesweeperActivity::continueGame() {
  if (!hasSavedGame_) {
    gameOver_ = false;
    viewMode_ = ViewMode::Result;
    requestUpdate();
    return;
  }
  enterGrid();
}

void MinesweeperActivity::newGame() {
  // Show a real pre-game option screen instead of changing game behaviour
  // silently from the main menu.
  newGameSetupActive = true;
  assistedCounterChoice = false;
  gameOver_ = false;
  selectedIndex_ = 0;
  viewMode_ = ViewMode::Result;
  requestUpdate();
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
  newGameSetupActive = false;
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  confirmHoldHandled_ = false;
  undoAvailable = false;
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

bool MinesweeperActivity::isValidCell(const int row, const int col) const {
  const int dimension = gridDimension();
  return row >= 0 && row < dimension && col >= 0 && col < dimension;
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
      if (isValidCell(nr, nc) && mines_[nr * dimension + nc]) ++count;
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
  selectedCellIndex_ = 0;
  confirmHoldHandled_ = false;
  undoAvailable = false;
  lossUndoDeadlineUs = 0;
}

void MinesweeperActivity::placeMines(const int firstIndex) {
  mines_.fill(0);
  const int dimension = gridDimension();
  const int firstRow = firstIndex / dimension;
  const int firstCol = firstIndex % dimension;
  const int wanted = mineCount();
  int placed = 0;

  while (placed < wanted) {
    const int index = static_cast<int>(esp_random() % static_cast<uint32_t>(totalCells()));
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

  // One-level undo snapshot taken immediately before the reveal action.
  undoMines = mines_;
  undoRevealed = revealed_;
  undoFlagged = flagged_;
  undoMinesPlaced = minesPlaced_;
  undoRevealedSafeCells = revealedSafeCells_;
  undoSelectedCellIndex = selectedCellIndex_;
  undoAvailable = true;

  if (!minesPlaced_) placeMines(index);
  if (mines_[index]) {
    revealed_[index] = 1;
    finishGame(false);
    return;
  }
  revealFlood(index);
  checkWin();
}

void MinesweeperActivity::revealFlood(const int startIndex) {
  std::array<int16_t, kMaxCells> queue{};
  int head = 0;
  int tail = 0;
  queue[tail++] = static_cast<int16_t>(startIndex);

  while (head < tail) {
    const int index = queue[head++];
    if (index < 0 || index >= totalCells() || revealed_[index] || flagged_[index] || mines_[index]) continue;
    revealed_[index] = 1;
    ++revealedSafeCells_;
    if (adjacentMineCount(index) != 0) continue;

    const int dimension = gridDimension();
    const int row = index / dimension;
    const int col = index % dimension;
    for (int dr = -1; dr <= 1; ++dr) {
      for (int dc = -1; dc <= 1; ++dc) {
        if (dr == 0 && dc == 0) continue;
        const int nr = row + dr;
        const int nc = col + dc;
        if (!isValidCell(nr, nc)) continue;
        const int next = nr * dimension + nc;
        if (!revealed_[next] && !flagged_[next] && !mines_[next] && tail < kMaxCells) {
          queue[tail++] = static_cast<int16_t>(next);
        }
      }
    }
  }
}

void MinesweeperActivity::toggleFlag(const int index) {
  if (gameOver_ || index < 0 || index >= totalCells() || revealed_[index]) return;
  flagged_[index] = flagged_[index] ? 0 : 1;
  saveGame();
}

void MinesweeperActivity::checkWin() {
  if (revealedSafeCells_ >= totalCells() - mineCount()) finishGame(true);
}

void MinesweeperActivity::finishGame(const bool won) {
  gameOver_ = true;
  won_ = won;

  if (won) {
    undoAvailable = false;
    lossUndoDeadlineUs = 0;
    for (int i = 0; i < totalCells(); ++i) {
      revealed_[i] = 1;
      if (mines_[i]) flagged_[i] = 1;
    }
  } else {
    // Keep the solution hidden. The five-second timer is armed only after the
    // undo button has actually been drawn on the e-ink screen.
    lossUndoDeadlineUs = 0;
  }

  clearSavedGame();
  viewMode_ = ViewMode::Result;
  requestUpdate();
}

bool MinesweeperActivity::saveGame() {
  if (gameOver_) return false;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MINE", SAVE_PATH, file)) return false;

  const uint8_t grid = static_cast<uint8_t>(gridSizeIndex_);
  const uint8_t minesPlaced = minesPlaced_ ? 1 : 0;
  const uint8_t assistedCounter = assistedCounterActive ? 1 : 0;
  const uint16_t selected = static_cast<uint16_t>(std::clamp(selectedCellIndex_, 0, totalCells() - 1));
  const uint16_t revealedCount = static_cast<uint16_t>(revealedSafeCells_);
  const uint16_t cellCount = static_cast<uint16_t>(totalCells());

  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, grid) &&
            writeValue(file, minesPlaced) && writeValue(file, assistedCounter) && writeValue(file, selected) &&
            writeValue(file, revealedCount) && writeValue(file, cellCount);
  if (ok) ok = file.write(mines_.data(), cellCount) == cellCount;
  if (ok) ok = file.write(revealed_.data(), cellCount) == cellCount;
  if (ok) ok = file.write(flagged_.data(), cellCount) == cellCount;
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
  lossUndoDeadlineUs = 0;
  assistedCounterActive = false;
  assistedCounterChoice = false;
  if (!Storage.exists(SAVE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MINE", SAVE_PATH, file)) return false;

  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t grid = 0;
  uint8_t minesPlaced = 0;
  uint8_t assistedCounter = 0;
  uint16_t selected = 0;
  uint16_t revealedCount = 0;
  uint16_t cellCount = 0;

  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, grid) &&
            readValue(file, minesPlaced);
  if (ok && version == SAVE_VERSION) ok = readValue(file, assistedCounter);
  if (ok) ok = readValue(file, selected) && readValue(file, revealedCount) && readValue(file, cellCount);

  if (!ok || magic != SAVE_MAGIC ||
      (version != SAVE_VERSION && version != PREVIOUS_SAVE_VERSION) || grid >= kGridOptionCount) {
    file.close();
    clearSavedGame();
    return false;
  }

  gridSizeIndex_ = grid;
  const int expectedCells = totalCells();
  if (cellCount != expectedCells || cellCount > kMaxCells) {
    file.close();
    clearSavedGame();
    return false;
  }

  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  ok = file.read(mines_.data(), cellCount) == cellCount;
  if (ok) ok = file.read(revealed_.data(), cellCount) == cellCount;
  if (ok) ok = file.read(flagged_.data(), cellCount) == cellCount;
  file.close();

  if (!ok || selected >= cellCount || revealedCount > cellCount) {
    clearSavedGame();
    resetGame();
    return false;
  }

  minesPlaced_ = minesPlaced != 0;
  assistedCounterActive = version == SAVE_VERSION && assistedCounter != 0;
  assistedCounterChoice = assistedCounterActive;
  selectedCellIndex_ = selected;
  revealedSafeCells_ = revealedCount;
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

  std::vector<fui::ListItem> items;
  items.reserve(kMenuRowCount);
  for (int i = 0; i < kGridOptionCount; ++i) {
    fui::ListItem item;
    item.label = GRID_LABELS[i];
    item.value = i == gridSizeIndex_ ? "Choisie" : nullptr;
    item.actionValue = static_cast<int16_t>(i);
    items.push_back(item);
  }

  fui::ListItem continueItem;
  continueItem.label = "Continuer";
  continueItem.value = hasSavedGame_ ? "Partie sauvegardee" : "Aucune partie";
  continueItem.actionValue = 3;
  items.push_back(continueItem);

  fui::ListItem newGameItem;
  newGameItem.label = "Nouvelle partie";
  newGameItem.value = GRID_DIMS[gridSizeIndex_];
  newGameItem.actionValue = 4;
  items.push_back(newGameItem);

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
  } else if (assistedCounterActive) {
    std::snprintf(title, sizeof(title), "Demineur %s  Mines: %d", GRID_DIMS[gridSizeIndex_],
                  std::max(0, mineCount() - correctFlags));
  } else {
    std::snprintf(title, sizeof(title), "Demineur %s  Drapeaux: %d", GRID_DIMS[gridSizeIndex_], flags);
  }
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, title, false);
  } else {
    GUI.drawHeader(renderer, geometry.header, title);
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
        // Revealed cells are always pure white for maximum e-ink readability.
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
    // Put the undo control directly below the grid. This remains visible on
    // touch-only layouts where the generic button-hints footer can be absent.
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

  // Arm the grace-period clock after the frame containing the button has been
  // sent to the display, so the user gets the full five seconds to react.
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

  if (newGameSetupActive) {
    const NewGameSetupGeometry setup = newGameSetupGeometry(renderer, mappedInput);
    if (mappedInput.hasTouchHardware()) {
      TouchHeaderBackButton::draw(renderer, uiTarget_, setup.header, "Nouvelle partie", false);
    } else {
      GUI.drawHeader(renderer, setup.header, "Nouvelle partie", nullptr, false);
    }

    const int x = metrics.contentSidePadding;
    const int y = setup.header.y + setup.header.height + metrics.verticalSpacing * 2;
    renderer.drawText(UI_12_FONT_ID, x, y, GRID_LABELS[gridSizeIndex_]);

    const int boxSize = 26;
    const int boxX = setup.assistRow.x + 4;
    const int boxY = setup.assistRow.y + 8;
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    if (assistedCounterChoice) {
      renderer.drawLine(boxX + 5, boxY + 13, boxX + 11, boxY + 20, 2, true);
      renderer.drawLine(boxX + 11, boxY + 20, boxX + 22, boxY + 6, 2, true);
    }
    renderer.drawText(UI_12_FONT_ID, boxX + boxSize + 12, boxY + 2, "Aide compteur de mines");
    renderer.drawText(UI_10_FONT_ID, boxX + boxSize + 12,
                      boxY + renderer.getLineHeight(UI_12_FONT_ID) + 4,
                      "Baisse seulement si le drapeau est juste.");
    if (selectedIndex_ == 0) {
      renderer.drawRect(setup.assistRow.x, setup.assistRow.y, setup.assistRow.width, setup.assistRow.height, 2, true);
    }

    renderer.fillRect(setup.startButton.x, setup.startButton.y, setup.startButton.width, setup.startButton.height, false);
    renderer.drawRect(setup.startButton.x, setup.startButton.y, setup.startButton.width, setup.startButton.height,
                      selectedIndex_ == 1 ? 3 : 1, true);
    const char* startLabel = "COMMENCER";
    const int startFont = UI_12_FONT_ID;
    const int startTextWidth = renderer.getTextWidth(startFont, startLabel);
    const int startTextHeight = renderer.getLineHeight(startFont);
    renderer.drawText(startFont,
                      setup.startButton.x + std::max(2, (setup.startButton.width - startTextWidth) / 2),
                      setup.startButton.y + std::max(1, (setup.startButton.height - startTextHeight) / 2),
                      startLabel);

    const auto labels =
        mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
    GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
    renderer.displayBuffer();
    return;
  }

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
