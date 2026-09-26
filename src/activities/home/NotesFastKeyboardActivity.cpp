#include "NotesFastKeyboardActivity.h"

#include <BidiUtils.h>
#include <HalGPIO.h>
#include <HalDisplay.h>
#include <esp_heap_caps.h>
#include <I18n.h>

#include <algorithm>
#include <cstring>

#include "DeviceCapabilities.h"
#include "CrossPointSettings.h"
#include "SdCardFontSystem.h"
#include "activities/util/KeyboardLayoutSet.h"
#include "MappedInputManager.h"
#include "components/TouchHeaderBackButton.h"
#include "components/UITheme.h"
#include "components/UIScale.h"
#include "fontIds.h"

namespace fui = freeink::ui;

namespace {

constexpr fui::ActionId ACTION_KEY = 1;

bool outputEndsWord(const char* out) {
  if (!out || !*out) return false;
  const size_t len = strlen(out);
  const unsigned char c = static_cast<unsigned char>(out[len - 1]);
  if (c >= 0x80) return false;
  return c != '\'' && c != '-' &&
         !((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'));
}

// ---------------------------------------------------------------------------
// URL layers. The SDK builtin layouts have no URL variant (":", "/", ".", the
// snippet panel), so these are app-defined tables over the same public
// KeyboardLayout structs. URLs are ASCII, so the letter rows are EN-arranged
// regardless of UI language.
// ---------------------------------------------------------------------------

#define UK(label, output, value) \
  fui::KeyboardKey { label, output, fui::KeyKind::Normal, fui::StateNormal, value, 1, true, nullptr }
#define UKA(label, output, value, alt) \
  fui::KeyboardKey { label, output, fui::KeyKind::Normal, fui::StateNormal, value, 1, true, alt }
#define UKW(label, output, value, units) \
  fui::KeyboardKey { label, output, fui::KeyKind::Normal, fui::StateNormal, value, units, true, nullptr }
#define UKS(label, kind, value, units) \
  fui::KeyboardKey { label, nullptr, kind, fui::StateNormal, value, units, true, nullptr }

constexpr int16_t URL_PANEL_VALUE = -3;  // mirrors NotesFastKeyboardActivity::URL_PANEL_KEY

const fui::KeyboardKey URL_NUM_ROW[] = {UKA("1", "1", '1', "!"), UKA("2", "2", '2', "@"), UKA("3", "3", '3', "#"),
                                        UKA("4", "4", '4', "$"), UKA("5", "5", '5', "%"), UKA("6", "6", '6', "^"),
                                        UKA("7", "7", '7', "&"), UKA("8", "8", '8', "*"), UKA("9", "9", '9', "("),
                                        UKA("0", "0", '0', ")")};

const fui::KeyboardKey URL_ROW1[] = {UK("q", "q", 'q'), UK("w", "w", 'w'), UK("e", "e", 'e'), UK("r", "r", 'r'),
                                     UK("t", "t", 't'), UK("y", "y", 'y'), UK("u", "u", 'u'), UK("i", "i", 'i'),
                                     UK("o", "o", 'o'), UK("p", "p", 'p')};
const fui::KeyboardKey URL_ROW2[] = {UK("a", "a", 'a'), UK("s", "s", 's'), UK("d", "d", 'd'),
                                     UK("f", "f", 'f'), UK("g", "g", 'g'), UK("h", "h", 'h'),
                                     UK("j", "j", 'j'), UK("k", "k", 'k'), UK("l", "l", 'l')};
const fui::KeyboardKey URL_ROW3[] = {UKS("Shift", fui::KeyKind::Shift, fui::QWERTY_KEY_SHIFT, 2),
                                     UK("z", "z", 'z'),
                                     UK("x", "x", 'x'),
                                     UK("c", "c", 'c'),
                                     UK("v", "v", 'v'),
                                     UK("b", "b", 'b'),
                                     UK("n", "n", 'n'),
                                     UK("m", "m", 'm'),
                                     UKS("Del", fui::KeyKind::Delete, fui::QWERTY_KEY_BACKSPACE, 2)};
// URLs have no spaces, so the URL bottom row spends the space slot on ":",
// "/", "." and the snippet-panel toggle instead (the legacy keyboard did the
// same with its "URL" key).
const fui::KeyboardKey URL_BOTTOM[] = {UKS("?123", fui::KeyKind::Mode, fui::QWERTY_KEY_MODE, 2),
                                       UK(":", ":", ':'),
                                       UK("/", "/", '/'),
                                       UK(".", ".", '.'),
                                       UKW("URL", nullptr, URL_PANEL_VALUE, 2),
                                       UKS("OK", fui::KeyKind::Ok, fui::QWERTY_KEY_ENTER, 2)};

const fui::KeyboardKey URL_SHIFT_ROW1[] = {UK("Q", "Q", 'Q'), UK("W", "W", 'W'), UK("E", "E", 'E'), UK("R", "R", 'R'),
                                           UK("T", "T", 'T'), UK("Y", "Y", 'Y'), UK("U", "U", 'U'), UK("I", "I", 'I'),
                                           UK("O", "O", 'O'), UK("P", "P", 'P')};
const fui::KeyboardKey URL_SHIFT_ROW2[] = {UK("A", "A", 'A'), UK("S", "S", 'S'), UK("D", "D", 'D'),
                                           UK("F", "F", 'F'), UK("G", "G", 'G'), UK("H", "H", 'H'),
                                           UK("J", "J", 'J'), UK("K", "K", 'K'), UK("L", "L", 'L')};
const fui::KeyboardKey URL_SHIFT_ROW3[] = {UKS("Shift", fui::KeyKind::Shift, fui::QWERTY_KEY_SHIFT, 2),
                                           UK("Z", "Z", 'Z'),
                                           UK("X", "X", 'X'),
                                           UK("C", "C", 'C'),
                                           UK("V", "V", 'V'),
                                           UK("B", "B", 'B'),
                                           UK("N", "N", 'N'),
                                           UK("M", "M", 'M'),
                                           UKS("Del", fui::KeyKind::Delete, fui::QWERTY_KEY_BACKSPACE, 2)};

// Snippet keys: multi-character outputs, stable ids above the localized-key
// range so they never collide with layout key ids.
const fui::KeyboardKey URL_SNIP_ROW1[] = {UK("https://", "https://", 2001), UK("www.", "www.", 2002),
                                          UK(".com", ".com", 2003)};
const fui::KeyboardKey URL_SNIP_ROW2[] = {UK("http://", "http://", 2004), UK("192.168.", "192.168.", 2005),
                                          UK(".org", ".org", 2006)};
const fui::KeyboardKey URL_SNIP_ROW3[] = {UK("/opds", "/opds", 2007), UK(":8080", ":8080", 2008),
                                          UK(".net", ".net", 2009)};
const fui::KeyboardKey URL_SNIP_BOTTOM[] = {UKS("abc", fui::KeyKind::Mode, fui::QWERTY_KEY_MODE, 2),
                                            UKW("URL", nullptr, URL_PANEL_VALUE, 2),
                                            UKS("Del", fui::KeyKind::Delete, fui::QWERTY_KEY_BACKSPACE, 2),
                                            UKS("OK", fui::KeyKind::Ok, fui::QWERTY_KEY_ENTER, 2)};

#undef UK
#undef UKA
#undef UKW
#undef UKS

const fui::KeyboardRow URL_ROWS[] = {
    {URL_NUM_ROW, 10, 0}, {URL_ROW1, 10, 0}, {URL_ROW2, 9, 1}, {URL_ROW3, 9, 0}, {URL_BOTTOM, 6, 0}};
const fui::KeyboardRow URL_SHIFT_ROWS[] = {
    {URL_NUM_ROW, 10, 0}, {URL_SHIFT_ROW1, 10, 0}, {URL_SHIFT_ROW2, 9, 1}, {URL_SHIFT_ROW3, 9, 0}, {URL_BOTTOM, 6, 0}};
const fui::KeyboardRow URL_SNIP_ROWS[] = {
    {URL_SNIP_ROW1, 3, 0}, {URL_SNIP_ROW2, 3, 0}, {URL_SNIP_ROW3, 3, 0}, {URL_SNIP_BOTTOM, 4, 0}};

const fui::KeyboardLayout URL_LAYOUT{URL_ROWS, 5};
const fui::KeyboardLayout URL_SHIFT_LAYOUT{URL_SHIFT_ROWS, 5};
const fui::KeyboardLayout URL_SNIPPET_LAYOUT{URL_SNIP_ROWS, 4};

}  // namespace

void NotesFastKeyboardActivity::onEnter() {
  Activity::onEnter();
  cursorPos = text.length();
  layoutId = inputType == InputType::Url ? fui::KeyboardLayoutId::QwertyEn : keyboard_layouts::startingLayout();
  const uint16_t enabledLayouts = keyboard_layouts::enabled();
  showLangKey = (enabledLayouts & (enabledLayouts - 1)) != 0;
  shifted = false;
  symbols = false;
  urlPanel = false;
  cursorMode = false;
  togglePos = false;
  passwordVisible = false;
  selRow = 0;
  selCol = 0;
  delPressCount = 0;
  hintVisible = false;
  hintShowTime = 0;
  rightHeld = false;
  rightLongHandled = false;
  savedCursorPos = 0;
  rightStartCursorPos = 0;
  touchRouter.reset();
  touchRouter.holdMs = TOUCH_LONG_PRESS_MS;
  touchRouter.overrideHoldMs = TOUCH_DEL_LONG_PRESS_MS;
  interactionsReady = false;
  if (predictiveEnabled()) {
    predictiveText.load();
    predictiveText.seedFromText(text);
  }
  editing = false;
  viewerPage = 0;
  viewerLayoutDirty = true;
  notesWindowShadowValid = false;
  if (viewerEnabled()) {
    sdFontSystem.ensureLoaded(renderer);
    rebuildViewerLayout();
    requestUpdate(true);
  } else {
    requestUpdate();
  }
}

void NotesFastKeyboardActivity::onExit() {
  if (predictiveEnabled()) predictiveText.save();
  releaseNotesWindowShadow();
  Activity::onExit();
}

bool NotesFastKeyboardActivity::predictiveEnabled() const { return inputType == InputType::Multiline; }

bool NotesFastKeyboardActivity::viewerPointIn(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

Rect NotesFastKeyboardActivity::viewerHeaderActionRect() const {
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto backLayout = TouchHeaderBackButton::layout(header);
  const int controlOffset = std::min(
      TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
      std::max(0, header.y + header.height -
                      (backLayout.iconRect.y +
                       (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
  const int width = std::max(0, headerActionReserveWidth());
  return Rect{renderer.getScreenWidth() - width, header.y + controlOffset, width, header.height};
}

Rect NotesFastKeyboardActivity::pencilRect() const {
  constexpr int width = 58;
  constexpr int height = 44;
  return Rect{(renderer.getScreenWidth() - width) / 2, renderer.getScreenHeight() - height - 10, width, height};
}

void NotesFastKeyboardActivity::drawHeaderAction() {
  if (headerActionReserveWidth() <= 0) return;
  if (headerActionLocked()) {
    drawNotesHeaderAction();
  } else {
    drawOpenLockLight(lockArtworkRectOnTitleBaseline(viewerHeaderActionRect()));
  }
}

Rect NotesFastKeyboardActivity::lockArtworkRectOnTitleBaseline(Rect rect) const {
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto headerLayout = TouchHeaderBackButton::layout(header);
  const int iconBottom =
      headerLayout.iconRect.y + (headerLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2;
  const int availableOffset = std::max(0, header.y + header.height - iconBottom);
  const int titleOffset =
      std::clamp(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET, 0, availableOffset);
  const auto scale = uiScaleSpec();
  const int titleBaselineY =
      headerLayout.iconRect.y + titleOffset +
      std::max(0, (headerLayout.iconRect.height - renderer.getLineHeight(scale.titleFontId)) / 2) +
      renderer.getFontAscenderSize(scale.titleFontId);

  constexpr int lockBodyHeight = 16;
  const int currentBodyBottomY = rect.y + rect.height / 2 + lockBodyHeight - 1;
  rect.y += titleBaselineY - currentBodyBottomY;
  return rect;
}

size_t NotesFastKeyboardActivity::previousUtf8Boundary(const std::string& value, size_t pos) {
  if (pos == 0) return 0;
  --pos;
  while (pos > 0 && (static_cast<unsigned char>(value[pos]) & 0xC0) == 0x80) --pos;
  return pos;
}

size_t NotesFastKeyboardActivity::nextUtf8Boundary(const std::string& value, const size_t pos) {
  if (pos >= value.size()) return value.size();
  size_t next = pos + 1;
  while (next < value.size() && (static_cast<unsigned char>(value[next]) & 0xC0) == 0x80) ++next;
  return next;
}

void NotesFastKeyboardActivity::appendWrappedLine(std::string remaining) {
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
      if (space != std::string::npos && space > 0) breakPos = space;
      else breakPos = previousUtf8Boundary(remaining, breakPos);
    }
    if (breakPos == 0) breakPos = nextUtf8Boundary(remaining, 0);

    viewerLines.push_back(remaining.substr(0, breakPos));
    size_t skip = breakPos;
    while (skip < remaining.size() && remaining[skip] == ' ') ++skip;
    remaining.erase(0, skip);
  }
}

void NotesFastKeyboardActivity::rebuildViewerLayout() {
  viewerLayoutDirty = false;
  sdFontSystem.ensureLoaded(renderer);
  viewerFontId = SETTINGS.getReaderFontId();
  if (renderer.isSdCardFont(viewerFontId) && !text.empty()) {
    renderer.ensureSdCardFontReady(viewerFontId, text.c_str(), 0x01);
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

  viewerPageCount =
      std::max(1, (static_cast<int>(viewerLines.size()) + viewerLinesPerPage - 1) / viewerLinesPerPage);
  viewerPage = std::clamp(viewerPage, 0, viewerPageCount - 1);
}

void NotesFastKeyboardActivity::changeViewerPage(const int delta) {
  const int next = std::clamp(viewerPage + delta, 0, viewerPageCount - 1);
  if (next == viewerPage) return;
  viewerPage = next;
  notesWindowShadowValid = false;
  requestUpdate();
}

void NotesFastKeyboardActivity::drawOpenLockLight(const Rect& rect) {
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

void NotesFastKeyboardActivity::drawPencil(const Rect& rect) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  renderer.drawLine(cx - 9, cy + 8, cx + 8, cy - 9, 3, true);
  renderer.drawLine(cx - 12, cy + 11, cx - 7, cy + 9, 2, true);
  renderer.drawLine(cx + 6, cy - 11, cx + 11, cy - 6, 2, true);
}

void NotesFastKeyboardActivity::loopViewer() {
  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty)) {
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const Rect backRect = TouchHeaderBackButton::layout(header).touchRect;
    if (viewerPointIn(backRect, tx, ty)) {
      finish();
      return;
    }
    if (viewerPointIn(pencilRect(), tx, ty)) {
      editing = true;
      notesWindowShadowValid = false;
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
    changeViewerPage(-1);
    return;
  }
  if (mappedInput.wasReleased(MappedInputManager::Button::Down) ||
      mappedInput.wasReleased(MappedInputManager::Button::Right)) {
    changeViewerPage(1);
    return;
  }

  const auto swipe = mappedInput.wasSwipe();
  if (swipe == MappedInputManager::SwipeDir::Up) changeViewerPage(1);
  else if (swipe == MappedInputManager::SwipeDir::Down) changeViewerPage(-1);
}

void NotesFastKeyboardActivity::renderViewer() {
  if (viewerLayoutDirty) rebuildViewerLayout();

  renderer.clearScreen();
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  TouchHeaderBackButton::draw(renderer, header, viewerTitle.c_str(), false, 0);

  const size_t firstLine = static_cast<size_t>(viewerPage * viewerLinesPerPage);
  const size_t endLine =
      std::min(viewerLines.size(), firstLine + static_cast<size_t>(viewerLinesPerPage));
  int y = viewerBodyTop;
  for (size_t i = firstLine; i < endLine; ++i) {
    const std::string& line = viewerLines[i];
    if (!line.empty()) {
      int x = viewerMarginX;
      uint8_t alignment = SETTINGS.paragraphAlignment;
      const bool rtl = BidiUtils::startsWithRtl(line.c_str(), BidiUtils::RTL_PARAGRAPH_PROBE_DEPTH);
      if (rtl && (alignment == CrossPointSettings::LEFT_ALIGN ||
                  alignment == CrossPointSettings::JUSTIFIED)) {
        alignment = CrossPointSettings::RIGHT_ALIGN;
      }
      const int textWidth = renderer.getTextWidth(viewerFontId, line.c_str());
      if (alignment == CrossPointSettings::CENTER_ALIGN) x = viewerMarginX + (viewerContentWidth - textWidth) / 2;
      else if (alignment == CrossPointSettings::RIGHT_ALIGN) x = viewerMarginX + viewerContentWidth - textWidth;
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
  notesWindowShadowValid = false;
}

void NotesFastKeyboardActivity::releaseNotesWindowShadow() {
  if (notesWindowShadow != nullptr) {
    heap_caps_free(notesWindowShadow);
    notesWindowShadow = nullptr;
  }
  notesWindowShadowValid = false;
  notesFastRefreshCount = 0;
}

void NotesFastKeyboardActivity::refreshNotesPanel() {
  uint8_t* const fb = display.getFrameBuffer();
  const uint32_t bufferSize = display.getBufferSize();
  const uint16_t panelW = display.getDisplayWidth();
  const uint16_t panelH = display.getDisplayHeight();
  const uint16_t wb = display.getDisplayWidthBytes();

  if (fb == nullptr || bufferSize == 0 || wb == 0 || panelW == 0 || panelH == 0 ||
      renderer.getOrientation() != GfxRenderer::Portrait) {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    notesWindowShadowValid = false;
    notesFastRefreshCount = 0;
    return;
  }

  if (notesWindowShadow == nullptr) {
    notesWindowShadow = static_cast<uint8_t*>(
        heap_caps_malloc(bufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    notesWindowShadowValid = false;
  }

  auto cleanRefresh = [&]() {
    renderer.displayBuffer(HalDisplay::FAST_REFRESH);
    if (notesWindowShadow != nullptr) {
      memcpy(notesWindowShadow, fb, bufferSize);
      notesWindowShadowValid = true;
    }
    notesFastRefreshCount = 0;
  };

  if (notesWindowShadow == nullptr || !notesWindowShadowValid) {
    cleanRefresh();
    return;
  }

  uint32_t changedBytes = 0;
  for (uint32_t i = 0; i < bufferSize; ++i) {
    if (fb[i] != notesWindowShadow[i]) ++changedBytes;
  }
  if (changedBytes == 0) return;

  // A layout/layer change dirties a large part of the keyboard. Those events
  // are infrequent and deserve the stock clean waveform instead of stretching
  // the Missile-oriented window waveform over a large UI surface.
  if (changedBytes > 3500 ||
      notesFastRefreshCount >= NOTES_FAST_REFRESHES_BEFORE_CLEAN) {
    cleanRefresh();
    return;
  }

  struct DirtyBox {
    uint16_t minByte;
    uint16_t maxByte;
    uint16_t minY;
    uint16_t maxY;
    bool changed;
  };

  auto findDirty = [&](const uint16_t firstByte, const uint16_t endByte) {
    DirtyBox box{endByte, 0, panelH, 0, false};
    for (uint16_t y = 0; y < panelH; ++y) {
      const uint32_t row = static_cast<uint32_t>(y) * wb;
      for (uint16_t bx = firstByte; bx < endByte; ++bx) {
        const uint32_t offset = row + bx;
        if (fb[offset] == notesWindowShadow[offset]) continue;
        box.changed = true;
        if (bx < box.minByte) box.minByte = bx;
        if (bx > box.maxByte) box.maxByte = bx;
        if (y < box.minY) box.minY = y;
        if (y > box.maxY) box.maxY = y;
      }
    }
    return box;
  };

  auto displayDirty = [&](const DirtyBox& box) {
    if (!box.changed) return;
    const uint16_t x = static_cast<uint16_t>(box.minByte * 8);
    const uint16_t y = box.minY;
    const uint16_t w = static_cast<uint16_t>((box.maxByte - box.minByte + 1) * 8);
    const uint16_t h = static_cast<uint16_t>(box.maxY - box.minY + 1);
    display.displayWindow(x, y, w, h, false);

    const uint16_t copyBytes = static_cast<uint16_t>(box.maxByte - box.minByte + 1);
    for (uint16_t row = box.minY; row <= box.maxY; ++row) {
      const uint32_t offset = static_cast<uint32_t>(row) * wb + box.minByte;
      memcpy(notesWindowShadow + offset, fb + offset, copyBytes);
    }
  };

  // Portrait rendering maps logical Y to physical X. Split text/prediction
  // from the keyboard so a changed glyph and a changed key never create one
  // giant physical refresh rectangle spanning the whole display.
  const fui::Rect kb = keyboardRect();
  const int splitPixel = std::clamp(static_cast<int>(kb.y) & ~7, 8, static_cast<int>(panelW) - 8);
  const uint16_t splitByte = static_cast<uint16_t>(splitPixel / 8);

  const DirtyBox upper = findDirty(0, splitByte);
  const DirtyBox keyboard = findDirty(splitByte, wb);
  displayDirty(upper);
  displayDirty(keyboard);

  ++notesFastRefreshCount;
}

const fui::KeyboardLayout& NotesFastKeyboardActivity::currentLayout() const {
  if (symbols) return fui::builtinKeyboardLayout(layoutId, shifted, true);
  if (inputType == InputType::Url) {
    if (urlPanel) return URL_SNIPPET_LAYOUT;
    return shifted ? URL_SHIFT_LAYOUT : URL_LAYOUT;
  }
  return fui::builtinKeyboardLayout(layoutId, shifted, false, /*numberRow=*/true, showLangKey);
}

const fui::KeyboardKey* NotesFastKeyboardActivity::selectedKey() const {
  const fui::KeyboardLayout& layout = currentLayout();
  if (selRow < 0 || selRow >= layout.rowCount) return nullptr;
  const fui::KeyboardRow& row = layout.rows[selRow];
  if (selCol < 0 || selCol >= row.count) return nullptr;
  return &row.keys[selCol];
}

int NotesFastKeyboardActivity::selectedLogicalIndex() const {
  const fui::KeyboardLayout& layout = currentLayout();
  int index = 0;
  for (int r = 0; r < selRow && r < layout.rowCount; r++) {
    index += layout.rows[r].count;
  }
  return index + selCol;
}

void NotesFastKeyboardActivity::clampSelection() {
  const fui::KeyboardLayout& layout = currentLayout();
  if (layout.rowCount == 0) {
    selRow = 0;
    selCol = 0;
    return;
  }
  if (selRow < 0) selRow = 0;
  if (selRow >= layout.rowCount) selRow = layout.rowCount - 1;
  const int cols = layout.rows[selRow].count;
  if (selCol < 0) selCol = 0;
  if (selCol >= cols) selCol = cols > 0 ? cols - 1 : 0;
}

void NotesFastKeyboardActivity::moveSelectionRow(const int delta) {
  const fui::KeyboardLayout& layout = currentLayout();
  if (layout.rowCount == 0) return;
  const int oldCols = selRow < layout.rowCount ? layout.rows[selRow].count : 1;
  selRow = (selRow + delta + layout.rowCount) % layout.rowCount;
  const int newCols = layout.rows[selRow].count;
  // Proportional column mapping keeps vertical travel intuitive between rows
  // of different key counts (e.g. a 10-key letter row over a 6-key bottom row).
  if (oldCols > 0 && newCols > 0 && oldCols != newCols) {
    selCol = selCol * newCols / oldCols;
  }
  clampSelection();
}

void NotesFastKeyboardActivity::moveSelectionCol(const int delta) {
  const fui::KeyboardLayout& layout = currentLayout();
  if (selRow < 0 || selRow >= layout.rowCount) return;
  const int cols = layout.rows[selRow].count;
  if (cols <= 0) return;
  selCol = (selCol + delta + cols) % cols;
}

bool NotesFastKeyboardActivity::syncSelectionToValue(const int16_t value) {
  const fui::KeyboardLayout& layout = currentLayout();
  for (int r = 0; r < layout.rowCount; r++) {
    for (int c = 0; c < layout.rows[r].count; c++) {
      if (layout.rows[r].keys[c].value == value) {
        selRow = r;
        selCol = c;
        return true;
      }
    }
  }
  return false;
}

size_t NotesFastKeyboardActivity::utf8Prev(const std::string& s, size_t pos) {
  if (pos == 0) return 0;
  pos--;
  while (pos > 0 && (static_cast<uint8_t>(s[pos]) & 0xC0) == 0x80) pos--;
  return pos;
}

size_t NotesFastKeyboardActivity::utf8Next(const std::string& s, size_t pos) {
  if (pos >= s.length()) return s.length();
  pos++;
  while (pos < s.length() && (static_cast<uint8_t>(s[pos]) & 0xC0) == 0x80) pos++;
  return pos;
}

void NotesFastKeyboardActivity::insertUtf8(const char* out) {
  if (!out || !*out) return;
  const size_t n = strlen(out);
  if (maxLength != 0 && text.length() + n > maxLength) return;
  if (cursorPos > text.length()) cursorPos = text.length();
  text.insert(cursorPos, out, n);
  cursorPos += n;
}

bool NotesFastKeyboardActivity::backspaceUtf8() {
  if (text.empty() || cursorPos == 0) return false;
  const size_t prev = utf8Prev(text, cursorPos);
  text.erase(prev, cursorPos - prev);
  cursorPos = prev;
  return true;
}

bool NotesFastKeyboardActivity::activateValue(const int16_t value, const bool longPress) {
  switch (value) {
    case fui::QWERTY_KEY_SHIFT:
      delPressCount = 0;
      hintVisible = false;
      // Letters: case toggle. Symbols: pages between "?123" and "#+=".
      shifted = !shifted;
      clampSelection();
      return true;
    case fui::QWERTY_KEY_MODE:
      delPressCount = 0;
      hintVisible = false;
      if (urlPanel) {
        urlPanel = false;
      } else {
        symbols = !symbols;
        shifted = false;
      }
      clampSelection();
      return true;
    case fui::QWERTY_KEY_LANG: {
      delPressCount = 0;
      hintVisible = false;
      const auto nextLayout = keyboard_layouts::next(layoutId);
      if (nextLayout == layoutId) return false;
      layoutId = nextLayout;
      shifted = false;
      clampSelection();
      return true;
    }
    case URL_PANEL_KEY:
      delPressCount = 0;
      hintVisible = false;
      urlPanel = !urlPanel;
      symbols = false;
      shifted = false;
      clampSelection();
      return true;
    case fui::QWERTY_KEY_ENTER:
      if (inputType == InputType::Multiline) {
        predictiveText.learnWordBefore(text, cursorPos);
        insertUtf8("\n");
        return true;
      }
      if (text.length() < minLength) return true;
      onComplete(text);
      return false;
    case fui::QWERTY_KEY_BACKSPACE:
      if (longPress) {
        text.clear();
        cursorPos = 0;
        return true;
      }
      delPressCount++;
      if (delPressCount >= 2) {
        hintVisible = true;
        hintShowTime = millis();
      }
      backspaceUtf8();
      return true;
    default: {
      delPressCount = 0;
      hintVisible = false;
      const fui::KeyboardLayout& layer = currentLayout();
      // keyboardAltOutputFor covers explicit alts and the letter case-flip.
      const char* out = longPress ? fui::keyboardAltOutputFor(layer, value) : nullptr;
      if (!out) out = fui::keyboardOutputFor(layer, value);
      if (!out) return false;
      if (predictiveEnabled() && outputEndsWord(out)) predictiveText.learnWordBefore(text, cursorPos);
      insertUtf8(out);
      if (shifted && !symbols) {
        shifted = false;  // shift auto-releases after one character
        clampSelection();
      }
      return true;
    }
  }
}

bool NotesFastKeyboardActivity::clearAllOrAltOnSelected() {
  const fui::KeyboardKey* key = selectedKey();
  if (!key) return false;
  if (key->value == fui::QWERTY_KEY_BACKSPACE) {
    text.clear();
    cursorPos = 0;
    return true;
  }
  // Explicit alts and the letter case-flip, same as touch long-press.
  const char* alt = fui::keyboardAltOutputFor(currentLayout(), key->value);
  if (alt) {
    insertUtf8(alt);
    return true;
  }
  return false;
}

std::string NotesFastKeyboardActivity::displayTextForCurrentState() const {
  std::string displayText = text;
  if (inputType != InputType::Password || passwordVisible) {
    return displayText;
  }

  size_t revealPos;
  if (cursorMode) {
    revealPos = text.length();  // no reveal in displayText; block draws actual char directly
  } else {
    revealPos = (text.length() > 0 && cursorPos > 0) ? cursorPos - 1 : std::string::npos;
  }
  for (size_t i = 0; i < displayText.length(); i++) {
    if (i != revealPos) {
      displayText[i] = '*';
    }
  }
  return displayText;
}

int NotesFastKeyboardActivity::measureRange(std::string& s, const int start, const int end) const {
  if (end <= start) return 0;
  // s[end] is writable even at s.length() (the terminator slot); only '\0' may
  // be written there, which is exactly what the measurement needs.
  const char saved = s[end];
  s[end] = '\0';
  const int width = renderer.getTextAdvanceX(UI_12_FONT_ID, s.c_str() + start, EpdFontFamily::REGULAR);
  s[end] = saved;
  return width;
}

bool NotesFastKeyboardActivity::rangeIsRtl(std::string& s, const int start, const int end) const {
  if (end <= start) return false;
  const char saved = s[end];
  s[end] = '\0';
  const bool isRtl = BidiUtils::detectParagraphLevel(s.c_str() + start, 0, end - start) != 0;
  s[end] = saved;
  return isRtl;
}

int NotesFastKeyboardActivity::lineBreakEnd(std::string& s, const int start, const int maxWidth) const {
  const int len = static_cast<int>(s.length());
  const size_t newlinePos = s.find('\n', static_cast<size_t>(start));
  const int hardEnd = newlinePos == std::string::npos ? len : static_cast<int>(newlinePos);
  if (measureRange(s, start, hardEnd) <= maxWidth) return hardEnd;
  int lo = start + 1;
  int hi = hardEnd - 1;
  int best = start + 1;
  while (lo <= hi) {
    const int mid = lo + (hi - lo) / 2;
    if (measureRange(s, start, mid) <= maxWidth) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  // The byte-index search can stop inside a character; snap back to a boundary,
  // keeping one whole character so the wrap loop always advances.
  const int firstCharEnd = static_cast<int>(utf8Next(s, static_cast<size_t>(start)));
  while (best > start && (static_cast<uint8_t>(s[best]) & 0xC0) == 0x80) best--;
  // Widths measured mid-character are unreliable, so the search can overshoot.
  while (best > firstCharEnd && measureRange(s, start, best) > maxWidth) {
    best = static_cast<int>(utf8Prev(s, static_cast<size_t>(best)));
  }
  return best < firstCharEnd ? firstCharEnd : best;
}

NotesFastKeyboardActivity::InputFieldTouchTarget NotesFastKeyboardActivity::inputFieldTouchTargetFromPoint(
    const int x, const int y, size_t& position) const {
  // Key taps are the overwhelmingly common case; they land on the keyboard,
  // never the text field, so skip the wrap/measure work entirely.
  if (y >= keyboardRect().y) return InputFieldTouchTarget::None;

  const int pageWidth = renderer.getScreenWidth();
  const auto& metrics = UITheme::getInstance().getMetrics();

  const int lineHeight = renderer.getLineHeight(UI_12_FONT_ID);
  const int inputStartY = metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) +
                          metrics.verticalSpacing + metrics.verticalSpacing * 4 + metrics.keyboardVerticalOffset;

  int availableWidth = pageWidth;
  // Clear the side-button hint gutters, which only render on edge-button boards without touch.
  if (deviceUsesSideButtonHintGutters(gpio)) {
    availableWidth -= 2 * metrics.sideButtonHintsWidth;
  }
  const int effectiveMargin = (pageWidth - availableWidth * metrics.keyboardTextFieldWidthPercent / 100) / 2;
  const int toggleGap = inputType == InputType::Password ? 4 : 0;
  const int toggleReserve = inputType == InputType::Password ? std::max(renderer.getTextWidth(UI_12_FONT_ID, "[abc]"),
                                                                        renderer.getTextWidth(UI_12_FONT_ID, "[***]")) +
                                                                   toggleGap
                                                             : 0;
  const int textAreaWidth = pageWidth - 2 * effectiveMargin - toggleReserve;
  const int maxLineWidth = textAreaWidth;
  const bool centerText = metrics.keyboardCenteredText;
  std::string displayText = displayTextForCurrentState();

  int lineStartIdx = 0;
  int lineY = inputStartY;
  int lastLineStartIdx = 0;
  int lastLineEndIdx = static_cast<int>(displayText.length());
  int lastLineStartX = effectiveMargin;
  int lastLineWidth = 0;

  while (true) {
    const int lineEndIdx = lineBreakEnd(displayText, lineStartIdx, maxLineWidth);
    const bool forcedBreak = lineEndIdx < static_cast<int>(displayText.length()) && displayText[lineEndIdx] == '\n';
    const int textWidth = measureRange(displayText, lineStartIdx, lineEndIdx);
    const bool isLastLine = lineEndIdx == static_cast<int>(displayText.length());
    if (isLastLine && inputType == InputType::Password && x >= effectiveMargin + maxLineWidth &&
        x < pageWidth - effectiveMargin && y >= lineY - metrics.verticalSpacing &&
        y < lineY + lineHeight + metrics.verticalSpacing) {
      return InputFieldTouchTarget::PasswordToggle;
    }

    const int lineStartX = centerText ? effectiveMargin + (maxLineWidth - textWidth) / 2 : effectiveMargin;
    const bool isRtl = rangeIsRtl(displayText, lineStartIdx, lineEndIdx);
    lastLineStartIdx = lineStartIdx;
    lastLineEndIdx = lineEndIdx;
    lastLineStartX = lineStartX;
    lastLineWidth = textWidth;

    if (y >= lineY - metrics.verticalSpacing && y < lineY + lineHeight + metrics.verticalSpacing) {
      if (x <= lineStartX) {
        position = static_cast<size_t>(isRtl ? lineEndIdx : lineStartIdx);
        return InputFieldTouchTarget::Cursor;
      }
      if (x >= lineStartX + textWidth) {
        position = static_cast<size_t>(isRtl ? lineStartIdx : lineEndIdx);
        return InputFieldTouchTarget::Cursor;
      }

      int previousWidth = 0;
      for (int i = lineStartIdx; i < lineEndIdx;) {
        const int next = static_cast<int>(utf8Next(displayText, static_cast<size_t>(i)));
        const int nextWidth = measureRange(displayText, lineStartIdx, next);
        const int halfAdvance = (nextWidth - previousWidth) / 2;
        const int midpoint =
            isRtl ? lineStartX + textWidth - previousWidth - halfAdvance : lineStartX + previousWidth + halfAdvance;
        if ((isRtl && x >= midpoint) || (!isRtl && x < midpoint)) {
          position = static_cast<size_t>(i);
          return InputFieldTouchTarget::Cursor;
        }
        previousWidth = nextWidth;
        i = next;
      }
      position = static_cast<size_t>(lineEndIdx);
      return InputFieldTouchTarget::Cursor;
    }

    if (lineEndIdx == static_cast<int>(displayText.length())) {
      break;
    }

    lineY += lineHeight;
    lineStartIdx = forcedBreak ? lineEndIdx + 1 : lineEndIdx;
  }

  const int underlineBottom = lineY + lineHeight + metrics.verticalSpacing + 8;
  if (y >= inputStartY - metrics.verticalSpacing && y < underlineBottom && x >= effectiveMargin &&
      x < effectiveMargin + maxLineWidth + toggleReserve) {
    const bool isRtl = rangeIsRtl(displayText, lastLineStartIdx, lastLineEndIdx);
    const bool insideText = x < lastLineStartX + lastLineWidth;
    position = static_cast<size_t>(insideText == isRtl ? lastLineEndIdx : lastLineStartIdx);
    return InputFieldTouchTarget::Cursor;
  }

  return InputFieldTouchTarget::None;
}

fui::Rect NotesFastKeyboardActivity::keyboardRect() const {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int pageWidth = renderer.getScreenWidth();
  const int pageHeight = renderer.getScreenHeight();
  const int rows = currentLayout().rowCount;
  const int gap = metrics.keyboardKeySpacing;
  const int height = rows * metrics.keyboardKeyHeight + (rows > 1 ? (rows - 1) * gap : 0);
  const int width = pageWidth * metrics.keyboardWidthPercent / 100;
  const int x = (pageWidth - width) / 2;
  const int y =
      pageHeight - metrics.buttonHintsHeight - metrics.verticalSpacing - height + metrics.keyboardVerticalOffset;
  return fui::Rect{static_cast<int16_t>(x), static_cast<int16_t>(y), static_cast<int16_t>(width),
                   static_cast<int16_t>(height)};
}

fui::Rect NotesFastKeyboardActivity::predictiveBarRect() const {
  const fui::Rect kb = keyboardRect();
  const auto& metrics = UITheme::getInstance().getMetrics();
  // Notes uses a taller prediction bar than the generic keyboard: easier
  // to read and a larger touch target without changing the global keyboard UI.
  const int height = std::max(52, renderer.getLineHeight(UI_10_FONT_ID) + 24);
  const int y = std::max(0, static_cast<int>(kb.y) - metrics.verticalSpacing - height);
  return fui::Rect{kb.x, static_cast<int16_t>(y), kb.width, static_cast<int16_t>(height)};
}

void NotesFastKeyboardActivity::loop() {
  if (viewerEnabled() && !editing) {
    loopViewer();
    return;
  }
#if CROSSINK_APP_CAP_TOUCH
  if (TouchHeaderBackButton::wasTapped(mappedInput, renderer)) {
    if (inputType == InputType::Multiline) {
      onComplete(text);
    } else {
      onCancel();
    }
    return;
  }

  int tx = 0;
  int ty = 0;

  if (mappedInput.wasScreenTapped(tx, ty)) {
    if (handleHeaderActionTap(tx, ty)) return;

    if (predictiveEnabled() && !cursorMode && !symbols && !urlPanel) {
      const fui::Rect bar = predictiveBarRect();
      if (tx >= bar.x && tx < bar.x + bar.width && ty >= bar.y && ty < bar.y + bar.height) {
        const auto options = predictiveText.suggestions(text, cursorPos);
        int index = bar.width > 0 ? (tx - bar.x) * 3 / bar.width : 0;
        index = std::clamp(index, 0, 2);
        if (!options[index].empty() && predictiveText.applySuggestion(text, cursorPos, maxLength, options[index])) {
          delPressCount = 0;
          hintVisible = false;
          shifted = false;
          touchRouter.reset();
          requestUpdate();
        }
        return;
      }
    }

    size_t touchedCursorPos = 0;
    const InputFieldTouchTarget inputTarget = inputFieldTouchTargetFromPoint(tx, ty, touchedCursorPos);
    if (inputTarget == InputFieldTouchTarget::PasswordToggle) {
      passwordVisible = !passwordVisible;
      togglePos = false;
      hintVisible = false;
      requestUpdate();
      return;
    }
    if (inputTarget == InputFieldTouchTarget::Cursor) {
      cursorPos = std::min(touchedCursorPos, text.length());
      cursorMode = false;
      togglePos = false;
      hintVisible = false;
      // The masked text field maps taps per byte; snap back to a boundary so
      // the cursor never lands inside a multi-byte character.
      while (cursorPos > 0 && cursorPos < text.length() && (static_cast<uint8_t>(text[cursorPos]) & 0xC0) == 0x80) {
        cursorPos--;
      }
      touchRouter.reset();
      requestUpdate();
      return;
    }
  }

  if (!cursorMode && interactionsReady.load(std::memory_order_acquire)) {
    unsigned long touchHeldMs = 0;
    const bool tapCandidate = mappedInput.isScreenTouchTapCandidate(tx, ty, touchHeldMs);
    int tapX = 0;
    int tapY = 0;
    const bool tapped = mappedInput.wasScreenTapped(tapX, tapY);
    int hx = 0;
    int hy = 0;
    const bool inContact = mappedInput.isScreenTouchHeld(hx, hy);

    const fui::TouchHoldRouter::Result result =
        touchRouter.update(interactions, tapCandidate, static_cast<int16_t>(tx), static_cast<int16_t>(ty), tapped,
                           static_cast<int16_t>(tapX), static_cast<int16_t>(tapY), inContact, millis());
    if (result.event) {
      syncSelectionToValue(result.event.value);
      if (activateValue(result.event.value, result.event.longPress)) {
        requestUpdate();
      }
      return;
    }
    // Do not refresh e-ink only for transient touch highlighting.
    // The key event below performs the single useful redraw after text changes.
    if (tapCandidate || tapped) {
      return;
    }
  }
#endif

  if (!cursorMode && mappedInput.wasPressed(MappedInputManager::Button::Up)) {
    upHeld = true;
    upLongHandled = false;
  }

  if (upHeld && !upLongHandled && mappedInput.isPressed(MappedInputManager::Button::Up) &&
      mappedInput.getHeldTime() > LONG_PRESS_MS) {
    cursorMode = true;
    upLongHandled = true;
    hintVisible = true;
    hintShowTime = millis();
    requestUpdate();
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Up)) {
    if (upHeld && !upLongHandled && !cursorMode) {
      moveSelectionRow(-1);
      requestUpdate();
    }
    upHeld = false;
    upLongHandled = false;
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Down)) {
    downHeld = true;
    if (cursorMode) {
      togglePos = false;
      passwordVisible = false;
      cursorMode = false;
      hintVisible = false;
      downLongHandled = true;
      requestUpdate();
    } else {
      downLongHandled = false;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Down)) {
    if (downHeld && !downLongHandled && !cursorMode) {
      moveSelectionRow(1);
      requestUpdate();
    }
    downHeld = false;
    downLongHandled = false;
  }

  buttonNavigator.onPressAndContinuous({MappedInputManager::Button::Left}, [this] {
    if (cursorMode) return;
    moveSelectionCol(-1);
    requestUpdate();
  });

  if (mappedInput.wasReleased(MappedInputManager::Button::Left)) {
    if (cursorMode) {
      if (togglePos) {
        cursorPos = savedCursorPos;
        togglePos = false;
        requestUpdate();
      } else if (cursorPos > 0) {
        cursorPos = utf8Prev(text, cursorPos);
        requestUpdate();
      }
    }
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Right)) {
    if (cursorMode && inputType == InputType::Password && !togglePos) {
      rightHeld = true;
      rightLongHandled = false;
      rightStartCursorPos = cursorPos;
    }
  }

  buttonNavigator.onPressAndContinuous({MappedInputManager::Button::Right}, [this] {
    if (cursorMode) return;
    moveSelectionCol(1);
    requestUpdate();
  });

  if (rightHeld && !rightLongHandled && mappedInput.isPressed(MappedInputManager::Button::Right) &&
      mappedInput.getHeldTime() > LONG_PRESS_MS) {
    if (cursorMode && inputType == InputType::Password && !togglePos) {
      savedCursorPos = rightStartCursorPos;
      togglePos = true;
      rightLongHandled = true;
      requestUpdate();
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Right)) {
    if (cursorMode && inputType == InputType::Password) {
      rightHeld = false;
      rightLongHandled = false;
    }
    if (cursorMode && !togglePos && cursorPos < text.length()) {
      cursorPos = utf8Next(text, cursorPos);
      requestUpdate();
    }
    if (cursorMode) return;
    rightHeld = false;
    rightLongHandled = false;
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Confirm)) {
    confirmHeld = true;
    confirmLongHandled = false;
  }

  const fui::KeyboardKey* selKey = selectedKey();
  const bool selectedDel = selKey && selKey->value == fui::QWERTY_KEY_BACKSPACE;

  if (confirmHeld && !confirmLongHandled && mappedInput.isPressed(MappedInputManager::Button::Confirm) &&
      mappedInput.getHeldTime() > DEL_LONG_PRESS_MS && selectedDel) {
    clearAllOrAltOnSelected();
    confirmLongHandled = true;
    requestUpdate();
  }

  if (confirmHeld && !confirmLongHandled && mappedInput.isPressed(MappedInputManager::Button::Confirm) &&
      mappedInput.getHeldTime() > LONG_PRESS_MS) {
    if (!selectedDel && clearAllOrAltOnSelected()) {
      requestUpdate();
      confirmLongHandled = true;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (confirmHeld && !confirmLongHandled && !cursorMode) {
      if (selKey && activateValue(selKey->value, false)) {
        requestUpdate();
      }
    } else if (confirmHeld && !confirmLongHandled && cursorMode && inputType == InputType::Password && togglePos) {
      passwordVisible = !passwordVisible;
      requestUpdate();
    }
    confirmHeld = false;
    confirmLongHandled = false;
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    if (inputType == InputType::Multiline) {
      onComplete(text);
    } else {
      onCancel();
    }
  }

  if (hintVisible && !cursorMode && millis() - hintShowTime > 4000) {
    hintVisible = false;
    requestUpdate();
  }
}

void NotesFastKeyboardActivity::render(RenderLock&&) {
  if (viewerEnabled() && !editing) {
    renderViewer();
    return;
  }
  renderer.clearScreen();

  const auto pageWidth = renderer.getScreenWidth();
  const auto& metrics = UITheme::getInstance().getMetrics();

  const Rect header{0, metrics.topPadding, pageWidth, TouchHeaderBackButton::height(metrics, mappedInput)};
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, header, title.c_str(), false, headerActionReserveWidth());
  } else {
    GUI.drawHeader(renderer, header, title.c_str());
  }
  drawHeaderAction();

  const int lineHeight = renderer.getLineHeight(UI_12_FONT_ID);
  const int inputStartY = metrics.topPadding + TouchHeaderBackButton::height(metrics, mappedInput) +
                          metrics.verticalSpacing + metrics.verticalSpacing * 4 + metrics.keyboardVerticalOffset;
  int inputHeight = 0;

  std::string displayText = displayTextForCurrentState();

  const bool isPassword = (inputType == InputType::Password);
  int availableWidth = pageWidth;
  // Clear the side-button hint gutters, which only render on edge-button boards without touch.
  if (deviceUsesSideButtonHintGutters(gpio)) {
    availableWidth -= 2 * metrics.sideButtonHintsWidth;
  }
  const int effectiveMargin = (pageWidth - availableWidth * metrics.keyboardTextFieldWidthPercent / 100) / 2;
  const int toggleGap = isPassword ? 4 : 0;
  const int toggleReserve = isPassword ? std::max(renderer.getTextWidth(UI_12_FONT_ID, "[abc]"),
                                                  renderer.getTextWidth(UI_12_FONT_ID, "[***]")) +
                                             toggleGap
                                       : 0;
  const int textAreaWidth = pageWidth - 2 * effectiveMargin - toggleReserve;
  const int maxLineWidth = textAreaWidth;
  const bool centerText = metrics.keyboardCenteredText;

  // The cursor spans a whole code point: a lone byte of it renders as a replacement glyph.
  // Masking is per byte, so displayText keeps text's length and the same span applies to both.
  const size_t cursorCharBytes = (cursorPos < text.length()) ? utf8Next(text, cursorPos) - cursorPos : 0;
  char cursorChar[8] = {};         // the character under the cursor
  char displayCursorChar[8] = {};  // same span of displayText, masked for passwords
  if (cursorCharBytes > 0) {
    const size_t n = std::min(cursorCharBytes, sizeof(cursorChar) - 1);
    memcpy(cursorChar, text.data() + cursorPos, n);
    memcpy(displayCursorChar, displayText.data() + cursorPos, n);
  }

  int cursorCharWidth = 6;
  if (cursorCharBytes > 0) {
    int w = renderer.getTextWidth(UI_12_FONT_ID, cursorChar);
    if (w > cursorCharWidth) cursorCharWidth = w;
  }

  int lineStartIdx = 0;
  int textWidth = 0;
  int cursorPixelX = effectiveMargin;
  int cursorLineY = inputStartY;
  bool cursorDrawn = false;

  while (true) {
    const int lineEndIdx = lineBreakEnd(displayText, lineStartIdx, maxLineWidth);
    const bool forcedBreak = lineEndIdx < static_cast<int>(displayText.length()) && displayText[lineEndIdx] == '\n';
    // Measure directly in displayText: avoid allocating a temporary string for
    // every visible line on every keystroke.
    textWidth = measureRange(displayText, lineStartIdx, lineEndIdx);
    {
      const bool isRtl = rangeIsRtl(displayText, lineStartIdx, lineEndIdx);
      const int lineStartX = centerText ? effectiveMargin + (maxLineWidth - textWidth) / 2 : effectiveMargin;
      const bool isLastLine = (lineEndIdx == static_cast<int>(displayText.length()));
      bool isCursorLine = false;
      if (!cursorDrawn && cursorPos >= lineStartIdx &&
          (isLastLine ? cursorPos <= lineEndIdx : cursorPos < lineEndIdx)) {
        // Normal typing keeps cursorMode off, so measure the existing buffer in
        // place instead of constructing beforeCursor on every key activation.
        // Password cursor mode retains its masked temporary because its visual
        // representation intentionally differs from displayText.
        std::string maskedBeforeCursor;
        int beforeWidth = 0;
        if (isPassword && !passwordVisible && cursorMode) {
          maskedBeforeCursor.assign(cursorPos - lineStartIdx, '*');
          beforeWidth = renderer.getTextAdvanceX(UI_12_FONT_ID, maskedBeforeCursor.c_str(), EpdFontFamily::REGULAR);
        } else {
          beforeWidth = measureRange(displayText, lineStartIdx, static_cast<int>(cursorPos));
        }
        int throughCursorWidth = beforeWidth;
        int kernOffset = 0;
        if (cursorCharBytes > 0) {
          std::string beforeAndCursor;
          if (isPassword && !passwordVisible && cursorMode) {
            beforeAndCursor = maskedBeforeCursor;
            beforeAndCursor += displayCursorChar;
            throughCursorWidth = renderer.getTextAdvanceX(UI_12_FONT_ID, beforeAndCursor.c_str(), EpdFontFamily::REGULAR);
          } else {
            throughCursorWidth = measureRange(displayText, lineStartIdx,
                                               static_cast<int>(cursorPos + cursorCharBytes));
          }
          int charAdvance = renderer.getTextAdvanceX(UI_12_FONT_ID, displayCursorChar, EpdFontFamily::REGULAR);
          kernOffset = throughCursorWidth - beforeWidth - charAdvance;
        }
        if (isRtl) {
          const int logicalWidth = cursorMode && cursorCharBytes > 0 ? throughCursorWidth : beforeWidth;
          cursorPixelX = lineStartX + textWidth - logicalWidth;
        } else {
          cursorPixelX = lineStartX + beforeWidth + kernOffset;
        }
        cursorLineY = inputStartY + inputHeight;
        cursorDrawn = true;
        isCursorLine = true;
      }

      if (isCursorLine && cursorMode && isPassword && !passwordVisible && !togglePos) {
        // Draw text in 3 parts to avoid block cursor overflowing onto next char.
        // displayText uses '*' for all chars; actual char may be wider than '*'.
        // Part 1: chars before cursor position
        const std::string part1 = displayText.substr(lineStartIdx, cursorPos - lineStartIdx);
        renderer.drawText(UI_12_FONT_ID, lineStartX, inputStartY + inputHeight, part1.c_str());
        // Part 2: skip cursor slot (block + actual char drawn later)
        // Part 3: chars after cursor position (skip char under cursor), starting at cursorPixelX + cursorCharWidth
        const int afterStart = static_cast<int>(cursorPos + cursorCharBytes);
        const int afterEnd = lineEndIdx;
        if (afterStart < afterEnd) {
          const std::string part3 = displayText.substr(afterStart, afterEnd - afterStart);
          renderer.drawText(UI_12_FONT_ID, cursorPixelX + cursorCharWidth, inputStartY + inputHeight, part3.c_str());
        }
      } else {
        // Draw the [lineStartIdx, lineEndIdx) slice without a substr allocation.
        const char saved = displayText[lineEndIdx];
        displayText[lineEndIdx] = '\0';
        renderer.drawText(UI_12_FONT_ID, lineStartX, inputStartY + inputHeight,
                          displayText.c_str() + lineStartIdx);
        displayText[lineEndIdx] = saved;
      }
      if (lineEndIdx == static_cast<int>(displayText.length())) {
        break;
      }

      inputHeight += lineHeight;
      lineStartIdx = forcedBreak ? lineEndIdx + 1 : lineEndIdx;
    }
  }

  const int fieldWidth = (inputHeight > 0) ? maxLineWidth : textWidth;
  const int lineMargin = effectiveMargin;
  GUI.drawTextField(renderer, Rect{0, inputStartY, pageWidth, inputHeight}, fieldWidth, cursorMode, lineMargin,
                    pageWidth - 2 * lineMargin);

  if (cursorMode && !togglePos && cursorPos <= displayText.length()) {
    static constexpr int blockPadding = 1;
    renderer.fillRect(cursorPixelX - blockPadding, cursorLineY, cursorCharWidth + blockPadding * 2, lineHeight, true);
    if (cursorCharBytes > 0) {
      renderer.drawText(UI_12_FONT_ID, cursorPixelX, cursorLineY, cursorChar, false);
    }
  } else if (cursorPos <= displayText.length()) {
    static constexpr int serifW = 3;
    const int cX = cursorPixelX;
    const int cY = cursorLineY;
    const int cBottom = cursorLineY + lineHeight - 1;
    renderer.fillRect(cX, cY, 2, lineHeight, true);
    renderer.drawLine(cX - serifW, cY, cX - 1, cY, 2, true);
    renderer.drawLine(cX + 1, cY, cX + serifW, cY, 2, true);
    renderer.drawLine(cX - serifW, cBottom, cX - 1, cBottom, 2, true);
    renderer.drawLine(cX + 1, cBottom, cX + serifW, cBottom, 2, true);
  }

  if (isPassword) {
    const char* toggleLabel = passwordVisible ? "[***]" : "[abc]";
    const int toggleWidth = renderer.getTextWidth(UI_12_FONT_ID, toggleLabel);
    const int toggleX = pageWidth - effectiveMargin - toggleWidth;
    const int toggleY = inputStartY + inputHeight;
    const bool toggleSelected = cursorMode && togglePos;

    if (toggleSelected) {
      renderer.fillRect(toggleX - 2, toggleY, toggleWidth + 5, lineHeight + 3, true);
      renderer.drawText(UI_12_FONT_ID, toggleX, toggleY, toggleLabel, false);
    } else {
      renderer.drawText(UI_12_FONT_ID, toggleX, toggleY, toggleLabel, true);
    }
  }

  if (hintVisible && !text.empty()) {
    const int hintLh = renderer.getLineHeight(SMALL_FONT_ID);
    const int underlineY = inputStartY + inputHeight + lineHeight + metrics.verticalSpacing;
    const int hintY = underlineY + 4;
    if (cursorMode) {
      int hintLineY = hintY;
      if (inputType == InputType::Password && togglePos) {
        renderer.drawCenteredText(
            SMALL_FONT_ID, hintLineY,
            passwordVisible ? tr(STR_KB_HINT_TOGGLE_HIDE_PASSWORD) : tr(STR_KB_HINT_TOGGLE_SHOW_PASSWORD), true);
        hintLineY += hintLh;
        renderer.drawCenteredText(SMALL_FONT_ID, hintLineY, tr(STR_KB_HINT_RETURN_CURSOR), true);
      } else {
        renderer.drawCenteredText(SMALL_FONT_ID, hintLineY, tr(STR_KB_HINT_MOVE_CURSOR), true);
        hintLineY += hintLh;
        if (inputType == InputType::Password) {
          const char* passTip = passwordVisible ? tr(STR_KB_HINT_HIDE_PASSWORD) : tr(STR_KB_HINT_SHOW_PASSWORD);
          renderer.drawCenteredText(SMALL_FONT_ID, hintLineY, passTip, true);
        }
      }
    } else {
      renderer.drawCenteredText(SMALL_FONT_ID, hintY, tr(STR_KB_HINT_EDIT_ENTRY), true);
    }
  }

  const fui::Rect kbRect = keyboardRect();

  if (predictiveEnabled() && !cursorMode && !symbols && !urlPanel) {
    const auto options = predictiveText.suggestions(text, cursorPos);
    if (!options[0].empty() || !options[1].empty() || !options[2].empty()) {
      const fui::Rect bar = predictiveBarRect();
      renderer.fillRect(bar.x, bar.y, bar.width, bar.height, false);
      renderer.drawLine(bar.x, bar.y, bar.x + bar.width, bar.y, 1, true);
      renderer.drawLine(bar.x, bar.y + bar.height - 1, bar.x + bar.width, bar.y + bar.height - 1, 1, true);
      for (int i = 0; i < 3; ++i) {
        const int cellX = bar.x + bar.width * i / 3;
        const int nextX = bar.x + bar.width * (i + 1) / 3;
        if (i > 0) renderer.drawLine(cellX, bar.y + 5, cellX, bar.y + bar.height - 6, 1, true);
        if (options[i].empty()) continue;
        const int cellWidth = std::max(1, nextX - cellX);
        const std::string label = renderer.truncatedText(UI_10_FONT_ID, options[i].c_str(), std::max(1, cellWidth - 10));
        const int textWidth = renderer.getTextWidth(UI_10_FONT_ID, label.c_str());
        const int textHeight = renderer.getLineHeight(UI_10_FONT_ID);
        renderer.drawText(UI_10_FONT_ID, cellX + std::max(3, (cellWidth - textWidth) / 2),
                          bar.y + std::max(1, (bar.height - textHeight) / 2), label.c_str(), true);
      }
    }
  }

  const int tipsLh = renderer.getLineHeight(SMALL_FONT_ID);
  const int underlineBottom = inputStartY + inputHeight + lineHeight + metrics.verticalSpacing + 4;
  auto drawTip = [&](const char* tip, int y) { renderer.drawCenteredText(SMALL_FONT_ID, y, tip, true); };

  int tipCount = 0;
  if (cursorMode) {
    tipCount = 1;
  } else if (urlPanel) {
    tipCount = 1 + (!text.empty() ? 1 : 0);
  } else if (symbols) {
    tipCount = !text.empty() ? 1 : 0;
  } else {
    tipCount = 1 + (inputType == InputType::Url ? 1 : 0) + (!text.empty() ? 1 : 0);
  }

  if (tipCount > 0 && !(predictiveEnabled() && !cursorMode)) {
    int y = (underlineBottom + kbRect.y) / 2 - (tipCount + 1) * tipsLh / 2;
    drawTip(tr(STR_KB_TIPS), y);
    y += tipsLh;
    if (cursorMode) {
      drawTip(tr(STR_KB_HINT_RETURN_KEYBOARD), y);
    } else if (urlPanel) {
      drawTip(tr(STR_KB_HINT_EXIT_URL_MODE), y);
      y += tipsLh;
      if (!text.empty()) {
        drawTip(tr(STR_KB_HINT_CLEAR_TEXT), y);
      }
    } else if (symbols) {
      if (!text.empty()) {
        drawTip(tr(STR_KB_HINT_CLEAR_TEXT), y);
      }
    } else {
      const char* altCharTip;
      if (inputType == InputType::Url) {
        altCharTip = tr(STR_KB_HINT_SECONDARY_CHAR);
      } else if (shifted) {
        altCharTip = tr(STR_KB_HINT_LOWER_SECONDARY);
      } else {
        altCharTip = tr(STR_KB_HINT_UPPER_SECONDARY);
      }
      drawTip(altCharTip, y);
      y += tipsLh;
      if (inputType == InputType::Url) {
        drawTip(tr(STR_KB_HINT_URL_SNIPPETS), y);
        y += tipsLh;
      }
      if (!text.empty()) {
        drawTip(tr(STR_KB_HINT_CLEAR_TEXT), y);
      }
    }
  }

  // The FreeInkUI keyboard draws the keys and registers their hit rects into
  // `interactions`; loop() routes touch snapshots against the last published
  // table while this render builds the next generation.
  fui::GfxRendererTarget target(renderer);
  target.setFont(fui::GfxRendererTarget::FONT_SMALL, SMALL_FONT_ID);
  target.setFont(fui::GfxRendererTarget::FONT_BODY, UI_12_FONT_ID);
  const fui::DeviceContext device = target.deviceContext();
  const fui::InputSnapshot noInput{};
  interactions.beginPublishCycle();
  fui::Frame<56> frame(target, device, noInput, interactions);

  fui::KeyboardProps props;
  const fui::KeyboardLayout& layout = currentLayout();
  props.layout = &layout;
  props.keyAction = ACTION_KEY;  // one action id; loop() dispatches on key value
  props.okLabel = inputType == InputType::Multiline ? "↵" : tr(STR_OK_BUTTON);
  props.shiftLabel = tr(STR_KEY_SHIFT);
  // Match the label to the layer the mode key leads back from: the symbols
  // layer and the URL snippet panel both label it "abc" in the static tables.
  props.modeLabel =
      (symbols || (inputType == InputType::Url && urlPanel)) ? tr(STR_KEY_MODE_ABC) : tr(STR_KEY_MODE_SYMBOLS);
  props.inputMask = static_cast<uint16_t>(fui::InputTouch | fui::InputLongPress);
  props.selectedIndex = cursorMode ? -1 : static_cast<int16_t>(selectedLogicalIndex());
  props.labelText.font = fui::GfxRendererTarget::FONT_BODY;
  props.altText.font = fui::GfxRendererTarget::FONT_SMALL;
  props.gap = static_cast<int16_t>(metrics.keyboardKeySpacing);
  props.padding = fui::Insets{0, 0, 0, 0};
  // Fingers land low on the bottom row (occlusion) and there is no key below
  // to catch the miss — extend its hit band down to the button hints bar.
  const int hintsTop = renderer.getScreenHeight() - metrics.buttonHintsHeight;
  props.bottomHitOverflow = static_cast<int16_t>(std::max(0, hintsTop - (kbRect.y + kbRect.height)));
  fui::keyboard(frame, kbRect, props);
  interactions.publish();
  interactionsReady.store(true, std::memory_order_release);

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_LEFT),
                                            tr(STR_DIR_RIGHT));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);

  GUI.drawSideButtonHints(renderer, ">", "<");

  refreshNotesPanel();
}

void NotesFastKeyboardActivity::onComplete(std::string text) {
  if (predictiveEnabled()) {
    predictiveText.learnCurrentWord(text, cursorPos);
    predictiveText.save();
  }
  setResult(KeyboardResult{std::move(text)});
  finish();
}

void NotesFastKeyboardActivity::onCancel() {
  ActivityResult result;
  result.isCancelled = true;
  setResult(std::move(result));
  finish();
}