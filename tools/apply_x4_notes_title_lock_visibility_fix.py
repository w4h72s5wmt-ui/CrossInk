from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Notes title/search fields must stay visually clean. Only the actual note
# content viewer/editor reserves and draws the lock action.
viewer_path = Path("src/activities/home/NotesViewerKeyboardBase.h")
viewer = viewer_path.read_text()
viewer = replace_once(
    viewer,
    '''  void drawHeaderAction() override {
    if (currentNoteLooksLocked()) {
      drawNotesHeaderAction();
    } else {
      drawOpenLockLight(headerActionRect());
    }
  }
''',
    '''  virtual bool headerActionLocked() const { return currentNoteLooksLocked(); }

  void drawHeaderAction() override {
    // Generic Notes text fields (title/search) reserve no header action.
    // Never draw the lock there; it belongs only to the actual note content editor/viewer.
    if (headerActionReserveWidth() <= 0) return;
    if (headerActionLocked()) {
      drawNotesHeaderAction();
    } else {
      Rect iconRect = headerActionRect();
      // The padlock artwork is visually top-heavy; nudge only the drawing,
      // not its touch target, so it shares the title's perceived baseline.
      iconRect.y += 6;
      drawOpenLockLight(iconRect);
    }
  }
''',
    "Notes title/search lock suppression and exact lock-state hook",
)
viewer_path.write_text(viewer)


core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()

# Make marker removal observable. Existing callers may ignore the return value;
# the editor uses it to keep plaintext/encrypted state consistent.
core = replace_once(
    core,
    'void removeLockMarker(const std::string& notePath) { Storage.remove(lockMarkerPath(notePath).c_str()); }\n',
    '''bool removeLockMarker(const std::string& notePath) {
  const std::string marker = lockMarkerPath(notePath);
  return !Storage.exists(marker.c_str()) || Storage.remove(marker.c_str());
}
''',
    "Notes checked lock-marker removal",
)

# The content editor knows the exact on-disk path. Use that instead of deriving
# lock state from the displayed title (which is ambiguous for duplicate titles
# or sanitised filenames), and align only the visual icon 6 px lower.
core = replace_once(
    core,
    '''  int headerActionReserveWidth() const override { return kLockButtonWidth; }

  void drawHeaderAction() override { drawLockIcon(renderer, lockButtonRect(), true); }
''',
    '''  int headerActionReserveWidth() const override { return kLockButtonWidth; }

  bool headerActionLocked() const override { return noteLockedByPath(path); }

  void drawHeaderAction() override {
    Rect iconRect = lockButtonRect();
    iconRect.y += 6;
    drawLockIcon(renderer, iconRect, true);
  }
''',
    "Notes exact-path lock state and header icon alignment",
)

# Unlock through a temporary plaintext file and keep the encrypted original as
# a backup until the marker is removed. This prevents a failed SD operation from
# leaving a plaintext note behind a stale .lock marker (or vice versa).
core = replace_once(
    core,
    '''  void beginUnlock() {
    if (!saveNoteFile(path, currentText())) {
      LOG_ERR("NOTES", "Failed to decrypt note: %s", path.c_str());
      requestUpdate();
      return;
    }
    removeLockMarker(path);
    requestUpdate(true);
  }
''',
    '''  void beginUnlock() {
    const std::string tempPath = path + ".unlock.tmp";
    const std::string backupPath = path + ".unlock.bak";
    if (Storage.exists(tempPath.c_str())) Storage.remove(tempPath.c_str());
    if (Storage.exists(backupPath.c_str())) Storage.remove(backupPath.c_str());

    const std::string& plain = currentText();
    if (!writeRawNoteFile(tempPath, reinterpret_cast<const uint8_t*>(plain.data()), plain.size())) {
      LOG_ERR("NOTES", "Failed to stage unlocked note: %s", path.c_str());
      requestUpdate();
      return;
    }
    if (!Storage.rename(path.c_str(), backupPath.c_str())) {
      Storage.remove(tempPath.c_str());
      LOG_ERR("NOTES", "Failed to preserve encrypted note before unlock: %s", path.c_str());
      requestUpdate();
      return;
    }
    if (!Storage.rename(tempPath.c_str(), path.c_str())) {
      Storage.rename(backupPath.c_str(), path.c_str());
      if (Storage.exists(tempPath.c_str())) Storage.remove(tempPath.c_str());
      LOG_ERR("NOTES", "Failed to install plaintext note during unlock: %s", path.c_str());
      requestUpdate();
      return;
    }

    if (!removeLockMarker(path)) {
      // The note is still logically locked. Restore encrypted content before
      // returning so a later open can never interpret plaintext as ciphertext.
      if (!saveEncryptedNoteFile(path, plain, vaultPattern)) {
        Storage.remove(path.c_str());
        Storage.rename(backupPath.c_str(), path.c_str());
      }
      if (Storage.exists(backupPath.c_str())) Storage.remove(backupPath.c_str());
      LOG_ERR("NOTES", "Failed to remove lock marker while unlocking: %s", path.c_str());
      requestUpdate();
      return;
    }

    if (Storage.exists(backupPath.c_str()) && !Storage.remove(backupPath.c_str())) {
      LOG_WARN("NOTES", "Unlocked note kept a stale backup: %s", backupPath.c_str());
    }
    requestUpdate(true);
  }
''',
    "Notes transactional unlock",
)

core_path.write_text(core)
print("Applied Notes title visibility, lock alignment, exact-path state, and reliable unlock fixes.")
