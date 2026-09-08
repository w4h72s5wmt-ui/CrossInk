from pathlib import Path

path = Path("src/activities/home/NotesViewerKeyboardBase.h")
text = path.read_text()
old = '''  void drawHeaderAction() override {
    if (currentNoteLooksLocked()) {
      drawNotesHeaderAction();
    } else {
      drawOpenLockLight(headerActionRect());
    }
  }
'''
new = '''  void drawHeaderAction() override {
    // Generic Notes text fields (title/search) reserve no header action.
    // Never draw the lock there; it belongs only to the actual note content editor/viewer.
    if (headerActionReserveWidth() <= 0) return;
    if (currentNoteLooksLocked()) {
      drawNotesHeaderAction();
    } else {
      drawOpenLockLight(headerActionRect());
    }
  }
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Notes title lock visibility: expected 1 match, found {count}")
path.write_text(text.replace(old, new, 1))
print("Applied Notes title/search lock visibility fix.")
