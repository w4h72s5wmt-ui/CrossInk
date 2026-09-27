#pragma once

#include <FreeInkApp.h>
#include <FreeInkUIGfxRenderer.h>

#include <array>
#include <atomic>
#include <cstdint>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class Game2048Activity final : public Activity {
 public:
  Game2048Activity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  using UiApp = freeink::ui::FreeInkApp<20, 4>;

  static constexpr int kGridOptionCount = 4;
  static constexpr int kMenuRowCount = 6;
  static constexpr int kMaxSide = 6;
  static constexpr int kMaxCells = kMaxSide * kMaxSide;
  static constexpr int kUndoDepth = 4;

  enum class Direction : uint8_t { Left, Right, Up, Down };
  enum class ViewMode : uint8_t { Menu, Grid, WinPrompt, LossPrompt };

  struct Snapshot {
    std::array<uint8_t, kMaxCells> board{};
    uint32_t score = 0;
    bool winAcknowledged = false;
  };

  ButtonNavigator buttonNavigator_;
  freeink::ui::GfxRendererTarget uiTarget_;
  UiApp app_;
  std::atomic<bool> uiReady_{false};

  ViewMode viewMode_ = ViewMode::Menu;
  int selectedIndex_ = 1;
  int gridSizeIndex_ = 1;
  int visibleRows_ = 1;
  int topIndex_ = 0;
  bool initialViewportPending_ = true;
  int promptSelection_ = 0;

  std::array<uint8_t, kMaxCells> board_{};
  std::array<Snapshot, kUndoDepth> undoHistory_{};
  std::array<uint32_t, kGridOptionCount> bestScores_{};
  uint32_t score_ = 0;
  int undoCount_ = 0;
  bool hasSavedGame_ = false;
  bool winAcknowledged_ = false;
  bool gameOver_ = false;
  bool scoresDirty_ = false;
  bool lossUndoExpired_ = false;
  int64_t lossUndoDeadlineUs_ = 0;

  static void menuScreen(UiApp::ScreenType& screen, void* user);
  static void onRowEvent(const freeink::ui::ActionEvent& event, void* user);

  void buildMenuScreen(UiApp::ScreenType& screen);
  void activateRow(int row);
  void continueGame();
  void newGame();
  void enterGrid();
  void returnToMenu();
  void beginWinPrompt();
  void beginLossPrompt();
  void continueAfterWin();
  void terminateWinToMenu();
  void finishLossToMenu();

  void loopMenu();
  void loopGrid();
  void loopWinPrompt();
  void loopLossPrompt();

  void renderMenu();
  void renderGrid();
  void renderWinPrompt();
  void renderLossPrompt();
  void renderGameSurface(bool drawHints);

  int gridDimension() const;
  int totalCells() const;
  int indexFor(Direction direction, int line, int offset) const;
  bool move(Direction direction);
  bool moveLine(Direction direction, int line);
  void spawnTile();
  bool hasMoves() const;
  bool reached2048() const;
  void updateAfterMove();

  void clearUndoHistory();
  void pushUndoSnapshot(const Snapshot& snapshot);
  bool undoLastMove();

  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
  bool loadBestScores();
  bool saveBestScores();
  void flushBestScores();
  void updateBestScore();

  static uint32_t tileValue(uint8_t exponent);
};
