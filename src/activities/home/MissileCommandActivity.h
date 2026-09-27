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

  static constexpr int kMenuRowCount = 7;
  static constexpr int kDifficultyCount = 3;
  static constexpr int kScoreSlotCount = kDifficultyCount * 2;
  static constexpr int kCityCount = 6;
  static constexpr int kBatteryCount = 3;
  static constexpr int kMaxEnemyMissiles = 12;
  static constexpr int kMaxPlayerMissiles = 8;
  static constexpr int kMaxExplosions = 8;

  enum class ViewMode : uint8_t { Menu, Playing, WaveComplete, GameOver };

  struct Missile {
    int16_t startX = 0;
    int16_t startY = 0;
    int16_t targetX = 0;
    int16_t targetY = 0;
    uint16_t progress = 0;
    uint16_t speed = 0;
    // Fractional legacy-frame progress carried between faster Stage-B frames.
    uint32_t progressRemainderUs = 0;
    bool active = false;
  };


  struct Explosion {
    int16_t x = 0;
    int16_t y = 0;
    uint8_t phase = 0;
    // Explosion phases keep the same real duration as the stable build.
    uint32_t phaseElapsedUs = 0;
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
  std::array<uint8_t, kBatteryCount> batteriesAlive_{{1, 1, 1}};
  bool baseMode_ = false;
  bool realisticExplosions_ = false;

  uint32_t score_ = 0;
  std::array<uint32_t, kScoreSlotCount> highScores_{};
  uint32_t highScore_ = 0;
  uint16_t wave_ = 1;
  uint16_t completedWave_ = 0;
  uint16_t waveEndAmmoRemaining_ = 0;
  uint8_t waveEndObjectives_ = 0;
  uint16_t waveShotsFired_ = 0;
  uint16_t waveEnemyKills_ = 0;
  uint16_t completedWaveShotsFired_ = 0;
  uint16_t completedWaveEnemyKills_ = 0;
  uint16_t completedWaveEfficiencyPct_ = 0;
  uint16_t waveTargetCount_ = 0;
  uint16_t waveEnemySpeed_ = 0;
  std::array<uint16_t, 7> waveHardEnemySpeeds_{};
  std::array<uint16_t, 16> waveEnemySpawnSpeeds_{};
  uint32_t waveSpawnIntervalUs_ = 0;
  uint8_t waveAmmoCapacity_ = 10;
  bool interWavePrepPending_ = false;
  uint16_t enemiesSpawned_ = 0;
  uint16_t enemiesResolved_ = 0;
  int64_t lastCycleUs_ = 0;
  int64_t nextSpawnUs_ = 0;
  bool hasSavedGame_ = false;
  bool sceneNeedsFullRedraw_ = true;
  uint8_t* windowShadow_ = nullptr;
  bool windowShadowValid_ = false;
  bool clusterCatchupPending_ = false;
  bool waveScrubPending_ = false;
  bool menuScrubPending_ = false;
  uint32_t hudScoreDrawn_ = 0xFFFFFFFFu;
  uint32_t hudHighScoreDrawn_ = 0xFFFFFFFFu;
  int64_t nextHudScoreCleanUs_ = 0;
  bool hudScoreCleanPending_ = false;

  // Main task captures touch into the next frame; render task clears this only
  // after the blocking FAST refresh completes. This enforces a strict 1:1
  // relationship between input, simulation state and the visible e-ink frame.
  std::atomic<bool> cycleRenderPending_{false};
  bool pendingTap_ = false;
  int16_t pendingTapX_ = 0;
  int16_t pendingTapY_ = 0;
  bool pendingBack_ = false;


  static void menuScreen(UiApp::ScreenType& screen, void* user);
  static void onRowEvent(const freeink::ui::ActionEvent& event, void* user);

  void buildMenuScreen(UiApp::ScreenType& screen);
  void activateRow(int row);
  void loopMenu();
  void loopPlaying();
  void loopGameOver();
  void loopWaveComplete();
  void renderMenu();
  void renderPlaying();
  void renderGameOver();
  void renderWaveComplete();
  void drawFullPlayingScene();
  void drawPlayingFrame();
  void refreshPlayingWindow(bool forceFullRefresh);
  void releaseWindowShadow();


  void newGame();
  void continueGame();
  void returnToMenu();
  void prepareWaveRuntimeConstants();
  void startWave();
  void beginPreparedWave();
  void tickGame(int64_t nowUs, uint32_t gameplayElapsedUs);
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
  int scoreSlot() const;
  void syncCurrentHighScore();

  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
  bool loadHighScore();
  bool saveHighScore();
};
