#include "MissileCommandActivity.h"

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
constexpr const char SAVE_PATH[] = "/.crosspoint/missile-command.bin";
constexpr const char SCORE_PATH[] = "/.crosspoint/missile-command-score.bin";
constexpr uint32_t SAVE_MAGIC = 0x4D434D31;   // MCM1
constexpr uint32_t SCORE_MAGIC = 0x4D435331;  // MCS1
constexpr uint8_t SAVE_VERSION = 1;
constexpr uint8_t SCORE_VERSION = 1;

// Simulation and panel cadence are deliberately independent. The old version
// advanced the game once per screen refresh, so a slow e-ink waveform made the
// whole game slow. We now simulate at 25 Hz and only ask for a new visible frame
// every 120 ms. If the panel is still busy the render task waits, while the main
// task continues simulating and accepting touch input.
constexpr int64_t LOGIC_TICK_US = 33333;
constexpr int64_t FRAME_INTERVAL_US = 33333;
constexpr int MAX_CATCHUP_TICKS = 8;
constexpr int EXPLOSION_PHASE_TICKS = 2;
constexpr const char* DIFFICULTY_LABELS[] = {"Facile", "Normal", "Difficile"};

Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int height = mappedInput.hasTouchHardware() ? TouchHeaderBackButton::height(metrics, mappedInput)
                                                     : metrics.headerHeight;
  return Rect{0, metrics.topPadding, renderer.getScreenWidth(), height};
}

Rect menuRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + metrics.verticalSpacing;
  return Rect{0, top, renderer.getScreenWidth(),
              renderer.getScreenHeight() - top - metrics.buttonHintsHeight - metrics.verticalSpacing};
}

struct GameGeometry {
  Rect header;
  Rect status;
  Rect field;
  int groundY = 0;
};

GameGeometry gameGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header = headerRect(renderer, mappedInput);
  const int statusH = std::max(44, renderer.getLineHeight(UI_10_FONT_ID) + 16);
  const Rect status{metrics.contentSidePadding, header.y + header.height + metrics.verticalSpacing,
                    renderer.getScreenWidth() - 2 * metrics.contentSidePadding, statusH};
  const int fieldTop = status.y + status.height + metrics.verticalSpacing;
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  const Rect field{metrics.contentSidePadding, fieldTop,
                   renderer.getScreenWidth() - 2 * metrics.contentSidePadding,
                   std::max(80, footerTop - fieldTop - metrics.verticalSpacing)};
  return GameGeometry{header, status, field, field.y + field.height - 34};
}

bool pointInRect(const Rect& rect, int x, int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

template <typename T>
bool writeValue(FsFile& file, const T& value) {
  return file.write(reinterpret_cast<const uint8_t*>(&value), sizeof(T)) == sizeof(T);
}

template <typename T>
bool readValue(FsFile& file, T& value) {
  return file.read(reinterpret_cast<uint8_t*>(&value), sizeof(T)) == static_cast<int>(sizeof(T));
}

int lerpInt(int a, int b, uint16_t progress) {
  return a + static_cast<int>((static_cast<int32_t>(b - a) * progress) / 1000);
}

void drawCenteredText(GfxRenderer& renderer, int fontId, const Rect& rect, const char* text) {
  const int w = renderer.getTextWidth(fontId, text);
  const int h = renderer.getLineHeight(fontId);
  renderer.drawText(fontId, rect.x + std::max(0, (rect.width - w) / 2),
                    rect.y + std::max(0, (rect.height - h) / 2), text);
}

int explosionRadius(uint8_t phase) {
  return phase <= 3 ? 8 + phase * 9 : 8 + (6 - phase) * 9;
}

void drawExplosion(GfxRenderer& renderer, int x, int y, int radius) {
  if (radius <= 1) {
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
    return;
  }
  renderer.drawRect(x - radius, y - radius, radius * 2, radius * 2, 1, true);
  const int inner = std::max(1, radius / 2);
  renderer.drawRect(x - inner, y - inner, inner * 2, inner * 2, 1, true);
}
}  // namespace

MissileCommandActivity::MissileCommandActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Missile Command", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

void MissileCommandActivity::onEnter() {
  Activity::onEnter();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = difficulty_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  uiReady_ = false;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  refreshInFlight_ = false;
  loadHighScore();
  hasSavedGame_ = loadSavedGame();
  selectedIndex_ = difficulty_;
  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &MissileCommandActivity::onRowEvent, this);
  app_.setScreen(&MissileCommandActivity::menuScreen, this);
  resetRenderCaches();
  requestUpdate();
}

void MissileCommandActivity::onExit() {
  waitForPendingRefresh();
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  Activity::onExit();
}

void MissileCommandActivity::loop() {
  switch (viewMode_) {
    case ViewMode::Menu:
      loopMenu();
      break;
    case ViewMode::Playing:
      loopPlaying();
      break;
    case ViewMode::GameOver:
      loopGameOver();
      break;
  }
}

void MissileCommandActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    onGoHome();
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

  const auto moveSelection = [this](int index) {
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

void MissileCommandActivity::loopPlaying() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty) && pointInRect(geometry.field, tx, ty) && ty < geometry.groundY) {
    launchPlayerMissile(tx, ty);
    frameDirty_ = true;
  }

  const int64_t now = esp_timer_get_time();
  if (lastLogicTickUs_ == 0) lastLogicTickUs_ = now;

  int ticks = 0;
  while (now - lastLogicTickUs_ >= LOGIC_TICK_US && ticks < MAX_CATCHUP_TICKS && viewMode_ == ViewMode::Playing) {
    lastLogicTickUs_ += LOGIC_TICK_US;
    tickGame(lastLogicTickUs_);
    frameDirty_ = true;
    ++ticks;
  }
  if (ticks == MAX_CATCHUP_TICKS && now - lastLogicTickUs_ >= LOGIC_TICK_US) {
    lastLogicTickUs_ = now;
  }

  if (viewMode_ == ViewMode::Playing && frameDirty_ && now - lastFrameRequestUs_ >= FRAME_INTERVAL_US) {
    frameDirty_ = false;
    lastFrameRequestUs_ = now;
    requestUpdate();
  }
}

void MissileCommandActivity::loopGameOver() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back) ||
      mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
  }
}

void MissileCommandActivity::activateRow(int row) {
  if (row >= 0 && row < kDifficultyCount) {
    difficulty_ = row;
    selectedIndex_ = row;
    requestUpdate();
    return;
  }
  if (row == 3) {
    if (hasSavedGame_) continueGame();
    return;
  }
  if (row != 4) return;

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

void MissileCommandActivity::newGame() {
  waitForPendingRefresh();
  clearSavedGame();
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  citiesAlive_.fill(1);
  ammo_.fill(10);
  score_ = 0;
  wave_ = 1;
  startWave();
  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastLogicTickUs_ = esp_timer_get_time();
  lastFrameRequestUs_ = 0;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
  requestUpdate();
}

void MissileCommandActivity::continueGame() {
  waitForPendingRefresh();
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  viewMode_ = ViewMode::Playing;
  uiReady_ = false;
  lastLogicTickUs_ = esp_timer_get_time();
  lastFrameRequestUs_ = 0;
  nextSpawnUs_ = lastLogicTickUs_ + 500000;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
  requestUpdate();
}

void MissileCommandActivity::returnToMenu() {
  waitForPendingRefresh();
  if (aliveCityCount() > 0) saveGame();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = difficulty_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  sceneNeedsFullRedraw_ = true;
  requestUpdate();
}

void MissileCommandActivity::startWave() {
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  ammo_.fill(static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5)));
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  nextSpawnUs_ = esp_timer_get_time() + 500000;
  sceneNeedsFullRedraw_ = true;
  resetRenderCaches();
}

void MissileCommandActivity::tickGame(int64_t nowUs) {
  if (aliveCityCount() <= 0) {
    finishGame();
    return;
  }

  const int targetCount = 5 + difficulty_ * 2 + std::min<int>(wave_, 7);
  if (enemiesSpawned_ < targetCount && nowUs >= nextSpawnUs_ && activeEnemyCount() < kMaxEnemyMissiles) {
    spawnEnemy(nowUs);
  }

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  for (auto& missile : enemies_) {
    if (!missile.active) continue;
    missile.progress = static_cast<uint16_t>(std::min<int>(1000, missile.progress + missile.speed));
    if (missile.progress < 1000) continue;
    missile.active = false;
    ++enemiesResolved_;

    int nearest = 0;
    int nearestDist = 1 << 30;
    for (int i = 0; i < kCityCount; ++i) {
      if (!citiesAlive_[static_cast<size_t>(i)]) continue;
      const int cityX = geometry.field.x + (geometry.field.width * (i + 1)) / (kCityCount + 1);
      const int d = std::abs(cityX - missile.targetX);
      if (d < nearestDist) {
        nearestDist = d;
        nearest = i;
      }
    }
    if (nearestDist < std::max(24, geometry.field.width / 10)) citiesAlive_[static_cast<size_t>(nearest)] = 0;
    createExplosion(missile.targetX, missile.targetY);
  }

  for (auto& missile : players_) {
    if (!missile.active) continue;
    missile.progress = static_cast<uint16_t>(std::min<int>(1000, missile.progress + missile.speed));
    if (missile.progress >= 1000) {
      missile.active = false;
      createExplosion(missile.targetX, missile.targetY);
    }
  }

  for (auto& explosion : explosions_) {
    if (!explosion.active) continue;
    if (++explosion.phaseTicks < EXPLOSION_PHASE_TICKS) continue;
    explosion.phaseTicks = 0;
    if (++explosion.phase >= 7) explosion.active = false;
  }

  resolveCollisions();
  finishWaveIfNeeded();
}

void MissileCommandActivity::spawnEnemy(int64_t nowUs) {
  Missile* slot = nullptr;
  for (auto& missile : enemies_) {
    if (!missile.active) {
      slot = &missile;
      break;
    }
  }
  if (!slot) return;

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int margin = 8;
  slot->startX = static_cast<int16_t>(geometry.field.x + margin +
      static_cast<int>(esp_random() % static_cast<uint32_t>(std::max(1, geometry.field.width - margin * 2))));
  slot->startY = static_cast<int16_t>(geometry.field.y + 2);

  std::array<int, kCityCount> alive{};
  int aliveCount = 0;
  for (int i = 0; i < kCityCount; ++i) {
    if (citiesAlive_[static_cast<size_t>(i)]) alive[static_cast<size_t>(aliveCount++)] = i;
  }
  if (aliveCount <= 0) return;
  const int city = alive[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
  slot->targetX = static_cast<int16_t>(geometry.field.x + (geometry.field.width * (city + 1)) / (kCityCount + 1));
  slot->targetY = static_cast<int16_t>(geometry.groundY);
  slot->progress = 0;
  // Speeds are per 40 ms simulation tick. These values preserve roughly the
  // original real-time descent speed while producing much finer movement.
  slot->speed = static_cast<uint16_t>(4 + difficulty_ + std::min<int>(wave_ / 2, 4));
  slot->active = true;
  ++enemiesSpawned_;

  const int delayMs = std::max(420, 1150 - difficulty_ * 180 - static_cast<int>(wave_) * 45);
  nextSpawnUs_ = nowUs + static_cast<int64_t>(delayMs) * 1000;
}

void MissileCommandActivity::launchPlayerMissile(int x, int y) {
  Missile* slot = nullptr;
  for (auto& missile : players_) {
    if (!missile.active) {
      slot = &missile;
      break;
    }
  }
  if (!slot) return;

  const int battery = nearestBatteryForX(x);
  if (battery < 0 || battery >= kBatteryCount || ammo_[static_cast<size_t>(battery)] == 0) return;

  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int batteryX = geometry.field.x + geometry.field.width * (battery * 2 + 1) / (kBatteryCount * 2);
  --ammo_[static_cast<size_t>(battery)];
  slot->startX = static_cast<int16_t>(batteryX);
  slot->startY = static_cast<int16_t>(geometry.groundY + 18);
  slot->targetX = static_cast<int16_t>(std::clamp(x, geometry.field.x, geometry.field.x + geometry.field.width - 1));
  slot->targetY = static_cast<int16_t>(std::clamp(y, geometry.field.y, geometry.groundY - 4));
  slot->progress = 0;
  slot->speed = 46;
  slot->active = true;
}

void MissileCommandActivity::createExplosion(int x, int y) {
  for (auto& explosion : explosions_) {
    if (explosion.active) continue;
    explosion.x = static_cast<int16_t>(x);
    explosion.y = static_cast<int16_t>(y);
    explosion.phase = 0;
    explosion.phaseTicks = 0;
    explosion.active = true;
    return;
  }
}

void MissileCommandActivity::resolveCollisions() {
  for (auto& enemy : enemies_) {
    if (!enemy.active) continue;
    const int ex = lerpInt(enemy.startX, enemy.targetX, enemy.progress);
    const int ey = lerpInt(enemy.startY, enemy.targetY, enemy.progress);
    for (const auto& explosion : explosions_) {
      if (!explosion.active) continue;
      const int radius = explosionRadius(explosion.phase);
      const int dx = ex - explosion.x;
      const int dy = ey - explosion.y;
      if (dx * dx + dy * dy > radius * radius) continue;
      enemy.active = false;
      ++enemiesResolved_;
      score_ += static_cast<uint32_t>(25 + wave_ * 2);
      createExplosion(ex, ey);
      break;
    }
  }
}

void MissileCommandActivity::finishWaveIfNeeded() {
  const int targetCount = 5 + difficulty_ * 2 + std::min<int>(wave_, 7);
  if (enemiesSpawned_ < targetCount || activeEnemyCount() > 0 || activePlayerCount() > 0) return;

  for (int i = 0; i < kCityCount; ++i) {
    if (citiesAlive_[static_cast<size_t>(i)]) score_ += 100;
  }
  for (uint8_t ammo : ammo_) score_ += static_cast<uint32_t>(ammo) * 5;
  ++wave_;
  startWave();
  saveGame();
}

void MissileCommandActivity::finishGame() {
  if (score_ > highScore_) {
    highScore_ = score_;
    saveHighScore();
  }
  clearSavedGame();
  viewMode_ = ViewMode::GameOver;
  frameDirty_ = false;
  sceneNeedsFullRedraw_ = true;
  requestUpdate();
}

int MissileCommandActivity::aliveCityCount() const {
  int count = 0;
  for (uint8_t alive : citiesAlive_) count += alive ? 1 : 0;
  return count;
}

int MissileCommandActivity::activeEnemyCount() const {
  int count = 0;
  for (const auto& missile : enemies_) count += missile.active ? 1 : 0;
  return count;
}

int MissileCommandActivity::activePlayerCount() const {
  int count = 0;
  for (const auto& missile : players_) count += missile.active ? 1 : 0;
  return count;
}

int MissileCommandActivity::nearestBatteryForX(int x) const {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  int best = 0;
  int bestDistance = 1 << 30;
  for (int i = 0; i < kBatteryCount; ++i) {
    const int bx = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const int d = std::abs(bx - x);
    if (d < bestDistance && ammo_[static_cast<size_t>(i)] > 0) {
      bestDistance = d;
      best = i;
    }
  }
  return bestDistance == (1 << 30) ? -1 : best;
}

void MissileCommandActivity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<MissileCommandActivity*>(user);
  if (event.value < 0 || event.value >= kMenuRowCount) return;
  self->selectedIndex_ = event.value;
  self->app_.clearTapFlash();
  self->activateRow(event.value);
}

void MissileCommandActivity::menuScreen(UiApp::ScreenType& screen, void* user) {
  static_cast<MissileCommandActivity*>(user)->buildMenuScreen(screen);
}

void MissileCommandActivity::buildMenuScreen(UiApp::ScreenType& screen) {
  const Rect bounds = menuRect(renderer, mappedInput);
  screen.setContentMargin(fui::Insets{static_cast<int16_t>(bounds.y), 0,
      static_cast<int16_t>(renderer.getScreenHeight() - bounds.y - bounds.height), 0});

  std::array<fui::ListItem, kMenuRowCount> items{};
  for (int i = 0; i < kDifficultyCount; ++i) {
    items[static_cast<size_t>(i)].label = DIFFICULTY_LABELS[i];
    items[static_cast<size_t>(i)].value = nullptr;
    items[static_cast<size_t>(i)].actionValue = static_cast<int16_t>(i);
  }

  items[3].label = "Continuer";
  if (hasSavedGame_) {
    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",
                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));
    items[3].value = continueValue_.data();
  } else {
    items[3].value = "Aucune partie";
  }
  items[3].actionValue = 3;

  items[4].label = "Nouvelle partie";
  items[4].value = DIFFICULTY_LABELS[difficulty_];
  items[4].actionValue = 4;

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
  topIndex_ = initialViewportPending_ ? followListSelection(selectedIndex_, 0, visibleRows_, kMenuRowCount)
                                      : scrollListBy(topIndex_, 0, visibleRows_, kMenuRowCount);
  initialViewportPending_ = false;
  props.topIndex = static_cast<uint16_t>(topIndex_);
  screen.list(props);
}

void MissileCommandActivity::render(RenderLock&&) {
  waitForPendingRefresh();
  switch (viewMode_) {
    case ViewMode::Menu:
      renderMenu();
      break;
    case ViewMode::Playing:
      renderPlaying();
      break;
    case ViewMode::GameOver:
      renderGameOver();
      break;
  }
}

void MissileCommandActivity::renderMenu() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, header, "Missile Command", nullptr, false);
  }

  uiReady_ = false;
  app_.render();
  uiReady_ = true;

  // Match Minesweeper/2048: real e-ink checkboxes for options, action rows
  // outlined as buttons, and a dithered disabled Continue action.
  const Rect listBounds = menuRect(renderer, mappedInput);
  const int drawnRows = std::max(1, visibleRows_);
  const int boxSize = 22;
  const int innerSize = 10;
  const int boxX = renderer.getScreenWidth() - UITheme::getInstance().getMetrics().contentSidePadding - boxSize - 10;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex < 0 || itemIndex >= kDifficultyCount) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    if (itemIndex == difficulty_) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
  }

  const auto& metrics = UITheme::getInstance().getMetrics();
  constexpr int actionInsetY = 4;
  const int actionX = metrics.contentSidePadding;
  const int actionWidth = renderer.getScreenWidth() - 2 * metrics.contentSidePadding;
  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex != 3 && itemIndex != 4) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int actionY = rowTop + actionInsetY;
    const int actionHeight = std::max(1, rowBottom - rowTop - 2 * actionInsetY);
    renderer.drawRoundedRect(actionX, actionY, actionWidth, actionHeight, 1, 6, true);
    if (itemIndex == 3 && !hasSavedGame_) {
      for (int y = actionY; y < actionY + actionHeight; y += 2) {
        renderer.fillRect(actionX, y, actionWidth, 1, false);
      }
    }
  }

  char record[48];
  std::snprintf(record, sizeof(record), "Meilleur score : %lu", static_cast<unsigned long>(highScore_));
  const int footerTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  drawCenteredText(renderer, UI_10_FONT_ID,
                   Rect{metrics.contentSidePadding, std::max(listBounds.y, footerTop - 34),
                        renderer.getScreenWidth() - 2 * metrics.contentSidePadding, 28}, record);

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT),
                                             tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}

void MissileCommandActivity::resetRenderCaches() {
  enemyDrawValid_.fill(0);
  playerDrawValid_.fill(0);
  explosionDrawValid_.fill(0);
  drawnCitiesAlive_.fill(0xFF);
  drawnAmmo_.fill(0xFF);
  drawnScore_ = UINT32_MAX;
  drawnWave_ = UINT16_MAX;
  drawnCityCount_ = -1;
}

void MissileCommandActivity::waitForPendingRefresh() {
  if (!refreshInFlight_) return;
  renderer.waitRefreshComplete();
  refreshInFlight_ = false;
}

void MissileCommandActivity::startFastRefresh() {
  if (renderer.supportsAsyncRefresh()) {
    renderer.displayBufferAsync(HalDisplay::FAST_REFRESH);
    refreshInFlight_ = true;
  } else {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
  }
}

void MissileCommandActivity::drawFullPlayingScene() {
  renderer.clearScreen();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }

  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);
  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);
  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  resetRenderCaches();
  sceneNeedsFullRedraw_ = false;
}

bool MissileCommandActivity::drawIncrementalPlayingScene() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);

  // Recompose the whole gameplay field in RAM each visible frame. This clears
  // the previous missile positions while retaining FAST differential e-ink
  // refresh. No permanent trajectory accumulation remains.
  renderer.fillRect(geometry.field.x + 1, geometry.field.y + 1,
                    std::max(1, geometry.field.width - 2), std::max(1, geometry.field.height - 2), false);
  renderer.drawLine(geometry.field.x, geometry.groundY,
                    geometry.field.x + geometry.field.width - 1, geometry.groundY, 1, true);

  for (int i = 0; i < kCityCount; ++i) {
    if (!citiesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i + 1) / (kCityCount + 1);
    renderer.drawRect(x - 10, geometry.groundY - 11, 20, 11, 1, true);
    renderer.drawLine(x - 8, geometry.groundY - 11, x, geometry.groundY - 20, 1, true);
    renderer.drawLine(x, geometry.groundY - 20, x + 8, geometry.groundY - 11, 1, true);
  }

  for (int i = 0; i < kBatteryCount; ++i) {
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);
    char ammoText[8];
    std::snprintf(ammoText, sizeof(ammoText), "%u", static_cast<unsigned>(ammo_[static_cast<size_t>(i)]));
    drawCenteredText(renderer, UI_10_FONT_ID, battery, ammoText);
  }

  for (const auto& missile : enemies_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 45 ? static_cast<uint16_t>(missile.progress - 45) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
  }

  for (const auto& missile : players_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 70 ? static_cast<uint16_t>(missile.progress - 70) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);
  }

  for (const auto& explosion : explosions_) {
    if (explosion.active) drawExplosion(renderer, explosion.x, explosion.y, explosionRadius(explosion.phase));
  }

  renderer.fillRect(geometry.status.x + 2, geometry.status.y + 2,
                    geometry.status.width - 4, geometry.status.height - 4, false);
  char status[96];
  std::snprintf(status, sizeof(status), "Score %lu   Record %lu   Vague %u   Villes %d",
                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_),
                static_cast<unsigned>(wave_), aliveCityCount());
  drawCenteredText(renderer, UI_10_FONT_ID, geometry.status, status);
  return true;
}

void MissileCommandActivity::renderPlaying() {
  if (sceneNeedsFullRedraw_) drawFullPlayingScene();
  if (drawIncrementalPlayingScene()) startFastRefresh();
}

void MissileCommandActivity::renderGameOver() {
  drawFullPlayingScene();
  drawIncrementalPlayingScene();
  const int width = std::min(380, renderer.getScreenWidth() - 36);
  const int height = 170;
  const Rect box{(renderer.getScreenWidth() - width) / 2, (renderer.getScreenHeight() - height) / 2, width, height};
  renderer.fillRect(box.x, box.y, box.width, box.height, false);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 2, 8, true);
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 12, box.y + 18, box.width - 24, 36}, "Toutes les villes sont perdues");
  char scoreText[64];
  std::snprintf(scoreText, sizeof(scoreText), "Score final : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 12, box.y + 68, box.width - 24, 30}, scoreText);
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 12, box.y + 112, box.width - 24, 30}, "OK / Retour : menu");
  renderer.displayBuffer();
  sceneNeedsFullRedraw_ = true;
}

bool MissileCommandActivity::saveGame() {
  if (aliveCityCount() <= 0) return false;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE", SAVE_PATH, file)) return false;
  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));
  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&
            writeValue(file, wave_) && writeValue(file, score_);
  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();
  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();
  file.close();
  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    return false;
  }
  hasSavedGame_ = true;
  return true;
}

bool MissileCommandActivity::loadSavedGame() {
  if (!Storage.exists(SAVE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MISSILE", SAVE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint8_t difficulty = 0;
  uint16_t wave = 0;
  uint32_t score = 0;
  std::array<uint8_t, kCityCount> cities{};
  std::array<uint8_t, kBatteryCount> ammo{};
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, difficulty) &&
            readValue(file, wave) && readValue(file, score);
  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());
  if (ok) ok = file.read(ammo.data(), ammo.size()) == static_cast<int>(ammo.size());
  file.close();
  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0) {
    clearSavedGame();
    return false;
  }
  for (uint8_t alive : cities) {
    if (alive > 1) {
      clearSavedGame();
      return false;
    }
  }
  difficulty_ = difficulty;
  wave_ = wave;
  score_ = score;
  citiesAlive_ = cities;
  ammo_ = ammo;
  enemies_ = {};
  players_ = {};
  explosions_ = {};
  enemiesSpawned_ = 0;
  enemiesResolved_ = 0;
  hasSavedGame_ = aliveCityCount() > 0;
  return hasSavedGame_;
}

void MissileCommandActivity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
}

bool MissileCommandActivity::loadHighScore() {
  highScore_ = 0;
  if (!Storage.exists(SCORE_PATH)) return false;
  FsFile file;
  if (!Storage.openFileForRead("MISSILE", SCORE_PATH, file)) return false;
  uint32_t magic = 0;
  uint8_t version = 0;
  uint32_t score = 0;
  const bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, score);
  file.close();
  if (!ok || magic != SCORE_MAGIC || version != SCORE_VERSION) return false;
  highScore_ = score;
  return true;
}

bool MissileCommandActivity::saveHighScore() {
  if (score_ > highScore_) highScore_ = score_;
  Storage.mkdir(SAVE_DIR);
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE", SCORE_PATH, file)) return false;
  const bool ok = writeValue(file, SCORE_MAGIC) && writeValue(file, SCORE_VERSION) && writeValue(file, highScore_);
  file.close();
  return ok;
}
