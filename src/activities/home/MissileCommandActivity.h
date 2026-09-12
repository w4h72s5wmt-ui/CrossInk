#pragma once

#include <FreeInkApp.h>
#include <FreeInkUIGfxRenderer.h>

#include <array>
#include <atomic>
#include <cstdint>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class MissileCommandActivity final : public Activity {
 public:
  MissileCommandActivity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;
  bool skipLoopDelay() override { return viewMode_ == ViewMode::Playing; }
  bool preventAutoSleep() override { return viewMode_ == ViewMode::Playing; }

 private:
  using UiApp = freeink::ui::FreeInkApp<16, 4>;

  static constexpr int kMenuRowCount = 5;
  static constexpr int kDifficultyCount = 3;
  static constexpr int kCityCount = 6;
  static constexpr int kBatteryCount = 3;
  static constexpr int kMaxEnemyMissiles = 12;
  static constexpr int kMaxPlayerMissiles = 8;
  static constexpr int kMaxExplosions = 8;

  enum class ViewMode : uint8_t { Menu, Playing, GameOver };

  struct Missile {
    int16_t startX = 0;
    int16_t startY = 0;
    int16_t targetX = 0;
    int16_t targetY = 0;
    uint16_t progress = 0;
    uint16_t speed = 0;
    bool active = false;
  };


  struct BenchmarkAccumulator {
    uint32_t frames = 0;
    uint64_t logicSumUs = 0;
    uint64_t drawSumUs = 0;
    uint64_t refreshSumUs = 0;
    uint64_t cycleSumUs = 0;
    uint64_t workSumUs = 0;
    uint32_t logicMinUs = 0xFFFFFFFFu;
    uint32_t logicMaxUs = 0;
    uint32_t drawMinUs = 0xFFFFFFFFu;
    uint32_t drawMaxUs = 0;
    uint32_t refreshMinUs = 0xFFFFFFFFu;
    uint32_t refreshMaxUs = 0;
    uint32_t cycleMinUs = 0xFFFFFFFFu;
    uint32_t cycleMaxUs = 0;
    uint32_t workMaxUs = 0;
    uint32_t overBudgetFrames = 0;
  };

  struct BenchmarkSnapshot {
    uint32_t elapsedMs = 0;
    uint16_t wave = 0;
    uint32_t score = 0;
    uint32_t frames = 0;
    uint32_t cycleMinUs = 0;
    uint32_t cycleAvgUs = 0;
    uint32_t cycleMaxUs = 0;
    uint32_t logicMinUs = 0;
    uint32_t logicAvgUs = 0;
    uint32_t logicMaxUs = 0;
    uint32_t drawMinUs = 0;
    uint32_t drawAvgUs = 0;
    uint32_t drawMaxUs = 0;
    uint32_t refreshMinUs = 0;
    uint32_t refreshAvgUs = 0;
    uint32_t refreshMaxUs = 0;
    uint32_t workAvgUs = 0;
    uint32_t workMaxUs = 0;
    uint32_t overBudgetFrames = 0;
  };

  struct Explosion {
    int16_t x = 0;
    int16_t y = 0;
    uint8_t phase = 0;
    uint8_t phaseTicks = 0;
    bool active = false;
  };

  ButtonNavigator buttonNavigator_;
  freeink::ui::GfxRendererTarget uiTarget_;
  UiApp app_;
  std::atomic<bool> uiReady_{false};

  ViewMode viewMode_ = ViewMode::Menu;
  int selectedIndex_ = 0;
  int difficulty_ = 1;
  int visibleRows_ = 1;
  int topIndex_ = 0;
  bool initialViewportPending_ = true;
  std::array<char, 40> continueValue_{};

  std::array<Missile, kMaxEnemyMissiles> enemies_{};
  std::array<Missile, kMaxPlayerMissiles> players_{};
  std::array<Explosion, kMaxExplosions> explosions_{};
  std::array<uint8_t, kCityCount> citiesAlive_{};
  std::array<uint8_t, kBatteryCount> ammo_{};

  uint32_t score_ = 0;
  uint32_t highScore_ = 0;
  uint16_t wave_ = 1;
  uint16_t enemiesSpawned_ = 0;
  uint16_t enemiesResolved_ = 0;
  int64_t lastCycleUs_ = 0;
  int64_t nextSpawnUs_ = 0;
  bool hasSavedGame_ = false;
  bool sceneNeedsFullRedraw_ = true;

  // Main task captures touch into the next frame; render task clears this only
  // after the blocking FAST refresh completes. This enforces a strict 1:1
  // relationship between input, simulation state and the visible e-ink frame.
  std::atomic<bool> cycleRenderPending_{false};
  bool pendingTap_ = false;
  int16_t pendingTapX_ = 0;
  int16_t pendingTapY_ = 0;
  bool pendingBack_ = false;

  // Timing samples cross the main gameplay task and the render task. Only a
  // completed, synchronized frame becomes a benchmark sample.
  std::atomic<uint32_t> lastLogicUs_{0};
  std::atomic<uint32_t> lastCycleIntervalUs_{0};
  std::atomic<bool> benchmarkSampleArmed_{false};
  std::atomic<bool> benchmarkFlushPending_{false};
  BenchmarkAccumulator benchmarkAccum_{};
  BenchmarkSnapshot benchmarkSnapshot_{};
  int64_t benchmarkSessionStartUs_ = 0;
  bool benchmarkLogOpen_ = false;

  static void menuScreen(UiApp::ScreenType& screen, void* user);
  static void onRowEvent(const freeink::ui::ActionEvent& event, void* user);

  void buildMenuScreen(UiApp::ScreenType& screen);
  void activateRow(int row);
  void loopMenu();
  void loopPlaying();
  void loopGameOver();
  void renderMenu();
  void renderPlaying();
  void renderGameOver();
  void drawFullPlayingScene();
  void drawPlayingFrame();

  void resetBenchmarkAccumulator();
  bool openBenchmarkLog();
  void closeBenchmarkLog();
  void recordBenchmarkSample(uint32_t logicUs, uint32_t drawUs, uint32_t refreshUs, uint32_t cycleUs);
  void flushBenchmarkLog();

  void newGame();
  void continueGame();
  void returnToMenu();
  void startWave();
  void tickGame(int64_t nowUs);
  void spawnEnemy(int64_t nowUs);
  void launchPlayerMissile(int x, int y);
  void createExplosion(int x, int y);
  void resolveCollisions();
  void finishWaveIfNeeded();
  void finishGame();

  int aliveCityCount() const;
  int activeEnemyCount() const;
  int activePlayerCount() const;
  int nearestBatteryForX(int x) const;

  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
  bool loadHighScore();
  bool saveHighScore();
};
