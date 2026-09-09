#include "Game2048Activity.h"

#include <GfxRenderer.h>
#include <esp_random.h>

#include <algorithm>
#include <array>
#include <cstdio>

#include "MappedInputManager.h"
#include "fontIds.h"

Game2048Activity::Game2048Activity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("2048", renderer, mappedInput) {}

uint32_t Game2048Activity::tileValue(const uint8_t exponent) {
  if (exponent == 0) return 0;
  return 1u << std::min<uint8_t>(exponent, 30);
}

void Game2048Activity::onEnter() {
  Activity::onEnter();
  newGame();
  requestUpdate();
}

int Game2048Activity::indexFor(const Direction direction, const int line, const int offset) const {
  switch (direction) {
    case Direction::Left:
      return line * kSide + offset;
    case Direction::Right:
      return line * kSide + (kSide - 1 - offset);
    case Direction::Up:
      return offset * kSide + line;
    case Direction::Down:
      return (kSide - 1 - offset) * kSide + line;
  }
  return 0;
}

bool Game2048Activity::moveLine(const Direction direction, const int line) {
  std::array<uint8_t, kSide> compact{};
  std::array<uint8_t, kSide> merged{};
  int count = 0;
  for (int offset = 0; offset < kSide; ++offset) {
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
  for (int offset = 0; offset < kSide; ++offset) {
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
  if (gameOver_) return false;
  const uint32_t oldScore = score_;
  bool changed = false;
  for (int line = 0; line < kSide; ++line) changed = moveLine(direction, line) || changed;
  if (!changed) {
    score_ = oldScore;
    return false;
  }
  spawnTile();
  updateState();
  return true;
}

void Game2048Activity::spawnTile() {
  int emptyCount = 0;
  for (const uint8_t value : board_) {
    if (value == 0) ++emptyCount;
  }
  if (emptyCount == 0) return;

  int target = static_cast<int>(esp_random() % static_cast<uint32_t>(emptyCount));
  for (auto& value : board_) {
    if (value != 0) continue;
    if (target-- == 0) {
      value = (esp_random() % 10u == 0u) ? 2u : 1u;
      return;
    }
  }
}

bool Game2048Activity::hasMoves() const {
  for (int row = 0; row < kSide; ++row) {
    for (int col = 0; col < kSide; ++col) {
      const int index = row * kSide + col;
      const uint8_t value = board_[static_cast<size_t>(index)];
      if (value == 0) return true;
      if (col + 1 < kSide && board_[static_cast<size_t>(index + 1)] == value) return true;
      if (row + 1 < kSide && board_[static_cast<size_t>(index + kSide)] == value) return true;
    }
  }
  return false;
}

void Game2048Activity::updateState() {
  if (!won_) {
    for (const uint8_t value : board_) {
      if (value >= 11) {
        won_ = true;
        break;
      }
    }
  }
  gameOver_ = !hasMoves();
}

void Game2048Activity::newGame() {
  board_.fill(0);
  score_ = 0;
  resetHoldHandled_ = false;
  gameOver_ = false;
  won_ = false;
  spawnTile();
  spawnTile();
}

void Game2048Activity::loop() {
  if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
    return;
  }

  if (mappedInput.isPressed(MappedInputManager::Button::Confirm) && mappedInput.getHeldTime() >= kResetHoldMs &&
      !resetHoldHandled_) {
    resetHoldHandled_ = true;
    newGame();
    requestUpdate();
    return;
  }
  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) resetHoldHandled_ = false;

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

void Game2048Activity::render(RenderLock&&) {
  renderer.clearScreen();
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  const int margin = 18;
  const int headerHeight = 54;
  const int footerHeight = 44;
  const int availableHeight = screenHeight - headerHeight - footerHeight - 2 * margin;
  const int boardSize = std::min(screenWidth - 2 * margin, availableHeight);
  const int cellSize = boardSize / kSide;
  const int gridSize = cellSize * kSide;
  const int gridX = (screenWidth - gridSize) / 2;
  const int gridY = headerHeight + margin + std::max(0, (availableHeight - gridSize) / 2);

  renderer.drawText(LEXENDDECA_20_FONT_ID, margin, 12, "2048");
  char scoreText[32];
  std::snprintf(scoreText, sizeof(scoreText), "Score %lu", static_cast<unsigned long>(score_));
  const int scoreWidth = renderer.getTextWidth(UI_12_FONT_ID, scoreText);
  renderer.drawText(UI_12_FONT_ID, std::max(margin, screenWidth - margin - scoreWidth), 18, scoreText);

  for (int row = 0; row < kSide; ++row) {
    for (int col = 0; col < kSide; ++col) {
      const int index = row * kSide + col;
      const int x = gridX + col * cellSize;
      const int y = gridY + row * cellSize;
      const int gap = std::max(3, cellSize / 24);
      const int inner = std::max(1, cellSize - 2 * gap);
      renderer.drawRoundedRect(x + gap, y + gap, inner, inner, board_[static_cast<size_t>(index)] ? 2 : 1,
                               std::max(3, inner / 14), true);

      const uint8_t exponent = board_[static_cast<size_t>(index)];
      if (exponent == 0) continue;
      char valueText[16];
      std::snprintf(valueText, sizeof(valueText), "%lu", static_cast<unsigned long>(tileValue(exponent)));
      const int font = tileValue(exponent) < 1000 ? LEXENDDECA_20_FONT_ID : LEXENDDECA_16_FONT_ID;
      const int textWidth = renderer.getTextWidth(font, valueText);
      const int textHeight = renderer.getLineHeight(font);
      renderer.drawText(font, x + (cellSize - textWidth) / 2, y + (cellSize - textHeight) / 2, valueText);
    }
  }

  const char* status = gameOver_ ? "Partie terminee - maintien OK: nouvelle partie"
                                 : (won_ ? "2048 atteint ! Continuez." : "Glissez ou utilisez les directions");
  const int statusWidth = renderer.getTextWidth(UI_10_FONT_ID, status);
  renderer.drawText(UI_10_FONT_ID, std::max(4, (screenWidth - statusWidth) / 2), screenHeight - footerHeight, status);
  renderer.displayBuffer();
}
