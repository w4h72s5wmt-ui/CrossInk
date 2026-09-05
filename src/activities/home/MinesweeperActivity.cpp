#include "MinesweeperActivity.h"

#include <GfxRenderer.h>
#include <I18n.h>

#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

#include "AlertActivity.h"
#include "CrossPointState.h"
#include "MappedInputManager.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;

constexpr const char* GRID_LABELS[] = {
    "Petite - 8 x 8",
    "Moyenne - 12 x 12",
    "Grande - 16 x 16",
};

constexpr const char* GRID_DIMS[] = {
    "8 x 8",
    "12 x 12",
    "16 x 16",
};

Rect menuListRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int contentTop =
      metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) + metrics.verticalSpacing;
  return Rect{0, contentTop, renderer.getScreenWidth(),
              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing};
}
}  // namespace

MinesweeperActivity::MinesweeperActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Minesweeper", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

void MinesweeperActivity::onEnter() {
  Activity::onEnter();
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  uiReady_ = false;

  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &MinesweeperActivity::onRowEvent, this);
  app_.setScreen(&MinesweeperActivity::menuScreen, this);
  requestUpdate();
}

void MinesweeperActivity::loop() {
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, renderer)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
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

void MinesweeperActivity::activateRow(const int row) {
  if (row >= 0 && row < kGridOptionCount) {
    gridSizeIndex_ = row;
    selectedIndex_ = row;
    requestUpdate();
    return;
  }

  if (row == 3) {
    continueGame();
    return;
  }

  if (row == 4) {
    newGame();
  }
}

void MinesweeperActivity::continueGame() {
  showInfo("Continuer", "Aucune partie sauvegardee pour le moment.");
}

void MinesweeperActivity::newGame() {
  char body[96];
  std::snprintf(body, sizeof(body), "Grille %s selectionnee. La grille arrive a l'etape suivante.",
                GRID_DIMS[gridSizeIndex_]);
  showInfo("Nouvelle partie", body);
}

void MinesweeperActivity::showInfo(const char* title, const char* body) {
  std::strcpy(APP_STATE.pendingAlertTitle, title);
  std::strcpy(APP_STATE.pendingAlertBody, body);
  APP_STATE.pendingAlertGoHomeOnBack.store(false, std::memory_order_relaxed);
  startActivityForResult(std::make_unique<AlertActivity>(renderer, mappedInput), [](const ActivityResult&) {});
}

void MinesweeperActivity::onRowEvent(const fui::ActionEvent& event, void* user) {
  auto* self = static_cast<MinesweeperActivity*>(user);
  if (event.value < 0 || event.value >= kMenuRowCount) return;

  self->selectedIndex_ = event.value;
  self->app_.clearTapFlash();
  self->activateRow(event.value);
}

void MinesweeperActivity::menuScreen(UiApp::ScreenType& screen, void* user) {
  static_cast<MinesweeperActivity*>(user)->buildMenuScreen(screen);
}

void MinesweeperActivity::buildMenuScreen(UiApp::ScreenType& screen) {
  const Rect bounds = menuListRect(renderer, mappedInput);
  screen.setContentMargin(fui::Insets{
      static_cast<int16_t>(bounds.y), 0,
      static_cast<int16_t>(renderer.getScreenHeight() - bounds.y - bounds.height), 0});

  std::vector<fui::ListItem> items;
  items.reserve(kMenuRowCount);

  for (int i = 0; i < kGridOptionCount; ++i) {
    fui::ListItem item;
    item.label = GRID_LABELS[i];
    item.value = i == gridSizeIndex_ ? "Choisie" : nullptr;
    item.actionValue = static_cast<int16_t>(i);
    items.push_back(item);
  }

  fui::ListItem continueItem;
  continueItem.label = "Continuer";
  continueItem.value = "Aucune partie";
  continueItem.actionValue = 3;
  items.push_back(continueItem);

  fui::ListItem newGameItem;
  newGameItem.label = "Nouvelle partie";
  newGameItem.value = GRID_DIMS[gridSizeIndex_];
  newGameItem.actionValue = 4;
  items.push_back(newGameItem);

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

void MinesweeperActivity::render(RenderLock&&) {
  renderer.clearScreen();

  const auto& metrics = UITheme::getInstance().getMetrics();
  const Rect header{0, metrics.topPadding, renderer.getScreenWidth(),
                    TouchHeaderBackButton::height(metrics, mappedInput)};

  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Demineur", false);
  } else {
    GUI.drawHeader(renderer, header, "Demineur", nullptr, false);
  }

  uiReady_ = false;
  app_.render();
  uiReady_ = true;

  const auto labels =
      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}
