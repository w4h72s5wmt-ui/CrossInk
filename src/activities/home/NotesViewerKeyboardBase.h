#pragma once

#include <BidiUtils.h>
#include <GfxRenderer.h>
#include <HalStorage.h>

#include <algorithm>
#include <cctype>
#include <string>
#include <utility>
#include <vector>

#include "CrossPointSettings.h"
#include "MappedInputManager.h"
#include "SdCardFontSystem.h"
#include "activities/util/KeyboardEntryActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "fontIds.h"

// Read-only-first decorator used by Notes. Non-multiline entry fields keep the
// normal KeyboardEntryActivity behavior, so title/search dialogs are unchanged.
class NotesViewerKeyboardBase : public KeyboardEntryActivity {
 public:
  explicit NotesViewerKeyboardBase(GfxRenderer& renderer, MappedInputManager& mappedInput,
                                   std::string title = "Enter Text", std::string initialText = "",
                                   const size_t maxLength = 0, InputType inputType = InputType::Text,
                                   const size_t minLength = 0)
      : KeyboardEntryActivity(renderer, mappedInput, title, std::move(initialText), maxLength, inputType, minLength),
        viewerTitle(std::move(title)), viewerInputType(inputType) {}

  void onEnter() override {
    KeyboardEntryActivity::onEnter();
    editing = false;
    viewerPage = 0;
    viewerLayoutDirty = true;
    if (viewerEnabled()) {
      sdFontSystem.ensureLoaded(renderer);
      rebuildViewerLayout();
      requestUpdate(true);
    }
  }

  void onExit() override { KeyboardEntryActivity::onExit(); }

  void loop() override {
    if (!viewerEnabled() || editing) {
      KeyboardEntryActivity::loop();
      return;
    }

    int tx = 0;
    int ty = 0;
    if (mappedInput.wasScreenTapped(tx, ty)) {
      const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
      const Rect backRect = TouchHeaderBackButton::layout(header).touchRect;
      if (pointIn(backRect, tx, ty)) {
        finish();
        return;
      }
      if (pointIn(headerActionRect(), tx, ty)) {
        handleHeaderActionTap(tx, ty);
        return;
      }
      if (pointIn(pencilRect(), tx, ty)) {
        editing = true;
        requestUpdate(true);
        return;
      }
    }

    if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
      finish();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Up) ||
        mappedInput.wasReleased(MappedInputManager::Button::Left)) {
      changePage(-1);
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Down) ||
        mappedInput.wasReleased(MappedInputManager::Button::Right)) {
      changePage(1);
      return;
    }

    const auto swipe = mappedInput.wasSwipe();
    if (swipe == MappedInputManager::SwipeDir::Up) {
      changePage(1);
    } else if (swipe == MappedInputManager::SwipeDir::Down) {
      changePage(-1);
    }
  }

  void render(RenderLock&& lock) override {
    if (!viewerEnabled() || editing) {
      KeyboardEntryActivity::render(std::move(lock));
      return;
    }

    if (viewerLayoutDirty) rebuildViewerLayout();

    renderer.clearScreen();
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    TouchHeaderBackButton::draw(renderer, header, viewerTitle.c_str(), false, headerActionReserveWidth());
    drawHeaderAction();

    const size_t firstLine = static_cast<size_t>(viewerPage * viewerLinesPerPage);
    const size_t endLine = std::min(viewerLines.size(), firstLine + static_cast<size_t>(viewerLinesPerPage));
    int y = viewerBodyTop;
    for (size_t i = firstLine; i < endLine; ++i) {
      const std::string& line = viewerLines[i];
      if (!line.empty()) {
        int x = viewerMarginX;
        uint8_t alignment = SETTINGS.paragraphAlignment;
        const bool rtl = BidiUtils::startsWithRtl(line.c_str(), BidiUtils::RTL_PARAGRAPH_PROBE_DEPTH);
        if (rtl && (alignment == CrossPointSettings::LEFT_ALIGN || alignment == CrossPointSettings::JUSTIFIED)) {
          alignment = CrossPointSettings::RIGHT_ALIGN;
        }
        const int textWidth = renderer.getTextWidth(viewerFontId, line.c_str());
        if (alignment == CrossPointSettings::CENTER_ALIGN) {
          x = viewerMarginX + (viewerContentWidth - textWidth) / 2;
        } else if (alignment == CrossPointSettings::RIGHT_ALIGN) {
          x = viewerMarginX + viewerContentWidth - textWidth;
        }
        renderer.drawText(viewerFontId, x, y, line.c_str(), true);
      }
      y += viewerLineHeight;
    }

    drawPencil(pencilRect());
    if (viewerPageCount > 1) {
      const std::string counter = std::to_string(viewerPage + 1) + "/" + std::to_string(viewerPageCount);
      const int counterWidth = renderer.getTextWidth(UI_10_FONT_ID, counter.c_str());
      const Rect pencil = pencilRect();
      renderer.drawText(UI_10_FONT_ID, renderer.getScreenWidth() - viewerMarginX - counterWidth,
                        pencil.y + (pencil.height - renderer.getLineHeight(UI_10_FONT_ID)) / 2,
                        counter.c_str(), true);
    }
    renderer.displayBuffer();
  }

 protected:
  bool viewerEnabled() const { return viewerInputType == InputType::Multiline && headerActionReserveWidth() > 0; }

  void drawHeaderAction() override {
    if (currentNoteLooksLocked()) {
      drawNotesHeaderAction();
    } else {
      drawOpenLockLight(headerActionRect());
    }
  }

  // NotesActivityCore.inc remaps its historical drawHeaderAction override to
  // this hook. That keeps the same privacy icon in viewer and editor modes.
  virtual void drawNotesHeaderAction() {}

 private:
  std::string viewerTitle;
  InputType viewerInputType = InputType::Text;
  bool editing = false;
  bool viewerLayoutDirty = true;
  int viewerFontId = UI_12_FONT_ID;
  int viewerLineHeight = 1;
  int viewerLinesPerPage = 1;
  int viewerPage = 0;
  int viewerPageCount = 1;
  int viewerMarginX = 12;
  int viewerBodyTop = 0;
  int viewerContentWidth = 1;
  std::vector<std::string> viewerLines;

  static bool pointIn(const Rect& rect, const int x, const int y) {
    return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
  }

  Rect headerActionRect() const {
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const int width = std::max(0, headerActionReserveWidth());
    return Rect{renderer.getScreenWidth() - width, header.y, width, header.height};
  }

  Rect pencilRect() const {
    constexpr int width = 58;
    constexpr int height = 44;
    return Rect{(renderer.getScreenWidth() - width) / 2, renderer.getScreenHeight() - height - 10, width, height};
  }

  static size_t previousUtf8Boundary(const std::string& text, size_t pos) {
    if (pos == 0) return 0;
    --pos;
    while (pos > 0 && (static_cast<unsigned char>(text[pos]) & 0xC0) == 0x80) --pos;
    return pos;
  }

  static size_t nextUtf8Boundary(const std::string& text, const size_t pos) {
    if (pos >= text.size()) return text.size();
    size_t next = pos + 1;
    while (next < text.size() && (static_cast<unsigned char>(text[next]) & 0xC0) == 0x80) ++next;
    return next;
  }

  void appendWrappedLine(std::string remaining) {
    if (remaining.empty()) {
      viewerLines.emplace_back();
      return;
    }

    while (!remaining.empty()) {
      if (renderer.getTextWidth(viewerFontId, remaining.c_str()) <= viewerContentWidth) {
        viewerLines.push_back(std::move(remaining));
        return;
      }

      size_t breakPos = remaining.size();
      while (breakPos > 0) {
        const std::string candidate = remaining.substr(0, breakPos);
        if (renderer.getTextWidth(viewerFontId, candidate.c_str()) <= viewerContentWidth) break;
        const size_t space = remaining.rfind(' ', breakPos - 1);
        if (space != std::string::npos && space > 0) {
          breakPos = space;
        } else {
          breakPos = previousUtf8Boundary(remaining, breakPos);
        }
      }
      if (breakPos == 0) breakPos = nextUtf8Boundary(remaining, 0);

      viewerLines.push_back(remaining.substr(0, breakPos));
      size_t skip = breakPos;
      while (skip < remaining.size() && remaining[skip] == ' ') ++skip;
      remaining.erase(0, skip);
    }
  }

  void rebuildViewerLayout() {
    viewerLayoutDirty = false;
    sdFontSystem.ensureLoaded(renderer);
    viewerFontId = SETTINGS.getReaderFontId();
    if (renderer.isSdCardFont(viewerFontId) && !currentText().empty()) {
      renderer.ensureSdCardFontReady(viewerFontId, currentText().c_str(), /*styleMask=*/0x01);
    }

    viewerLineHeight = std::max(
        1, static_cast<int>(renderer.getLineHeight(viewerFontId) * SETTINGS.getReaderLineCompression() + 0.5f));
    viewerMarginX = std::max(12, static_cast<int>(SETTINGS.screenMarginHorizontal));
    viewerContentWidth = std::max(1, renderer.getScreenWidth() - viewerMarginX * 2);

    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    viewerBodyTop = header.y + header.height + std::max(8, static_cast<int>(SETTINGS.screenMarginVertical));
    const int bodyBottom = pencilRect().y - std::max(8, static_cast<int>(SETTINGS.screenMarginVertical));
    viewerLinesPerPage = std::max(1, (bodyBottom - viewerBodyTop) / viewerLineHeight);

    viewerLines.clear();
    const std::string& text = currentText();
    size_t start = 0;
    while (start <= text.size()) {
      const size_t newline = text.find('\n', start);
      const size_t end = newline == std::string::npos ? text.size() : newline;
      std::string logical = text.substr(start, end - start);
      if (!logical.empty() && logical.back() == '\r') logical.pop_back();
      appendWrappedLine(std::move(logical));
      if (newline == std::string::npos) break;
      start = newline + 1;
    }
    if (viewerLines.empty()) viewerLines.emplace_back();

    viewerPageCount = std::max(1, (static_cast<int>(viewerLines.size()) + viewerLinesPerPage - 1) / viewerLinesPerPage);
    viewerPage = std::clamp(viewerPage, 0, viewerPageCount - 1);
  }

  void changePage(const int delta) {
    const int next = std::clamp(viewerPage + delta, 0, viewerPageCount - 1);
    if (next == viewerPage) return;
    viewerPage = next;
    requestUpdate();
  }

  static std::string storageTitle(std::string title) {
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

  bool currentNoteLooksLocked() const {
    const std::string marker = std::string("/Notes/") + storageTitle(viewerTitle) + ".txt.lock";
    return Storage.exists(marker.c_str());
  }

  void drawOpenLockLight(const Rect& rect) {
    const int bodyW = 20;
    const int bodyH = 16;
    const int bodyX = rect.x + (rect.width - bodyW) / 2;
    const int bodyY = rect.y + rect.height / 2;

    auto ditherH = [this](const int x1, const int x2, const int y) {
      for (int x = x1; x <= x2; x += 2) renderer.fillRect(x, y, 1, 1, true);
    };
    auto ditherV = [this](const int x, const int y1, const int y2) {
      for (int y = y1; y <= y2; y += 2) renderer.fillRect(x, y, 1, 1, true);
    };

    ditherH(bodyX, bodyX + bodyW - 1, bodyY);
    ditherH(bodyX, bodyX + bodyW - 1, bodyY + bodyH - 1);
    ditherV(bodyX, bodyY, bodyY + bodyH - 1);
    ditherV(bodyX + bodyW - 1, bodyY, bodyY + bodyH - 1);

    const int shackleLeft = bodyX + 4;
    const int shackleTop = bodyY - 10;
    const int shackleRight = bodyX + 15;
    ditherV(shackleLeft, shackleTop + 4, bodyY);
    ditherH(shackleLeft + 2, shackleRight, shackleTop);
    ditherV(shackleRight, shackleTop, shackleTop + 5);
    renderer.fillRect(bodyX + bodyW / 2, bodyY + 6, 1, 5, true);
  }

  void drawPencil(const Rect& rect) {
    const int cx = rect.x + rect.width / 2;
    const int cy = rect.y + rect.height / 2;
    renderer.drawLine(cx - 9, cy + 8, cx + 8, cy - 9, 3, true);
    renderer.drawLine(cx - 12, cy + 11, cx - 7, cy + 9, 2, true);
    renderer.drawLine(cx + 6, cy - 11, cx + 11, cy - 6, 2, true);
  }
};
