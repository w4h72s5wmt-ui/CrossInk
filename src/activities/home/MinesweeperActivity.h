#pragma once

#include <FreeInkApp.h>
#include <FreeInkUIGfxRenderer.h>

#include <atomic>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class MinesweeperActivity final : public Activity {
 public:
  MinesweeperActivity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  using UiApp = freeink::ui::FreeInkApp<20, 4>;

  static constexpr int kGridOptionCount = 3;
  static constexpr int kMenuRowCount = 5;

  enum class ViewMode {
    Menu,
    Grid,
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
  void renderMenu();
  void renderGrid();
  int gridDimension() const;
};
