from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# The lock action belongs only to active note-content editing. Title/search
# fields and the read-only viewer must neither display nor handle a padlock.
viewer_path = Path("src/activities/home/NotesViewerKeyboardBase.h")
viewer = viewer_path.read_text()
viewer = replace_once(
    viewer,
    '''#include "components/TouchHeaderBackButton.h"
#include "fontIds.h"
''',
    '''#include "components/TouchHeaderBackButton.h"
#include "components/UIScale.h"
#include "fontIds.h"
''',
    "Notes baseline alignment UI scale include",
)
viewer = replace_once(
    viewer,
    '''      if (pointIn(headerActionRect(), tx, ty)) {
        handleHeaderActionTap(tx, ty);
        return;
      }
''',
    "",
    "Notes disable lock tap in read-only viewer",
)
viewer = replace_once(
    viewer,
    '''    TouchHeaderBackButton::draw(renderer, header, viewerTitle.c_str(), false, headerActionReserveWidth());
    drawHeaderAction();
''',
    '''    // Read-only mode deliberately has no lock affordance. The action is
    // exposed only after the pencil opens the active keyboard/editor.
    TouchHeaderBackButton::draw(renderer, header, viewerTitle.c_str(), false, 0);
''',
    "Notes hide lock in read-only viewer",
)
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
    // This method is therefore reached only by the active note-content editor.
    if (headerActionReserveWidth() <= 0) return;
    if (headerActionLocked()) {
      drawNotesHeaderAction();
    } else {
      drawOpenLockLight(lockArtworkRectOnTitleBaseline(headerActionRect()));
    }
  }

  Rect lockArtworkRectOnTitleBaseline(Rect rect) const {
    // Use the exact same title-baseline calculation as the touch header. The
    // open and closed padlocks both have a 16px body, so placing the body's
    // bottom edge on the title baseline gives them identical vertical alignment
    // without moving the much larger touch target.
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const auto headerLayout = TouchHeaderBackButton::layout(header);
    const int iconBottom = headerLayout.iconRect.y +
                           (headerLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2;
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
''',
    "Notes editor-only lock action and exact title-baseline alignment",
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
# or sanitised filenames), and align the lock artwork to the real title baseline.
core = replace_once(
    core,
    '''  int headerActionReserveWidth() const override { return kLockButtonWidth; }

  void drawHeaderAction() override { drawLockIcon(renderer, lockButtonRect(), true); }
''',
    '''  int headerActionReserveWidth() const override { return kLockButtonWidth; }

  bool headerActionLocked() const override { return noteLockedByPath(path); }

  void drawHeaderAction() override {
    drawLockIcon(renderer, lockArtworkRectOnTitleBaseline(lockButtonRect()), true);
  }
''',
    "Notes exact-path lock state and exact title-baseline alignment",
)

# Use the note-title text baseline as the single vertical reference for all row
# artwork. Each icon has different visual extents inside an unchanged touch box,
# so geometric centering of those boxes cannot align the actual drawings.
# Align the visible bottom of pencil, lock body and trash can to the text baseline.
core = replace_once(
    core,
    '''      const int textH = renderer.getLineHeight(UI_12_FONT_ID);
      renderer.drawText(UI_12_FONT_ID, rowRect.x + kRowSidePadding, rowRect.y + (rowRect.height - textH) / 2,
                        title.c_str(), true);
      drawRenameIcon(renderer, renameRect, true);
      if (vaultMode && rowLocked) drawLockIcon(renderer, lockRect, true);
      drawTrashIcon(renderer, deleteRect, true);
''',
    '''      const int textH = renderer.getLineHeight(UI_12_FONT_ID);
      const int textY = rowRect.y + (rowRect.height - textH) / 2;
      const int rowBaselineY = textY + renderer.getFontAscenderSize(UI_12_FONT_ID);
      renderer.drawText(UI_12_FONT_ID, rowRect.x + kRowSidePadding, textY, title.c_str(), true);

      auto artworkOnBaseline = [rowBaselineY](Rect rect, const int visualBottomFromCenter) {
        const int currentVisualBottomY = rect.y + rect.height / 2 + visualBottomFromCenter;
        rect.y += rowBaselineY - currentVisualBottomY;
        return rect;
      };
      // Real visible bottoms relative to each action rectangle's center:
      // pencil +11px, lock body +15px, trash can +10px.
      drawRenameIcon(renderer, artworkOnBaseline(renameRect, 11), true);
      if (vaultMode && rowLocked) drawLockIcon(renderer, artworkOnBaseline(lockRect, 15), true);
      drawTrashIcon(renderer, artworkOnBaseline(deleteRect, 10), true);
''',
    "Notes list text/action baseline alignment",
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

    if (Storage.exists(backupPath.c_str())) Storage.remove(backupPath.c_str());
    requestUpdate(true);
  }
''',
    "Notes transactional unlock",
)

if "iconRect.y += 2" in viewer or "iconRect.y += 2" in core:
    raise RuntimeError("Notes lock still uses a hard-coded vertical pixel offset")
if "lockArtworkRectOnTitleBaseline" not in viewer or "lockArtworkRectOnTitleBaseline(lockButtonRect())" not in core:
    raise RuntimeError("Notes lock exact title-baseline alignment is missing")
if "const int rowBaselineY = textY + renderer.getFontAscenderSize(UI_12_FONT_ID);" not in core:
    raise RuntimeError("Notes list action/text baseline alignment is missing")

core_path.write_text(core)
print("Applied Notes header and list baseline alignment, editor-only lock action, exact-path state, and reliable unlock fixes.")
