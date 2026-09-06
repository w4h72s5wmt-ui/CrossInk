#include "NotesActivity.h"

#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>

#include <algorithm>
#include <cctype>
#include <memory>

#include "MappedInputManager.h"
#include "activities/util/ConfirmationActivity.h"
#include "activities/util/KeyboardEntryActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "fontIds.h"

namespace {
constexpr int kTopMargin = 12;
constexpr int kControlHeight = 52;
constexpr int kControlGap = 8;
constexpr int kSideButtonWidth = 52;
constexpr int kSearchClearWidth = 44;
constexpr int kDeleteButtonWidth = 48;
constexpr int kRenameButtonWidth = 44;
constexpr int kRowHeight = 58;
constexpr int kRowSidePadding = 16;
constexpr int kCornerRadius = 6;

bool pointInRect(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

std::string lowerAscii(std::string value) {
  for (char& c : value) {
    const unsigned char uc = static_cast<unsigned char>(c);
    if (uc < 0x80) c = static_cast<char>(std::tolower(uc));
  }
  return value;
}

void drawCenteredLabel(GfxRenderer& renderer, const Rect& rect, const char* label) {
  const int textW = renderer.getTextWidth(UI_12_FONT_ID, label);
  const int textH = renderer.getLineHeight(UI_12_FONT_ID);
  renderer.drawText(UI_12_FONT_ID, rect.x + (rect.width - textW) / 2, rect.y + (rect.height - textH) / 2, label);
}

void drawPlusIcon(GfxRenderer& renderer, const Rect& rect) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  const int half = 10;
  renderer.fillRect(cx - half, cy - 1, half * 2 + 1, 3, true);
  renderer.fillRect(cx - 1, cy - half, 3, half * 2 + 1, true);
}

void drawSearchIcon(GfxRenderer& renderer, const Rect& rect) {
  const int size = 15;
  const int x = rect.x + std::max(0, (rect.width - size - 6) / 2);
  const int y = rect.y + std::max(0, (rect.height - size) / 2 - 2);
  renderer.drawRoundedRect(x, y, size, size, 2, size / 2, true);
  renderer.drawLine(x + size - 2, y + size - 2, x + size + 6, y + size + 6, 2, true);
}

void drawClearIcon(GfxRenderer& renderer, const Rect& rect) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  const int half = 7;
  renderer.drawLine(cx - half, cy - half, cx + half, cy + half, 2, true);
  renderer.drawLine(cx + half, cy - half, cx - half, cy + half, 2, true);
}

void drawRenameIcon(GfxRenderer& renderer, const Rect& rect, const bool black) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  renderer.drawLine(cx - 8, cy + 8, cx + 8, cy - 8, 3, black);
  renderer.drawLine(cx - 10, cy + 10, cx - 5, cy + 9, 2, black);
  renderer.drawLine(cx + 6, cy - 10, cx + 10, cy - 6, 2, black);
  renderer.drawLine(cx - 11, cy + 11, cx - 7, cy + 7, 1, black);
}

void drawTrashIcon(GfxRenderer& renderer, const Rect& rect, const bool black) {
  const int iconWidth = 18;
  const int iconHeight = 22;
  const int x = rect.x + (rect.width - iconWidth) / 2;
  const int y = rect.y + (rect.height - iconHeight) / 2;

  renderer.drawLine(x, y + 4, x + iconWidth - 1, y + 4, 2, black);
  renderer.drawLine(x + 5, y + 1, x + iconWidth - 6, y + 1, 2, black);
  renderer.drawRect(x + 2, y + 6, iconWidth - 4, iconHeight - 6, 1, black);
  renderer.drawLine(x + 6, y + 9, x + 6, y + iconHeight - 3, 1, black);
  renderer.drawLine(x + iconWidth - 7, y + 9, x + iconWidth - 7, y + iconHeight - 3, 1, black);
}
}  // namespace

NotesActivity::NotesActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Notes", renderer, mappedInput) {}

void NotesActivity::onEnter() {
  Activity::onEnter();
  Storage.mkdir(kNotesDir);
  reloadNotes();
  applyFilter();
  selectorIndex = 0;
  topIndex = 0;
  requestUpdate();
}

void NotesActivity::onExit() {
  filteredNotes.clear();
  notes.clear();
  Activity::onExit();
}

void NotesActivity::reloadNotes() {
  notes.clear();
  auto dir = Storage.open(kNotesDir);
  if (!dir || !dir.isDirectory()) {
    if (dir) dir.close();
    return;
  }

  char name[256];
  for (auto file = dir.openNextFile(); file; file = dir.openNextFile()) {
    if (!file.isDirectory()) {
      file.getName(name, sizeof(name));
      const std::string filename{name};
      if (filename.size() >= 4 && filename.compare(filename.size() - 4, 4, ".txt") == 0) {
        notes.push_back(filename);
      }
    }
    file.close();
  }
  dir.close();
  std::sort(notes.begin(), notes.end());
}

void NotesActivity::applyFilter() {
  filteredNotes.clear();
  if (searchQuery.empty()) {
    filteredNotes = notes;
  } else {
    const std::string needle = lowerAscii(searchQuery);
    for (const auto& filename : notes) {
      bool matches = lowerAscii(displayName(filename)).find(needle) != std::string::npos;
      if (!matches) {
        std::string content;
        if (loadNote(std::string(kNotesDir) + "/" + filename, content)) {
          matches = lowerAscii(std::move(content)).find(needle) != std::string::npos;
        }
      }
      if (matches) filteredNotes.push_back(filename);
    }
  }

  if (filteredNotes.empty()) {
    selectorIndex = 0;
    topIndex = 0;
  } else {
    selectorIndex = std::clamp(selectorIndex, 0, static_cast<int>(filteredNotes.size()) - 1);
    topIndex = std::clamp(topIndex, 0, selectorIndex);
  }
}

std::string NotesActivity::displayName(const std::string& filename) {
  if (filename.size() > 4 && filename.compare(filename.size() - 4, 4, ".txt") == 0) {
    return filename.substr(0, filename.size() - 4);
  }
  return filename;
}

std::string NotesActivity::sanitizeFilename(const std::string& title) {
  std::string out;
  out.reserve(std::min<size_t>(title.size(), 48));
  for (const unsigned char c : title) {
    if (out.size() >= 48) break;
    if (c < 0x20 || c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' || c == '"' || c == '<' ||
        c == '>' || c == '|') {
      out.push_back('_');
    } else {
      out.push_back(static_cast<char>(c));
    }
  }
  while (!out.empty() && (out.back() == ' ' || out.back() == '.')) out.pop_back();
  if (out.empty()) out = "Note";
  return out;
}

std::string NotesActivity::uniquePathForTitle(const std::string& title) const {
  const std::string base = sanitizeFilename(title);
  std::string path = std::string(kNotesDir) + "/" + base + ".txt";
  if (!Storage.exists(path.c_str())) return path;

  for (int suffix = 2; suffix < 1000; ++suffix) {
    path = std::string(kNotesDir) + "/" + base + " " + std::to_string(suffix) + ".txt";
    if (!Storage.exists(path.c_str())) return path;
  }
  return std::string(kNotesDir) + "/Note.txt";
}

bool NotesActivity::loadNote(const std::string& path, std::string& text) const {
  text.clear();
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;

  const uint32_t size = file.size();
  if (size > kMaxNoteBytes) {
    file.close();
    return false;
  }

  text.resize(size);
  if (size > 0 && file.read(text.data(), size) != static_cast<int>(size)) {
    file.close();
    text.clear();
    return false;
  }
  file.close();
  return true;
}

bool NotesActivity::saveNote(const std::string& path, const std::string& text) const {
  if (text.size() > kMaxNoteBytes) return false;
  FsFile file = Storage.open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const size_t written = text.empty() ? 0 : file.write(reinterpret_cast<const uint8_t*>(text.data()), text.size());
  file.close();
  return written == text.size();
}

void NotesActivity::editNote(const std::string& path, const std::string& title) {
  std::string initialText;
  if (!loadNote(path, initialText)) initialText.clear();

  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes,
                                              InputType::Multiline),
      [this, path](const ActivityResult& result) {
        if (!result.isCancelled) {
          const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
          if (keyboard && !saveNote(path, keyboard->text)) {
            LOG_ERR("NOTES", "Failed to save note: %s", path.c_str());
          }
        }
        reloadNotes();
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::createNote() {
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_NOTE_TITLE), "", 48, InputType::Text, 1),
      [this](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
        if (!keyboard || keyboard->text.empty()) {
          requestUpdate();
          return;
        }
        const std::string path = uniquePathForTitle(keyboard->text);
        if (!saveNote(path, "")) {
          LOG_ERR("NOTES", "Failed to create note: %s", path.c_str());
          requestUpdate();
          return;
        }
        reloadNotes();
        applyFilter();
        editNote(path, keyboard->text);
      });
}

void NotesActivity::renameNote(const std::string& filename) {
  const std::string oldTitle = displayName(filename);
  const std::string oldPath = std::string(kNotesDir) + "/" + filename;
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_NOTE_TITLE), oldTitle, 48,
                                              InputType::Text, 1),
      [this, filename, oldPath](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
        if (!keyboard || keyboard->text.empty()) {
          requestUpdate();
          return;
        }

        const std::string sanitized = sanitizeFilename(keyboard->text);
        const std::string requestedFilename = sanitized + ".txt";
        if (requestedFilename == filename) {
          requestUpdate();
          return;
        }

        std::string content;
        if (!loadNote(oldPath, content)) {
          LOG_ERR("NOTES", "Failed to read note for rename: %s", oldPath.c_str());
          requestUpdate();
          return;
        }
        const std::string newPath = uniquePathForTitle(keyboard->text);
        if (!saveNote(newPath, content)) {
          LOG_ERR("NOTES", "Failed to write renamed note: %s", newPath.c_str());
          requestUpdate();
          return;
        }
        if (!Storage.remove(oldPath.c_str())) {
          Storage.remove(newPath.c_str());
          LOG_ERR("NOTES", "Failed to remove old note after rename: %s", oldPath.c_str());
          requestUpdate();
          return;
        }
        reloadNotes();
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::editSearch() {
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_SEARCH_NOTES), searchQuery, 80,
                                              InputType::Text),
      [this](const ActivityResult& result) {
        if (!result.isCancelled) {
          const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
          if (keyboard) searchQuery = keyboard->text;
        }
        selectorIndex = 0;
        topIndex = 0;
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::openNoteAt(const int index) {
  if (index < 0 || index >= static_cast<int>(filteredNotes.size())) return;
  selectorIndex = index;
  const std::string filename = filteredNotes[static_cast<size_t>(index)];
  editNote(std::string(kNotesDir) + "/" + filename, displayName(filename));
}

void NotesActivity::openSelectedNote() { openNoteAt(selectorIndex); }

void NotesActivity::loop() {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto backLayout = TouchHeaderBackButton::layout(header);
  const Rect backRect = backLayout.touchRect;
  const int controlOffset = std::min(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
                                     std::max(0, header.y + header.height -
                                                     (backLayout.iconRect.y +
                                                      (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
  const Rect addRect{width - kSideButtonWidth, header.y + controlOffset, kSideButtonWidth, header.height};
  const int searchLeft = backLayout.iconRect.x + backLayout.iconRect.width + kControlGap;
  const int searchRight = addRect.x - kControlGap;
  const Rect searchRect{searchLeft, header.y + controlOffset, std::max(1, searchRight - searchLeft), header.height};
  const int listTop = header.y + header.height + metrics.verticalSpacing;
  const int listBottom = height - metrics.buttonHintsHeight - kTopMargin;
  const int visibleRows = std::max(1, (listBottom - listTop) / kRowHeight);

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty)) {
    if (pointInRect(backRect, tx, ty)) {
      finish();
      return;
    }
    if (pointInRect(addRect, tx, ty)) {
      createNote();
      return;
    }
    if (pointInRect(searchRect, tx, ty)) {
      const Rect clearRect{searchRect.x + searchRect.width - kSearchClearWidth, searchRect.y, kSearchClearWidth,
                           searchRect.height};
      if (!searchQuery.empty() && pointInRect(clearRect, tx, ty)) {
        searchQuery.clear();
        selectorIndex = 0;
        topIndex = 0;
        applyFilter();
        requestUpdate();
      } else {
        editSearch();
      }
      return;
    }
    if (ty >= listTop && ty < listBottom) {
      const int row = (ty - listTop) / kRowHeight;
      const int index = topIndex + row;
      if (row >= 0 && row < visibleRows && index >= 0 && index < static_cast<int>(filteredNotes.size())) {
        selectorIndex = index;
        const Rect rowRect{kTopMargin, listTop + row * kRowHeight, width - kTopMargin * 2, kRowHeight - 2};
        const Rect deleteRect{rowRect.x + rowRect.width - kDeleteButtonWidth, rowRect.y, kDeleteButtonWidth,
                              rowRect.height};
        const Rect renameRect{deleteRect.x - kRenameButtonWidth, rowRect.y, kRenameButtonWidth, rowRect.height};
        if (pointInRect(deleteRect, tx, ty)) {
          const std::string filename = filteredNotes[static_cast<size_t>(index)];
          const std::string path = std::string(kNotesDir) + "/" + filename;
          const std::string heading = std::string(tr(STR_DELETE)) + "?";
          startActivityForResult(
              std::make_unique<ConfirmationActivity>(renderer, mappedInput, heading, displayName(filename)),
              [this, path](const ActivityResult& result) {
                if (result.isCancelled) {
                  requestUpdate();
                  return;
                }
                if (!Storage.remove(path.c_str())) {
                  LOG_ERR("NOTES", "Failed to delete note: %s", path.c_str());
                }
                reloadNotes();
                applyFilter();
                requestUpdate();
              });
          return;
        }
        if (pointInRect(renameRect, tx, ty)) {
          const std::string filename = filteredNotes[static_cast<size_t>(index)];
          renameNote(filename);
          return;
        }
        openNoteAt(index);
        return;
      }
    }
  }

  const int itemCount = static_cast<int>(filteredNotes.size());
  if (itemCount > 0) {
    const auto moveSelection = [this, itemCount, visibleRows](const int next) {
      selectorIndex = next;
      if (selectorIndex < topIndex) topIndex = selectorIndex;
      if (selectorIndex >= topIndex + visibleRows) topIndex = selectorIndex - visibleRows + 1;
      topIndex = std::clamp(topIndex, 0, std::max(0, itemCount - visibleRows));
      requestUpdate();
    };
    buttonNavigator.onNextRelease(
        [this, itemCount, &moveSelection] { moveSelection(ButtonNavigator::nextIndex(selectorIndex, itemCount)); });
    buttonNavigator.onPreviousRelease(
        [this, itemCount, &moveSelection] { moveSelection(ButtonNavigator::previousIndex(selectorIndex, itemCount)); });

    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      openSelectedNote();
      return;
    }

    const auto swipe = mappedInput.wasSwipe();
    if (swipe == MappedInputManager::SwipeDir::Up || swipe == MappedInputManager::SwipeDir::Down) {
      const int maxTop = std::max(0, itemCount - visibleRows);
      const int delta = swipe == MappedInputManager::SwipeDir::Up ? visibleRows : -visibleRows;
      topIndex = std::clamp(topIndex + delta, 0, maxTop);
      selectorIndex = std::clamp(selectorIndex, topIndex, std::min(itemCount - 1, topIndex + visibleRows - 1));
      requestUpdate();
      return;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
    finish();
  }
}

void NotesActivity::render(RenderLock&&) {
  renderer.clearScreen();
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto backLayout = TouchHeaderBackButton::layout(header);
  const int controlOffset = std::min(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
                                     std::max(0, header.y + header.height -
                                                     (backLayout.iconRect.y +
                                                      (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
  const Rect addRect{width - kSideButtonWidth, header.y + controlOffset, kSideButtonWidth, header.height};
  const int searchLeft = backLayout.iconRect.x + backLayout.iconRect.width + kControlGap;
  const int searchRight = addRect.x - kControlGap;
  const Rect searchRect{searchLeft, header.y + controlOffset, std::max(1, searchRight - searchLeft), header.height};

  TouchHeaderBackButton::draw(renderer, header, "", false, kSideButtonWidth + kControlGap);
  drawPlusIcon(renderer, addRect);

  const Rect searchIconRect{searchRect.x, searchRect.y, 34, searchRect.height};
  drawSearchIcon(renderer, searchIconRect);

  const char* placeholder = tr(STR_SEARCH_NOTES);
  const int searchTextReserve = searchQuery.empty() ? 8 : 8 + kSearchClearWidth;
  const int searchTextX = searchRect.x + searchIconRect.width + 4;
  const int searchTextWidth = std::max(1, searchRect.x + searchRect.width - searchTextX - searchTextReserve);
  const std::string searchLabel =
      searchQuery.empty()
          ? std::string(placeholder)
          : renderer.truncatedText(UI_12_FONT_ID, searchQuery.c_str(), searchTextWidth);
  const int searchTextH = renderer.getLineHeight(UI_12_FONT_ID);
  renderer.drawText(UI_12_FONT_ID, searchTextX, searchRect.y + (searchRect.height - searchTextH) / 2,
                    searchLabel.c_str());
  renderer.drawLine(searchTextX, searchRect.y + searchRect.height - 5, searchRect.x + searchRect.width - 4,
                    searchRect.y + searchRect.height - 5, 1, true);
  if (!searchQuery.empty()) {
    const Rect clearRect{searchRect.x + searchRect.width - kSearchClearWidth, searchRect.y, kSearchClearWidth,
                         searchRect.height};
    drawClearIcon(renderer, clearRect);
  }

  const int listTop = header.y + header.height + metrics.verticalSpacing;
  const int listBottom = height - metrics.buttonHintsHeight - kTopMargin;
  const int visibleRows = std::max(1, (listBottom - listTop) / kRowHeight);
  const int itemCount = static_cast<int>(filteredNotes.size());
  const int maxTop = std::max(0, itemCount - visibleRows);
  topIndex = std::clamp(topIndex, 0, maxTop);

  if (filteredNotes.empty()) {
    renderer.drawCenteredText(UI_12_FONT_ID, listTop + kRowHeight, tr(STR_NO_NOTES), true);
  } else {
    for (int row = 0; row < visibleRows; ++row) {
      const int index = topIndex + row;
      if (index >= itemCount) break;
      const int rowY = listTop + row * kRowHeight;
      const Rect rowRect{kTopMargin, rowY, width - kTopMargin * 2, kRowHeight - 2};
      const Rect deleteRect{rowRect.x + rowRect.width - kDeleteButtonWidth, rowRect.y, kDeleteButtonWidth,
                            rowRect.height};
      const Rect renameRect{deleteRect.x - kRenameButtonWidth, rowRect.y, kRenameButtonWidth, rowRect.height};
      const bool selected = index == selectorIndex;
      if (selected) {
        auto target = makeUiTarget(renderer);
        target.fill(freeink::ui::Rect{static_cast<int16_t>(rowRect.x), static_cast<int16_t>(rowRect.y),
                                      static_cast<int16_t>(rowRect.width), static_cast<int16_t>(rowRect.height)},
                    freeink::ui::Paint::dither(freeink::ui::Color::LightGray));
      }
      const std::string title = renderer.truncatedText(UI_12_FONT_ID, displayName(filteredNotes[index]).c_str(),
                                                       rowRect.width - kRowSidePadding * 2 - kRenameButtonWidth -
                                                           kDeleteButtonWidth);
      const int textH = renderer.getLineHeight(UI_12_FONT_ID);
      renderer.drawText(UI_12_FONT_ID, rowRect.x + kRowSidePadding, rowRect.y + (rowRect.height - textH) / 2,
                        title.c_str(), true);
      drawRenameIcon(renderer, renameRect, true);
      drawTrashIcon(renderer, deleteRect, true);
    }
  }

  const auto labels = mappedInput.mapLabels(tr(STR_SELECT), tr(STR_BACK), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);
  renderer.displayBuffer();
}
