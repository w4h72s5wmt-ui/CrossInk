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
  static constexpr int kPackedBytes = (kMaxCells + 7) / 8;
  static constexpr unsigned long kFlagHoldMs = 700;

  struct CellBits {
    class Reference {
     public:
      Reference(CellBits& owner, const int index) : owner_(owner), index_(index) {}
      Reference& operator=(const bool value) {
        owner_.set(index_, value);
        return *this;
      }
      Reference& operator=(const Reference& other) { return *this = static_cast<bool>(other); }
      operator bool() const { return owner_.get(index_); }

     private:
      CellBits& owner_;
      int index_;
    };

    std::array<uint8_t, kPackedBytes> bytes{};

    bool get(const int index) const {
      return (bytes[static_cast<size_t>(index >> 3)] & static_cast<uint8_t>(1u << (index & 7))) != 0;
    }
    void set(const int index, const bool value = true) {
      auto& byte = bytes[static_cast<size_t>(index >> 3)];
      const uint8_t mask = static_cast<uint8_t>(1u << (index & 7));
      if (value) {
        byte = static_cast<uint8_t>(byte | mask);
      } else {
        byte = static_cast<uint8_t>(byte & static_cast<uint8_t>(~mask));
      }
    }
    void fill(const uint8_t value) { bytes.fill(value ? 0xFF : 0); }
    Reference operator[](const int index) { return Reference(*this, index); }
    bool operator[](const int index) const { return get(index); }
    uint8_t* data() { return bytes.data(); }
    const uint8_t* data() const { return bytes.data(); }
    bool any() const {
      for (const uint8_t byte : bytes) {
        if (byte != 0) return true;
      }
      return false;
    }
  };

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

  CellBits mines_{};
  CellBits revealed_{};
  CellBits flagged_{};
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
