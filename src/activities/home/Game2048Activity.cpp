#include "Game2048Activity.h"

#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <esp_random.h>
#include <esp_timer.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <memory>

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
constexpr const char SAVE_PATH[] = "/.crosspoint/2048.bin";
constexpr const char SCORE_PATH[] = "/.crosspoint/2048-scores.bin";
constexpr uint32_t SAVE_MAGIC = 0x32303438;  // "2048"
constexpr uint32_t SCORE_MAGIC = 0x32305343;  // "20SC"
constexpr uint8_t SAVE_VERSION = 1;
constexpr uint8_t SCORE_VERSION = 1;
constexpr int64_t LOSS_UNDO_WINDOW_US = 5LL * 1000LL * 1000LL;
constexpr int SCORE_TABLE_HEIGHT = 152;
constexpr int SCORE_RESET_GAP = 8;
constexpr int SCORE_RESET_BUTTON_HEIGHT = 44;
constexpr int SCORE_AREA_HEIGHT = SCORE_TABLE_HEIGHT + SCORE_RESET_GAP + SCORE_RESET_BUTTON_HEIGHT;

constexpr int GRID_SIZES[] = {3, 4, 5, 6};
constexpr const char* GRID_LABELS[] = {"3 x 3", "4 x 4", "5 x 5", "6 x 6"};

constexpr uint8_t TILE_DIGITS[10][5] = {
    {0b111, 0b101, 0b101, 0b101, 0b111},
    {0b010, 0b110, 0b010, 0b010, 0b111},
    {0b111, 0b001, 0b111, 0b100, 0b111},
    {0b111, 0b001, 0b111, 0b001, 0b111},
    {0b101, 0b101, 0b111, 0b001, 0b001},
    {0b111, 0b100, 0b111, 0b001, 0b111},
    {0b111, 0b100, 0b111, 0b101, 0b111},
    {0b111, 0b001, 0b001, 0b001, 0b001},
    {0b111, 0b101, 0b111, 0b101, 0b111},
    {0b111, 0b101, 0b111, 0b001, 0b111},
};

Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int height = mappedInput.hasTouchHardware() ? TouchHeaderBackButton::height(metrics, mappedInput)
                                                     : metrics.headerHeight;
  return Rect{0, metrics.topPadding, renderer.getScreenWidth(), height};
}

Rect menuListRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int contentTop = header.y + header.height + metrics.verticalSpacing;
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

bool pointInRect(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

struct GameGeometry {
  Rect header;
  Rect scoreBar;
  Rect leftScore;
  Rect undoButton;
  Rect rightScore;
  Rect grid;
  int cellSize = 1;
};

GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput, const int dimension) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  const Rect header = headerRect(renderer, mappedInput);
  const int contentTop = header.y + header.height + metrics.verticalSpacing;
  const int barHeight = std::max(54, renderer.getLineHeight(UI_12_FONT_ID) + 18);
  const Rect scoreBar{metrics.contentSidePadding, contentTop,
                      screenWidth - 2 * metrics.contentSidePadding, barHeight};

  const int gap = 6;
  const int undoSize = std::max(38, barHeight - 2 * gap);
  const int panelWidth = std::max(1, (scoreBar.width - undoSize - 4 * gap) / 2);
  const Rect leftScore{scoreBar.x + gap, scoreBar.y + gap, panelWidth, scoreBar.height - 2 * gap};
  const Rect undoButton{scoreBar.x + (scoreBar.width - undoSize) / 2, scoreBar.y + gap, undoSize, undoSize};
  const Rect rightScore{scoreBar.x + scoreBar.width - gap - panelWidth, scoreBar.y + gap,
                        panelWidth, scoreBar.height - 2 * gap};

  const int gridTop = scoreBar.y + scoreBar.height + metrics.verticalSpacing;
  const int footerTop = screenHeight - metrics.buttonHintsHeight;
  const int availableHeight = std::max(1, footerTop - gridTop - metrics.verticalSpacing);
  const int availableWidth = std::max(1, screenWidth - 2 * metrics.contentSidePadding);
  const int cellSize = std::max(1, std::min(availableWidth / dimension, availableHeight / dimension));
  const int gridWidth = cellSize * dimension;
  const int gridHeight = cellSize * dimension;
  const int gridX = (screenWidth - gridWidth) / 2;
  const int gridY = gridTop + std::max(0, (availableHeight - gridHeight) / 2);

  return GameGeometry{header, scoreBar, leftScore, undoButton, rightScore,
                      Rect{gridX, gridY, gridWidth, gridHeight}, cellSize};
}

Rect promptRect(const GfxRenderer& renderer) {
  const int width = std::min(380, renderer.getScreenWidth() - 36);
  const int height = 190;
  return Rect{(renderer.getScreenWidth() - width) / 2,
              (renderer.getScreenHeight() - height) / 2, width, height};
}

Rect winContinueButtonRect(const GfxRenderer& renderer) {
  const Rect prompt = promptRect(renderer);
  const int gap = 10;
  const int innerWidth = prompt.width - 40;
  const int buttonWidth = (innerWidth - gap) / 2;
  return Rect{prompt.x + 20, prompt.y + prompt.height - 58, buttonWidth, 42};
}

Rect winFinishButtonRect(const GfxRenderer& renderer) {
  const Rect left = winContinueButtonRect(renderer);
  return Rect{left.x + left.width + 10, left.y, left.width, left.height};
}

Rect lossButtonRect(const GfxRenderer& renderer) {
  const Rect prompt = promptRect(renderer);
  return Rect{prompt.x + 20, prompt.y + prompt.height - 58, prompt.width - 40, 42};
}

template <typename T>
bool writeValue(FsFile& file, const T& value) {
  return file.write(reinterpret_cast<const uint8_t*>(&value), sizeof(T)) == sizeof(T);
}

template <typename T>
bool readValue(FsFile& file, T& value) {
  return file.read(reinterpret_cast<uint8_t*>(&value), sizeof(T)) == static_cast<int>(sizeof(T));
}

void drawCenteredText(GfxRenderer& renderer, const int fontId, const Rect& rect, const char* text) {
  const int textWidth = renderer.getTextWidth(fontId, text);
  const int textHeight = renderer.getLineHeight(fontId);
  renderer.drawText(fontId, rect.x + std::max(0, (rect.width - textWidth) / 2),
                    rect.y + std::max(0, (rect.height - textHeight) / 2), text);
}

void drawTileValue(GfxRenderer& renderer, const int x, const int y, const int width, const int height,
                   const uint32_t value) {
  char text[16];
  std::snprintf(text, sizeof(text), "%lu", static_cast<unsigned long>(value));
  int digitCount = 0;
  while (digitCount < static_cast<int>(sizeof(text)) && text[digitCount] != '\0') ++digitCount;
  if (digitCount <= 0) return;

  const int widthUnits = digitCount * 3 + (digitCount - 1);
  const int padding = std::max(3, std::min(width, height) / 10);
  const int usableWidth = std::max(1, width - 2 * padding);
  const int usableHeight = std::max(1, height - 2 * padding);
  const int pixel = std::max(1, std::min(usableWidth / widthUnits, usableHeight / 5));
  const int glyphWidth = widthUnits * pixel;
  const int glyphHeight = 5 * pixel;
  const int startX = x + (width - glyphWidth) / 2;
  const int startY = y + (height - glyphHeight) / 2;

  for (int digit = 0; digit < digitCount; ++digit) {
    const int valueDigit = text[digit] - '0';
    if (valueDigit < 0 || valueDigit > 9) continue;
    const int digitX = startX + digit * 4 * pixel;
    for (int row = 0; row < 5; ++row) {
      const uint8_t bits = TILE_DIGITS[valueDigit][row];
      for (int col = 0; col < 3; ++col) {
        if ((bits & static_cast<uint8_t>(1u << (2 - col))) == 0) continue;
        renderer.fillRect(digitX + col * pixel, startY + row * pixel, pixel, pixel, true);
      }
    }
  }
}

void drawUndoIcon(GfxRenderer& renderer, const Rect& button, const bool enabled, const int undoCount) {
  const int cx = button.x + button.width / 2;
  const int cy = button.y + button.height / 2 - 2;
  const int half = std::max(8, button.width / 4);
  const int thickness = enabled ? 2 : 1;
  renderer.drawLine(cx - half, cy, cx + half, cy, thickness, true);
  renderer.drawLine(cx - half, cy, cx - half / 2, cy - half / 2, thickness, true);
  renderer.drawLine(cx - half, cy, cx - half / 2, cy + half / 2, thickness, true);
  if (enabled) {
    char countText[8];
    std::snprintf(countText, sizeof(countText), "x%d", undoCount);
    const int width = renderer.getTextWidth(UI_10_FONT_ID, countText);
    renderer.drawText(UI_10_FONT_ID, button.x + button.width - width - 3,
                      button.y + button.height - renderer.getLineHeight(UI_10_FONT_ID) - 1, countText);
  }
}
}  // namespace

Game2048Activity::Game2048Activity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("2048", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

uint32_t Game2048Activity::tileValue(const uint8_t exponent) {
  if (exponent == 0) return 0;
  return 1u << std::min<uint8_t>(exponent, 30);
}

void Game2048Activity::onEnter() {
  Activity::onEnter();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  promptSelection_ = 0;
  uiReady_ = false;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;

  loadBestScores();
  hasSavedGame_ = loadSavedGame();
  selectedIndex_ = gridSizeIndex_;

  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &Game2048Activity::onRowEvent, this);
  app_.setScreen(&Game2048Activity::menuScreen, this);
  requestUpdate();
}

void Game2048Activity::onExit() {
  if (viewMode_ == ViewMode::Grid || viewMode_ == ViewMode::WinPrompt) saveGame();
  if (viewMode_ == ViewMode::LossPrompt) clearSavedGame();
  flushBestScores();
  Activity::onExit();
}

void Game2048Activity::loop() {
  switch (viewMode_) {
    case ViewMode::Menu:
      loopMenu();
      break;
    case ViewMode::Grid:
      loopGrid();
      break;
    case ViewMode::WinPrompt:
      loopWinPrompt();
      break;
    case ViewMode::LossPrompt:
      loopLossPrompt();
      break;
  }
}

void Game2048Activity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(tx, ty) &&
      pointInRect(scoreResetButtonRect(renderer, mappedInput), tx, ty)) {
    startActivityForResult(
        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Reinitialiser les scores ?", ""),
        [this](const ActivityResult& result) {
          if (!result.isCancelled) {
            bestScores_.fill(0);
            scoresDirty_ = false;
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

void Game2048Activity::loopGrid() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput, gridDimension());
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(tx, ty) &&
      pointInRect(geometry.undoButton, tx, ty)) {
    if (undoLastMove()) requestUpdate();
    return;
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (undoLastMove()) requestUpdate();
    return;
  }

  Direction direction = Direction::Left;
  bool moveRequested = false;
  switch (mappedInput.wasSwipe()) {
    case MappedInputManager::SwipeDir::Left:
      direction = Direction::Left;
      moveRequested = true;
      break;
    case MappedInputManager::SwipeDir::Right:
      direction = Direction::Right;
      moveRequested = true;
      break;
    case MappedInputManager::SwipeDir::Up:
      direction = Direction::Up;
      moveRequested = true;
      break;
    case MappedInputManager::SwipeDir::Down:
      direction = Direction::Down;
      moveRequested = true;
      break;
    case MappedInputManager::SwipeDir::None:
      break;
  }

  if (!moveRequested && mappedInput.wasReleased(MappedInputManager::Button::Left)) {
    direction = Direction::Left;
    moveRequested = true;
  } else if (!moveRequested && mappedInput.wasReleased(MappedInputManager::Button::Right)) {
    direction = Direction::Right;
    moveRequested = true;
  } else if (!moveRequested && mappedInput.wasReleased(MappedInputManager::Button::Up)) {
    direction = Direction::Up;
    moveRequested = true;
  } else if (!moveRequested && mappedInput.wasReleased(MappedInputManager::Button::Down)) {
    direction = Direction::Down;
    moveRequested = true;
  }

  if (moveRequested && move(direction)) requestUpdate();
}

void Game2048Activity::loopWinPrompt() {
  if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    terminateWinToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty)) {
    if (pointInRect(winContinueButtonRect(renderer), tx, ty)) {
      continueAfterWin();
      return;
    }
    if (pointInRect(winFinishButtonRect(renderer), tx, ty)) {
      terminateWinToMenu();
      return;
    }
  }

  const auto swipe = mappedInput.wasSwipe();
  if (swipe == MappedInputManager::SwipeDir::Left ||
      mappedInput.wasReleased(MappedInputManager::Button::Left) ||
      mappedInput.wasReleased(MappedInputManager::Button::Up)) {
    promptSelection_ = 0;
    requestUpdate();
    return;
  }
  if (swipe == MappedInputManager::SwipeDir::Right ||
      mappedInput.wasReleased(MappedInputManager::Button::Right) ||
      mappedInput.wasReleased(MappedInputManager::Button::Down)) {
    promptSelection_ = 1;
    requestUpdate();
    return;
  }
  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (promptSelection_ == 0) {
      continueAfterWin();
    } else {
      terminateWinToMenu();
    }
  }
}

void Game2048Activity::loopLossPrompt() {
  if (!lossUndoExpired_ && lossUndoDeadlineUs_ > 0 && esp_timer_get_time() >= lossUndoDeadlineUs_) {
    lossUndoExpired_ = true;
    lossUndoDeadlineUs_ = 0;
    requestUpdate();
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finishLossToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  const bool touched = mappedInput.wasScreenTapped(tx, ty) && pointInRect(lossButtonRect(renderer), tx, ty);
  if (touched || mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (!lossUndoExpired_) {
      if (undoLastMove()) requestUpdate();
    } else {
      finishLossToMenu();
    }
  }
}

void Game2048Activity::activateRow(const int row) {
  if (row >= 0 && row < kGridOptionCount) {
    gridSizeIndex_ = row;
    selectedIndex_ = row;
    requestUpdate();
    return;
  }
  if (row == 4) {
    if (hasSavedGame_) continueGame();
    return;
  }
  if (row == 5) {
    if (!hasSavedGame_) {
      newGame();
      return;
    }
    startActivityForResult(
        std::make_unique<ConfirmationActivity>(renderer, mappedInput, "Effacer la partie en cours :", ""),
        [this](const ActivityResult& result) {
          if (result.isCancelled) {
            requestUpdate();
            return;
          }
          newGame();
        });
  }
}

void Game2048Activity::continueGame() {
  if (!loadSavedGame()) {
    hasSavedGame_ = false;
    requestUpdate();
    return;
  }
  enterGrid();
  if (!winAcknowledged_ && reached2048()) {
    beginWinPrompt();
  } else if (!hasMoves()) {
    beginLossPrompt();
  }
}

void Game2048Activity::newGame() {
  board_.fill(0);
  score_ = 0;
  winAcknowledged_ = false;
  gameOver_ = false;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  clearUndoHistory();
  clearSavedGame();
  spawnTile();
  spawnTile();
  enterGrid();
  saveGame();
}

void Game2048Activity::enterGrid() {
  viewMode_ = ViewMode::Grid;
  uiReady_ = false;
  gameOver_ = false;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  requestUpdate();
}

void Game2048Activity::returnToMenu() {
  saveGame();
  flushBestScores();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  promptSelection_ = 0;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  requestUpdate();
}

void Game2048Activity::beginWinPrompt() {
  viewMode_ = ViewMode::WinPrompt;
  promptSelection_ = 0;
  updateBestScore();
  saveGame();
  requestUpdate();
}

void Game2048Activity::beginLossPrompt() {
  gameOver_ = true;
  viewMode_ = ViewMode::LossPrompt;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = esp_timer_get_time() + LOSS_UNDO_WINDOW_US;
  updateBestScore();
  flushBestScores();
  clearSavedGame();
  requestUpdate();
}

void Game2048Activity::continueAfterWin() {
  winAcknowledged_ = true;
  viewMode_ = ViewMode::Grid;
  gameOver_ = false;
  saveGame();
  if (!hasMoves()) {
    beginLossPrompt();
    return;
  }
  requestUpdate();
}

void Game2048Activity::terminateWinToMenu() {
  updateBestScore();
  flushBestScores();
  clearSavedGame();
  clearUndoHistory();
  gameOver_ = true;
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  promptSelection_ = 0;
  requestUpdate();
}

void Game2048Activity::finishLossToMenu() {
  updateBestScore();
  flushBestScores();
  clearSavedGame();
  clearUndoHistory();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  requestUpdate();
}

int Game2048Activity::gridDimension() const {
  return GRID_SIZES[std::clamp(gridSizeIndex_, 0, kGridOptionCount - 1)];
}

int Game2048Activity::totalCells() const {
  const int side = gridDimension();
  return side * side;
}

int Game2048Activity::indexFor(const Direction direction, const int line, const int offset) const {
  const int side = gridDimension();
  switch (direction) {
    case Direction::Left:
      return line * side + offset;
    case Direction::Right:
      return line * side + (side - 1 - offset);
    case Direction::Up:
      return offset * side + line;
    case Direction::Down:
      return (side - 1 - offset) * side + line;
  }
  return 0;
}

bool Game2048Activity::moveLine(const Direction direction, const int line) {
  const int side = gridDimension();
  std::array<uint8_t, kMaxSide> compact{};
  std::array<uint8_t, kMaxSide> merged{};
  int count = 0;
  for (int offset = 0; offset < side; ++offset) {
    const uint8_t value = board_[static_cast<size_t>(indexFor(direction, line, offset))];
    if (value != 0) compact[static_cast<size_t>(count++)] = value;
  }

  int in = 0;
  int out = 0;
  while (in < count) {
    uint8_t value = compact[static_cast<size_t>(in)];
    if (in + 1 < count && compact[static_cast<size_t>(in + 1)] == value) {
      value = static_cast<uint8_t>(std::min<int>(30, value + 1));
      score_ += tileValue(value);
      in += 2;
    } else {
      ++in;
    }
    merged[static_cast<size_t>(out++)] = value;
  }

  bool changed = false;
  for (int offset = 0; offset < side; ++offset) {
    const int index = indexFor(direction, line, offset);
    const uint8_t value = merged[static_cast<size_t>(offset)];
    if (board_[static_cast<size_t>(index)] != value) {
      board_[static_cast<size_t>(index)] = value;
      changed = true;
    }
  }
  return changed;
}

bool Game2048Activity::move(const Direction direction) {
  if (viewMode_ != ViewMode::Grid || gameOver_) return false;

  Snapshot before;
  before.board = board_;
  before.score = score_;
  before.winAcknowledged = winAcknowledged_;

  const uint32_t oldScore = score_;
  bool changed = false;
  const int side = gridDimension();
  for (int line = 0; line < side; ++line) changed = moveLine(direction, line) || changed;
  if (!changed) {
    score_ = oldScore;
    return false;
  }

  pushUndoSnapshot(before);
  spawnTile();
  updateBestScore();
  updateAfterMove();
  return true;
}

void Game2048Activity::spawnTile() {
  const int cellCount = totalCells();
  int emptyCount = 0;
  for (int i = 0; i < cellCount; ++i) {
    if (board_[static_cast<size_t>(i)] == 0) ++emptyCount;
  }
  if (emptyCount == 0) return;

  int target = static_cast<int>(esp_random() % static_cast<uint32_t>(emptyCount));
  for (int i = 0; i < cellCount; ++i) {
    auto& value = board_[static_cast<size_t>(i)];
    if (value != 0) continue;
    if (target-- == 0) {
      value = (esp_random() % 10u == 0u) ? 2u : 1u;
      return;
    }
  }
}

bool Game2048Activity::hasMoves() const {
  const int side = gridDimension();
  for (int row = 0; row < side; ++row) {
    for (int col = 0; col < side; ++col) {
      const int index = row * side + col;
      const uint8_t value = board_[static_cast<size_t>(index)];
      if (value == 0) return true;
      if (col + 1 < side && board_[static_cast<size_t>(index + 1)] == value) return true;
      if (row + 1 < side && board_[static_cast<size_t>(index + side)] == value) return true;
    }
  }
  return false;
}

bool Game2048Activity::reached2048() const {
  const int cellCount = totalCells();
  for (int i = 0; i < cellCount; ++i) {
    if (board_[static_cast<size_t>(i)] >= 11) return true;
  }
  return false;
}

void Game2048Activity::updateAfterMove() {
  if (!winAcknowledged_ && reached2048()) {
    beginWinPrompt();
    return;
  }
  if (!hasMoves()) {
    beginLossPrompt();
    return;
  }
  viewMode_ = ViewMode::Grid;
}

void Game2048Activity::clearUndoHistory() {
  undoHistory_ = {};
  undoCount_ = 0;
}

void Game2048Activity::pushUndoSnapshot(const Snapshot& snapshot) {
  if (undoCount_ < kUndoDepth) {
    undoHistory_[static_cast<size_t>(undoCount_++)] = snapshot;
    return;
  }
  for (int i = 1; i < kUndoDepth; ++i) {
    undoHistory_[static_cast<size_t>(i - 1)] = undoHistory_[static_cast<size_t>(i)];
  }
  undoHistory_[kUndoDepth - 1] = snapshot;
}

bool Game2048Activity::undoLastMove() {
  if (undoCount_ <= 0) return false;
  const Snapshot& snapshot = undoHistory_[static_cast<size_t>(undoCount_ - 1)];
  board_ = snapshot.board;
  score_ = snapshot.score;
  winAcknowledged_ = snapshot.winAcknowledged;
  --undoCount_;
  gameOver_ = false;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  viewMode_ = ViewMode::Grid;
  saveGame();
  return true;
}

bool Game2048Activity::saveGame() {
  if (gameOver_ || viewMode_ == ViewMode::LossPrompt) return false;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("2048", SAVE_PATH, file)) return false;

  const uint8_t grid = static_cast<uint8_t>(std::clamp(gridSizeIndex_, 0, kGridOptionCount - 1));
  const uint8_t flags = winAcknowledged_ ? 0x01 : 0x00;
  const uint8_t historyCount = static_cast<uint8_t>(std::clamp(undoCount_, 0, kUndoDepth));

  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, grid) &&
            writeValue(file, flags) && writeValue(file, historyCount) && writeValue(file, score_);
  if (ok) ok = file.write(board_.data(), board_.size()) == board_.size();
  for (int i = 0; i < kUndoDepth && ok; ++i) {
    const Snapshot& snapshot = undoHistory_[static_cast<size_t>(i)];
    const uint8_t snapshotFlags = snapshot.winAcknowledged ? 0x01 : 0x00;
    ok = writeValue(file, snapshot.score) && writeValue(file, snapshotFlags);
    if (ok) ok = file.write(snapshot.board.data(), snapshot.board.size()) == snapshot.board.size();
  }
  file.close();

  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    return false;
  }
  hasSavedGame_ = true;
  return true;
}

bool Game2048Activity::loadSavedGame() {
  if (!Storage.exists(SAVE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("2048", SAVE_PATH, file)) return false;

  constexpr size_t expectedSize = sizeof(uint32_t) + 4 * sizeof(uint8_t) + sizeof(uint32_t) + kMaxCells +
                                  kUndoDepth * (sizeof(uint32_t) + sizeof(uint8_t) + kMaxCells);
  if (file.size() != expectedSize) {
    file.close();
    clearSavedGame();
    return false;
  }

  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t grid = 0;
  uint8_t flags = 0;
  uint8_t historyCount = 0;
  uint32_t savedScore = 0;
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, grid) &&
            readValue(file, flags) && readValue(file, historyCount) && readValue(file, savedScore);
  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || grid >= kGridOptionCount ||
      historyCount > kUndoDepth || (flags & static_cast<uint8_t>(~0x01u)) != 0) {
    file.close();
    clearSavedGame();
    return false;
  }

  std::array<uint8_t, kMaxCells> loadedBoard{};
  std::array<Snapshot, kUndoDepth> loadedHistory{};
  ok = file.read(loadedBoard.data(), loadedBoard.size()) == static_cast<int>(loadedBoard.size());
  for (int i = 0; i < kUndoDepth && ok; ++i) {
    uint8_t snapshotFlags = 0;
    ok = readValue(file, loadedHistory[static_cast<size_t>(i)].score) && readValue(file, snapshotFlags);
    if (!ok || (snapshotFlags & static_cast<uint8_t>(~0x01u)) != 0) {
      ok = false;
      break;
    }
    loadedHistory[static_cast<size_t>(i)].winAcknowledged = (snapshotFlags & 0x01) != 0;
    ok = file.read(loadedHistory[static_cast<size_t>(i)].board.data(),
                   loadedHistory[static_cast<size_t>(i)].board.size()) ==
         static_cast<int>(loadedHistory[static_cast<size_t>(i)].board.size());
  }
  file.close();

  if (!ok) {
    clearSavedGame();
    return false;
  }

  const int side = GRID_SIZES[grid];
  const int cellCount = side * side;
  auto validBoard = [cellCount](const std::array<uint8_t, kMaxCells>& candidate) {
    for (int i = 0; i < kMaxCells; ++i) {
      if (candidate[static_cast<size_t>(i)] > 30) return false;
      if (i >= cellCount && candidate[static_cast<size_t>(i)] != 0) return false;
    }
    return true;
  };
  if (!validBoard(loadedBoard)) {
    clearSavedGame();
    return false;
  }
  for (int i = 0; i < historyCount; ++i) {
    if (!validBoard(loadedHistory[static_cast<size_t>(i)].board)) {
      clearSavedGame();
      return false;
    }
  }

  gridSizeIndex_ = grid;
  board_ = loadedBoard;
  undoHistory_ = loadedHistory;
  undoCount_ = historyCount;
  score_ = savedScore;
  winAcknowledged_ = (flags & 0x01) != 0;
  gameOver_ = false;
  lossUndoExpired_ = false;
  lossUndoDeadlineUs_ = 0;
  hasSavedGame_ = true;
  updateBestScore();
  return true;
}

void Game2048Activity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
}

bool Game2048Activity::loadBestScores() {
  bestScores_.fill(0);
  scoresDirty_ = false;
  if (!Storage.exists(SCORE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("2048", SCORE_PATH, file)) return false;

  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t count = 0;
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, count);
  if (!ok || magic != SCORE_MAGIC || version != SCORE_VERSION || count != kGridOptionCount) {
    file.close();
    bestScores_.fill(0);
    return false;
  }
  for (int i = 0; i < kGridOptionCount && ok; ++i) ok = readValue(file, bestScores_[static_cast<size_t>(i)]);
  file.close();
  if (!ok) bestScores_.fill(0);
  return ok;
}

bool Game2048Activity::saveBestScores() {
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("2048", SCORE_PATH, file)) return false;
  const uint8_t count = kGridOptionCount;
  bool ok = writeValue(file, SCORE_MAGIC) && writeValue(file, SCORE_VERSION) && writeValue(file, count);
  for (int i = 0; i < kGridOptionCount && ok; ++i) ok = writeValue(file, bestScores_[static_cast<size_t>(i)]);
  file.close();
  if (ok) scoresDirty_ = false;
  return ok;
}

void Game2048Activity::flushBestScores() {
  if (!scoresDirty_) return;
  saveBestScores();
}

void Game2048Activity::updateBestScore() {
  if (gridSizeIndex_ < 0 || gridSizeIndex_ >= kGridOptionCount) return;
  auto& best = bestScores_[static_cast<size_t>(gridSizeIndex_)];
  if (score_ <= best) return;
  best = score_;
  scoresDirty_ = true;
}

void Game2048Activity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<Game2048Activity*>(user);
  if (event.value < 0 || event.value >= kMenuRowCount) return;
  self->selectedIndex_ = event.value;
  self->app_.clearTapFlash();
  self->activateRow(event.value);
}

void Game2048Activity::menuScreen(UiApp::ScreenType& screen, void* user) {
  static_cast<Game2048Activity*>(user)->buildMenuScreen(screen);
}

void Game2048Activity::buildMenuScreen(UiApp::ScreenType& screen) {
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
  items[4].label = "Continuer";
  items[4].value = hasSavedGame_ ? "Partie sauvegardee" : "Aucune partie";
  items[4].actionValue = 4;
  items[5].label = "Nouvelle partie";
  items[5].value = GRID_LABELS[gridSizeIndex_];
  items[5].actionValue = 5;

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

void Game2048Activity::render(RenderLock&&) {
  switch (viewMode_) {
    case ViewMode::Menu:
      renderMenu();
      break;
    case ViewMode::Grid:
      renderGrid();
      break;
    case ViewMode::WinPrompt:
      renderWinPrompt();
      break;
    case ViewMode::LossPrompt:
      renderLossPrompt();
      break;
  }
}

void Game2048Activity::renderMenu() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "2048", false);
  } else {
    GUI.drawHeader(renderer, header, "2048", nullptr, false);
  }

  uiReady_ = false;
  app_.render();
  uiReady_ = true;

  const Rect listBounds = menuListRect(renderer, mappedInput);
  const int drawnRows = std::max(1, visibleRows_);
  const int boxSize = 22;
  const int innerSize = 10;
  const int boxX = renderer.getScreenWidth() - UITheme::getInstance().getMetrics().contentSidePadding - boxSize - 10;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex < 0 || itemIndex >= kGridOptionCount) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    if (itemIndex == gridSizeIndex_) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
  }

  const auto& menuMetrics = UITheme::getInstance().getMetrics();
  constexpr int actionInsetY = 4;
  const int actionX = menuMetrics.contentSidePadding;
  const int actionWidth = renderer.getScreenWidth() - 2 * menuMetrics.contentSidePadding;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex != 4 && itemIndex != 5) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    renderer.drawRoundedRect(actionX, rowTop + actionInsetY, actionWidth,
                             std::max(1, rowBottom - rowTop - 2 * actionInsetY), 1, 6, true);
  }

  if (!hasSavedGame_) {
    for (int visible = 0; visible < drawnRows; ++visible) {
      if (topIndex_ + visible != 4) continue;
      const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
      const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
      const int actionY = rowTop + actionInsetY;
      const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);
      for (int y = actionY; y < actionY + actionHeight; y += 2) {
        renderer.fillRect(actionX, y, actionWidth, 1, false);
      }
    }
  }

  const Rect scorePanel = scoreTableRect(renderer, mappedInput);
  renderer.fillRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, false);
  renderer.drawRect(scorePanel.x, scorePanel.y, scorePanel.width, scorePanel.height, 1, true);
  const int headerRowHeight = 30;
  const int dataTop = scorePanel.y + headerRowHeight;
  const int dataHeight = scorePanel.height - headerRowHeight;
  const int splitX = scorePanel.x + scorePanel.width / 2;
  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);
  renderer.drawLine(splitX, dataTop, splitX, scorePanel.y + scorePanel.height, 1, true);
  drawCenteredText(renderer, UI_12_FONT_ID,
                   Rect{scorePanel.x, scorePanel.y, scorePanel.width, headerRowHeight}, "Meilleurs scores");

  for (int row = 0; row < kGridOptionCount; ++row) {
    const int rowY = dataTop + dataHeight * row / kGridOptionCount;
    const int nextRowY = dataTop + dataHeight * (row + 1) / kGridOptionCount;
    const int rowHeight = nextRowY - rowY;
    if (row > 0) renderer.drawLine(scorePanel.x, rowY, scorePanel.x + scorePanel.width, rowY, 1, true);
    char scoreValue[20];
    std::snprintf(scoreValue, sizeof(scoreValue), "%lu",
                  static_cast<unsigned long>(bestScores_[static_cast<size_t>(row)]));
    drawCenteredText(renderer, UI_10_FONT_ID,
                     Rect{scorePanel.x, rowY, splitX - scorePanel.x, rowHeight}, GRID_LABELS[row]);
    drawCenteredText(renderer, UI_10_FONT_ID,
                     Rect{splitX, rowY, scorePanel.x + scorePanel.width - splitX, rowHeight}, scoreValue);
  }

  const Rect resetButton = scoreResetButtonRect(renderer, mappedInput);
  renderer.fillRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, false);
  renderer.drawRoundedRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, resetButton, "Reinitialiser les scores");

  const auto labels =
      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}

void Game2048Activity::renderGameSurface(const bool drawHints) {
  renderer.clearScreen();
  const int dimension = gridDimension();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput, dimension);

  char title[32];
  std::snprintf(title, sizeof(title), "2048 - %s", GRID_LABELS[gridSizeIndex_]);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, title, false);
  } else {
    GUI.drawHeader(renderer, geometry.header, title, nullptr, false);
  }

  renderer.fillRect(geometry.scoreBar.x, geometry.scoreBar.y, geometry.scoreBar.width, geometry.scoreBar.height, false);
  renderer.drawRect(geometry.scoreBar.x, geometry.scoreBar.y, geometry.scoreBar.width, geometry.scoreBar.height, 1, true);
  renderer.drawRect(geometry.leftScore.x, geometry.leftScore.y, geometry.leftScore.width, geometry.leftScore.height, 1, true);
  renderer.drawRect(geometry.rightScore.x, geometry.rightScore.y, geometry.rightScore.width, geometry.rightScore.height, 1, true);
  renderer.drawRoundedRect(geometry.undoButton.x, geometry.undoButton.y, geometry.undoButton.width,
                           geometry.undoButton.height, undoCount_ > 0 ? 2 : 1, 6, true);

  char currentText[32];
  char bestText[32];
  std::snprintf(currentText, sizeof(currentText), "Score %lu", static_cast<unsigned long>(score_));
  std::snprintf(bestText, sizeof(bestText), "Meilleur %lu",
                static_cast<unsigned long>(bestScores_[static_cast<size_t>(gridSizeIndex_)]));
  drawCenteredText(renderer, UI_10_FONT_ID, geometry.leftScore, currentText);
  drawCenteredText(renderer, UI_10_FONT_ID, geometry.rightScore, bestText);
  drawUndoIcon(renderer, geometry.undoButton, undoCount_ > 0, undoCount_);

  renderer.drawRect(geometry.grid.x, geometry.grid.y, geometry.grid.width + 1, geometry.grid.height + 1, 1, true);
  for (int row = 0; row < dimension; ++row) {
    for (int col = 0; col < dimension; ++col) {
      const int index = row * dimension + col;
      const int x = geometry.grid.x + col * geometry.cellSize;
      const int y = geometry.grid.y + row * geometry.cellSize;
      const int gap = std::max(2, geometry.cellSize / 24);
      const int inner = std::max(1, geometry.cellSize - 2 * gap);
      const uint8_t exponent = board_[static_cast<size_t>(index)];
      renderer.fillRect(x + gap, y + gap, inner, inner, false);
      renderer.drawRoundedRect(x + gap, y + gap, inner, inner, exponent ? 2 : 1,
                               std::max(3, inner / 14), true);
      if (exponent != 0) drawTileValue(renderer, x + gap, y + gap, inner, inner, tileValue(exponent));
    }
  }

  if (drawHints) {
    const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "Annuler",
                                               tr(STR_DIR_UP), tr(STR_DIR_DOWN));
    GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  }
}

void Game2048Activity::renderGrid() {
  renderGameSurface(true);
  renderer.displayBuffer();
}

void Game2048Activity::renderWinPrompt() {
  renderGameSurface(false);
  const Rect prompt = promptRect(renderer);
  renderer.fillRect(prompt.x, prompt.y, prompt.width, prompt.height, false);
  renderer.drawRoundedRect(prompt.x, prompt.y, prompt.width, prompt.height, 2, 8, true);

  drawCenteredText(renderer, UI_12_FONT_ID, Rect{prompt.x + 10, prompt.y + 18, prompt.width - 20, 32},
                   "2048 atteint !");
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{prompt.x + 10, prompt.y + 58, prompt.width - 20, 30},
                   "Continuer la partie ?");

  const Rect continueButton = winContinueButtonRect(renderer);
  const Rect finishButton = winFinishButtonRect(renderer);
  renderer.drawRoundedRect(continueButton.x, continueButton.y, continueButton.width, continueButton.height,
                           promptSelection_ == 0 ? 2 : 1, 6, true);
  renderer.drawRoundedRect(finishButton.x, finishButton.y, finishButton.width, finishButton.height,
                           promptSelection_ == 1 ? 2 : 1, 6, true);
  if (promptSelection_ == 0) {
    renderer.drawRect(continueButton.x + 3, continueButton.y + 3, continueButton.width - 6,
                      continueButton.height - 6, 1, true);
  } else {
    renderer.drawRect(finishButton.x + 3, finishButton.y + 3, finishButton.width - 6,
                      finishButton.height - 6, 1, true);
  }
  drawCenteredText(renderer, UI_10_FONT_ID, continueButton, "Continuer");
  drawCenteredText(renderer, UI_10_FONT_ID, finishButton, "Terminer");
  renderer.displayBuffer();
}

void Game2048Activity::renderLossPrompt() {
  renderGameSurface(false);
  const Rect prompt = promptRect(renderer);
  renderer.fillRect(prompt.x, prompt.y, prompt.width, prompt.height, false);
  renderer.drawRoundedRect(prompt.x, prompt.y, prompt.width, prompt.height, 2, 8, true);
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{prompt.x + 10, prompt.y + 18, prompt.width - 20, 32}, "Perdu !");

  char scoreText[40];
  std::snprintf(scoreText, sizeof(scoreText), "Score : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{prompt.x + 10, prompt.y + 58, prompt.width - 20, 30}, scoreText);

  const Rect button = lossButtonRect(renderer);
  renderer.drawRoundedRect(button.x, button.y, button.width, button.height, 2, 6, true);
  drawCenteredText(renderer, UI_12_FONT_ID, button, lossUndoExpired_ ? "Menu" : "Annuler (5 s)");
  renderer.displayBuffer();
}
