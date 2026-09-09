#pragma once

#include <array>
#include <cstdint>

#include "activities/Activity.h"

class Game2048Activity final : public Activity {
 public:
  Game2048Activity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  enum class Direction : uint8_t { Left, Right, Up, Down };
  static constexpr int kSide = 4;
  static constexpr int kCellCount = 16;
  static constexpr unsigned long kResetHoldMs = 900;

  std::array<uint8_t, kCellCount> board_{};
  uint32_t score_ = 0;
  bool resetHoldHandled_ = false;
  bool gameOver_ = false;
  bool won_ = false;

  int indexFor(Direction direction, int line, int offset) const;
  bool move(Direction direction);
  bool moveLine(Direction direction, int line);
  void spawnTile();
  void newGame();
  bool hasMoves() const;
  void updateState();
  static uint32_t tileValue(uint8_t exponent);
};
