#pragma once
#include <FreeInkUIGfxRenderer.h>
#include <GfxRenderer.h>

#include <atomic>
#include <cstdint>
#include <string>
#include <vector>
#include <utility>

#include "activities/Activity.h"
#include "SdCardFontSystem.h"
#include "activities/util/KeyboardEntryActivity.h"
#include "util/ButtonNavigator.h"
#include "activities/util/PredictiveText.h"

// Text entry on the FreeInkUI keyboard component: the SDK layout tables and
// keyboard() do the key rendering and hit-rect registration, InteractionBuffer
// routes taps/long-presses, and this activity owns the text field, cursor
// editing, and the URL snippet layouts.
class NotesFastKeyboardActivity : public Activity {
 public:
  explicit NotesFastKeyboardActivity(GfxRenderer& renderer, MappedInputManager& mappedInput,
                                 std::string title = "Enter Text", std::string initialText = "",
                                 const size_t maxLength = 0, InputType inputType = InputType::Text,
                                 const size_t minLength = 0)
      : Activity("NotesFastKeyboard", renderer, mappedInput),
        title(title),
        text(std::move(initialText)),
        maxLength(maxLength),
        inputType(inputType),
        minLength(minLength),
        viewerTitle(std::move(title)),
        viewerInputType(inputType) {}

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

  // Exposed for specialized editors that must persist in-progress text when
  // the activity is torn down by deep sleep rather than completed normally.
  const std::string& currentText() const { return text; }

 protected:
  // Optional right-side header action for specialized editors. The default
  // implementation is inert so existing keyboard users are unchanged.
  virtual bool handleHeaderActionTap(int, int) { return false; }
  virtual int headerActionReserveWidth() const { return 0; }
  virtual bool headerActionLocked() const { return false; }
  void drawHeaderAction();
  Rect lockArtworkRectOnTitleBaseline(Rect rect) const;
  virtual void drawNotesHeaderAction() {}

 private:
  std::string title;
  std::string text;
  size_t maxLength;
  InputType inputType;
  size_t minLength;
  bool passwordVisible = false;
  PredictiveText predictiveText;

  ButtonNavigator buttonNavigator;

  // Keyboard layers. The letter/symbol layers come from the SDK's builtin
  // layouts (with the always-visible number row); the URL layers are
  // app-defined tables in the .cpp.
  freeink::ui::KeyboardLayoutId layoutId = freeink::ui::KeyboardLayoutId::QwertyEn;
  bool showLangKey = false;
  bool shifted = false;
  bool symbols = false;
  bool urlPanel = false;  // URL snippet panel replaces the letter layer

  // Key hit rects registered by the keyboard component during render();
  // loop() routes taps/long-presses against them. Cyrillic's wider rows register
  // 48 keys, so 56 retains headroom for the double-buffered interaction table.
  freeink::ui::InteractionBuffer<56> interactions;

  // GPIO selection over the current layout grid (row/col in layout terms;
  // the bottom action row is just the last row).
  int selRow = 0;
  int selCol = 0;

  bool confirmHeld = false;
  bool confirmLongHandled = false;

  bool cursorMode = false;
  bool togglePos = false;
  size_t cursorPos = 0;  // byte offset into text (always on a code point boundary)
  bool upHeld = false;
  bool upLongHandled = false;
  bool downHeld = false;
  bool downLongHandled = false;
  bool rightHeld = false;
  bool rightLongHandled = false;
  size_t savedCursorPos = 0;
  size_t rightStartCursorPos = 0;

  // Tap/hold routing (threshold long-press, release swallow, slide re-arm)
  // lives in the SDK; loop() feeds it the level-triggered touch state.
  freeink::ui::TouchHoldRouter touchRouter;

  // loop() runs on the main task while render() rebuilds the interaction
  // table on the render task. This is only the first-published-table gate;
  // later renders publish into the SDK's double buffer without clearing it,
  // so the previous complete table remains routable during a rebuild. Atomic
  // release/acquire ordering pairs the first publish with the main task.
  std::atomic<bool> interactionsReady{false};

  int delPressCount = 0;
  bool hintVisible = false;
  unsigned long hintShowTime = 0;

  enum class InputFieldTouchTarget { None, Cursor, PasswordToggle };

  void onComplete(std::string text);
  void onCancel();
  InputFieldTouchTarget inputFieldTouchTargetFromPoint(int x, int y, size_t& position) const;
  std::string displayTextForCurrentState() const;
  // Advance of s[start, end) measured in place by temporarily null-terminating
  // at `end` — avoids a substr temporary per measurement.
  int measureRange(std::string& s, int start, int end) const;
  bool rangeIsRtl(std::string& s, int start, int end) const;
  // Largest line end in (start, s.length()] whose advance fits maxWidth.
  // Binary search over the monotonic prefix advance; always advances at least
  // one byte so an oversized glyph cannot stall the wrap loop.
  int lineBreakEnd(std::string& s, int start, int maxWidth) const;

  const freeink::ui::KeyboardLayout& currentLayout() const;
  const freeink::ui::KeyboardKey* selectedKey() const;
  int selectedLogicalIndex() const;
  void clampSelection();
  void moveSelectionRow(int delta);
  void moveSelectionCol(int delta);
  bool syncSelectionToValue(int16_t value);
  // Handles one key activation (by stable key id). Returns true when the
  // screen needs a repaint; OK/cancel finish the activity instead.
  bool activateValue(int16_t value, bool longPress);
  bool clearAllOrAltOnSelected();

  void insertUtf8(const char* out);
  bool backspaceUtf8();
  static size_t utf8Prev(const std::string& s, size_t pos);
  static size_t utf8Next(const std::string& s, size_t pos);
  bool predictiveEnabled() const;
  freeink::ui::Rect predictiveBarRect() const;

  freeink::ui::Rect keyboardRect() const;

 protected:
  bool viewerEnabled() const { return viewerInputType == InputType::Multiline && headerActionReserveWidth() > 0; }

  // NotesViewerKeyboardBase switches between viewer/editor and Notes can open
  // child dialogs while the editor remains alive. In both cases the physical
  // panel no longer matches this editor's shadow, so the next render must be
  // a clean whole-screen refresh.
  void invalidateNotesPanelBaseline() { notesWindowShadowValid = false; }

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

  static bool viewerPointIn(const Rect& rect, int x, int y);
  Rect viewerHeaderActionRect() const;
  Rect pencilRect() const;
  static size_t previousUtf8Boundary(const std::string& text, size_t pos);
  static size_t nextUtf8Boundary(const std::string& text, size_t pos);
  void appendWrappedLine(std::string remaining);
  void rebuildViewerLayout();
  void changeViewerPage(int delta);
  void drawOpenLockLight(const Rect& rect);
  void drawPencil(const Rect& rect);
  void loopViewer();
  void renderViewer();

  uint8_t* notesWindowShadow = nullptr;
  bool notesWindowShadowValid = false;
  uint8_t notesFastRefreshCount = 0;

  void releaseNotesWindowShadow();
  void refreshNotesPanel();

  static constexpr uint8_t NOTES_FAST_REFRESHES_BEFORE_CLEAN = 6;
  static constexpr uint16_t LONG_PRESS_MS = 500;
  static constexpr uint16_t DEL_LONG_PRESS_MS = 1500;
  static constexpr uint16_t TOUCH_LONG_PRESS_MS = 350;
  static constexpr uint16_t TOUCH_DEL_LONG_PRESS_MS = 900;

  // App-specific key id: toggles the URL snippet panel (URL fields only).
  static constexpr int16_t URL_PANEL_KEY = -3;
};
