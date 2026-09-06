#pragma once

#include <FreeInkApp.h>
#include <FreeInkUIGfxRenderer.h>

#include <array>
#include <atomic>
#include <cstdint>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class MinesweeperActivity final : public Activity {
 public:
  MinesweeperActivity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  using UiApp = freeink::ui::FreeInkApp<20, 4>;

  static constexpr int kGridOptionCount = 4;
  static constexpr int kMenuRowCount = 7;
  static constexpr int kMaxCells = 16 * 16;
  static constexpr unsigned long kFlagHoldMs = 700;

  enum class ViewMode {
    Menu,
    Grid,
    Result,
  };

  ButtonNavigator buttonNavigator_;
  freeink::ui::GfxRendererTarget uiTarget_;
  UiApp app_;
  std::atomic<bool> uiReady_{false};

  ViewMode viewMode_ = ViewMode::Menu;
  int selectedIndex_ = 0;
  int gridSizeIndex_ = 0;
  int visibleRows_ = 1;
  int topIndex_ = 0;
  bool initialViewportPending_ = true;
  int selectedCellIndex_ = 0;

  std::array<uint8_t, kMaxCells> mines_{};
  std::array<uint8_t, kMaxCells> revealed_{};
  std::array<uint8_t, kMaxCells> flagged_{};
  bool minesPlaced_ = false;
  bool gameOver_ = false;
  bool won_ = false;
  bool hasSavedGame_ = false;
  bool confirmHoldHandled_ = false;
  int revealedSafeCells_ = 0;

  static void menuScreen(UiApp::ScreenType& screen, void* user);
  static void onRowEvent(const freeink::ui::ActionEvent& event, void* user);

  void buildMenuScreen(UiApp::ScreenType& screen);
  void activateRow(int row);
  void showInfo(const char* title, const char* body);
  void continueGame();
  void newGame();
  void enterGrid();
  void returnToMenu();
  void loopMenu();
  void loopGrid();
  void loopResult();
  void renderMenu();
  void renderGrid();
  void renderResult();

  int gridDimension() const;
  int mineCount() const;
  int totalCells() const;
  int adjacentMineCount(int index) const;
  bool isValidCell(int row, int col) const;
  void resetGame();
  void placeMines(int firstIndex);
  void revealCell(int index);
  void revealFlood(int startIndex);
  void toggleFlag(int index);
  void checkWin();
  void finishGame(bool won);

  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
};
