#include "MinesweeperActivity.h"

#include <GfxRenderer.h>
#include <I18n.h>

#include <algorithm>
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
#include "fontIds.h"

namespace fui = freeink::ui;

namespace {
constexpr fui::ActionId ACTION_ROW = 1;
constexpr int HEADER_ACTION_SIZE = 48;
constexpr int HEADER_ACTION_MARGIN = 8;

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

constexpr int GRID_SIZES[] = {8, 12, 16};

Rect menuListRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int contentTop =
      metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) + metrics.verticalSpacing;
  return Rect{0, contentTop, renderer.getScreenWidth(),
              renderer.getScreenHeight() - contentTop - metrics.buttonHintsHeight - metrics.verticalSpacing};
}

Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int height = mappedInput.hasTouchHardware() ? TouchHeaderBackButton::height(metrics, mappedInput)
                                                     : metrics.headerHeight;
  return Rect{0, metrics.topPadding, renderer.getScreenWidth(), height};
}

Rect closeButtonRect(const Rect& header) {
  const int size = std::min(HEADER_ACTION_SIZE, std::max(32, header.height - 8));
  return Rect{header.x + header.width - size - HEADER_ACTION_MARGIN,
              header.y + std::max(0, (header.height - size) / 2), size, size};
}

void drawCloseButton(GfxRenderer& renderer, const Rect& rect) {
  renderer.drawRect(rect.x, rect.y, rect.width, rect.height, 1, true);
  const char* label = "X";
  const int textWidth = renderer.getTextWidth(UI_10_FONT_ID, label);
  const int textHeight = renderer.getLineHeight(UI_10_FONT_ID);
  renderer.drawText(UI_10_FONT_ID, rect.x + std::max(0, (rect.width - textWidth) / 2),
                    rect.y + std::max(0, (rect.height - textHeight) / 2), label);
}

bool pointInRect(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

struct GridGeometry {
  Rect header;
  Rect grid;
  Rect close;
  int cellSize = 1;
};

GridGeometry gridGeometry(const GfxRenderer& renderer, const MappedInputManager& mappedInput, const int dimension) {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  const Rect header = headerRect(renderer, mappedInput);
  const int contentTop = header.y + header.height + metrics.verticalSpacing;
  const int footerTop = screenHeight - metrics.buttonHintsHeight;
  const int availableHeight = std::max(1, footerTop - contentTop - metrics.verticalSpacing);
  const int availableWidth = std::max(1, screenWidth - 2 * metrics.contentSidePadding);
  const int cellSize = std::max(1, std::min(availableWidth / dimension, availableHeight / dimension));
  const int gridWidth = cellSize * dimension;
  const int gridHeight = cellSize * dimension;
  const int gridX = (screenWidth - gridWidth) / 2;
  const int gridY = contentTop + std::max(0, (availableHeight - gridHeight) / 2);
  return GridGeometry{header, Rect{gridX, gridY, gridWidth, gridHeight}, closeButtonRect(header), cellSize};
}
}  // namespace

MinesweeperActivity::MinesweeperActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Minesweeper", renderer, mappedInput),
      uiTarget_(makeUiTarget(renderer)),
      app_(uiTarget_, uiTarget_.deviceContext()) {}

void MinesweeperActivity::onEnter() {
  Activity::onEnter();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  visibleRows_ = 1;
  initialViewportPending_ = true;
  uiReady_ = false;
  selectedCellIndex_ = 0;
  confirmedCellIndex_ = -1;

  applySharedUiTheme(app_, uiTarget_);
  app_.on(ACTION_ROW, &MinesweeperActivity::onRowEvent, this);
  app_.setScreen(&MinesweeperActivity::menuScreen, this);
  requestUpdate();
}

void MinesweeperActivity::loop() {
  if (viewMode_ == ViewMode::Grid) {
    loopGrid();
  } else {
    loopMenu();
  }
}

void MinesweeperActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  const Rect close = closeButtonRect(header);
  if (mappedInput.hasTouchHardware() && mappedInput.wasTapInRect(close.x, close.y, close.width, close.height)) {
    finish();
    return;
  }

  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
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

void MinesweeperActivity::loopGrid() {
  const int dimension = gridDimension();
  const int totalCells = dimension * dimension;
  const GridGeometry geometry = gridGeometry(renderer, mappedInput, dimension);

  if (mappedInput.hasTouchHardware() &&
      mappedInput.wasTapInRect(geometry.close.x, geometry.close.y, geometry.close.width, geometry.close.height)) {
    returnToMenu();
    return;
  }

  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, geometry.header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    returnToMenu();
    return;
  }

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty) && pointInRect(geometry.grid, tx, ty)) {
    const int col = std::clamp((tx - geometry.grid.x) / geometry.cellSize, 0, dimension - 1);
    const int row = std::clamp((ty - geometry.grid.y) / geometry.cellSize, 0, dimension - 1);
    selectedCellIndex_ = row * dimension + col;
    confirmedCellIndex_ = -1;
    requestUpdate();
    return;
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    confirmedCellIndex_ = selectedCellIndex_;
    requestUpdate();
    return;
  }

  const auto moveCell = [this, totalCells](const int index) {
    selectedCellIndex_ = index;
    confirmedCellIndex_ = -1;
    requestUpdate();
  };

  buttonNavigator_.onNextRelease(
      [this, totalCells, &moveCell] { moveCell(ButtonNavigator::nextIndex(selectedCellIndex_, totalCells)); });
  buttonNavigator_.onPreviousRelease(
      [this, totalCells, &moveCell] { moveCell(ButtonNavigator::previousIndex(selectedCellIndex_, totalCells)); });
  buttonNavigator_.onNextContinuous(
      [this, totalCells, &moveCell] { moveCell(ButtonNavigator::nextIndex(selectedCellIndex_, totalCells)); });
  buttonNavigator_.onPreviousContinuous(
      [this, totalCells, &moveCell] { moveCell(ButtonNavigator::previousIndex(selectedCellIndex_, totalCells)); });
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
  enterGrid();
}

void MinesweeperActivity::enterGrid() {
  viewMode_ = ViewMode::Grid;
  uiReady_ = false;
  selectedCellIndex_ = 0;
  confirmedCellIndex_ = -1;
  requestUpdate();
}

void MinesweeperActivity::returnToMenu() {
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = gridSizeIndex_;
  topIndex_ = 0;
  initialViewportPending_ = true;
  confirmedCellIndex_ = -1;
  requestUpdate();
}

int MinesweeperActivity::gridDimension() const {
  return GRID_SIZES[std::clamp(gridSizeIndex_, 0, kGridOptionCount - 1)];
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
  if (viewMode_ == ViewMode::Grid) {
    renderGrid();
  } else {
    renderMenu();
  }
}

void MinesweeperActivity::renderMenu() {
  renderer.clearScreen();

  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    const int rightReserve = HEADER_ACTION_SIZE + 2 * HEADER_ACTION_MARGIN;
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Demineur", false, rightReserve);
    drawCloseButton(renderer, closeButtonRect(header));
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

void MinesweeperActivity::renderGrid() {
  renderer.clearScreen();

  const int dimension = gridDimension();
  const GridGeometry geometry = gridGeometry(renderer, mappedInput, dimension);

  char title[48];
  std::snprintf(title, sizeof(title), "Demineur - %s", GRID_DIMS[gridSizeIndex_]);
  if (mappedInput.hasTouchHardware()) {
    const int rightReserve = HEADER_ACTION_SIZE + 2 * HEADER_ACTION_MARGIN;
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, title, false, rightReserve);
    drawCloseButton(renderer, geometry.close);
  } else {
    GUI.drawHeader(renderer, geometry.header, title);
  }

  renderer.drawRect(geometry.grid.x, geometry.grid.y, geometry.grid.width + 1, geometry.grid.height + 1, 1, true);
  for (int i = 1; i < dimension; ++i) {
    const int x = geometry.grid.x + i * geometry.cellSize;
    renderer.drawLine(x, geometry.grid.y, x, geometry.grid.y + geometry.grid.height, 1, true);
  }
  for (int i = 1; i < dimension; ++i) {
    const int y = geometry.grid.y + i * geometry.cellSize;
    renderer.drawLine(geometry.grid.x, y, geometry.grid.x + geometry.grid.width, y, 1, true);
  }

  const int selectedRow = selectedCellIndex_ / dimension;
  const int selectedCol = selectedCellIndex_ % dimension;
  const int selectedX = geometry.grid.x + selectedCol * geometry.cellSize;
  const int selectedY = geometry.grid.y + selectedRow * geometry.cellSize;
  if (geometry.cellSize >= 5) {
    renderer.drawRect(selectedX + 2, selectedY + 2, std::max(1, geometry.cellSize - 3),
                      std::max(1, geometry.cellSize - 3), 2, true);
  }

  if (confirmedCellIndex_ >= 0 && confirmedCellIndex_ < dimension * dimension) {
    const int confirmedRow = confirmedCellIndex_ / dimension;
    const int confirmedCol = confirmedCellIndex_ % dimension;
    const int cx = geometry.grid.x + confirmedCol * geometry.cellSize + geometry.cellSize / 2;
    const int cy = geometry.grid.y + confirmedRow * geometry.cellSize + geometry.cellSize / 2;
    const int marker = std::max(2, geometry.cellSize / 10);
    renderer.fillRect(cx - marker, cy - marker, marker * 2 + 1, marker * 2 + 1, true);
  }

  const auto labels =
      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  renderer.displayBuffer();
}
