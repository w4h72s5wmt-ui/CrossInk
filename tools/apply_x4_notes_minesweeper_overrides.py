from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_pos] + replacement + text[end_pos:]


core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()

core = replace_once(
    core,
    """  bool handleHeaderActionTap(const int x, const int y) override {
    if (!pointInRect(lockButtonRect(), x, y)) return false;
    if (!noteLockedByPath(path)) beginLock();
    return true;
  }
""",
    """  bool handleHeaderActionTap(const int x, const int y) override {
    if (!pointInRect(lockButtonRect(), x, y)) return false;
    if (noteLockedByPath(path)) {
      beginUnlock();
    } else {
      beginLock();
    }
    return true;
  }
""",
    "Notes lock toggle",
)

core = replace_once(
    core,
    """  Rect lockButtonRect() const {
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    return Rect{renderer.getScreenWidth() - kLockButtonWidth, header.y, kLockButtonWidth, header.height};
  }
""",
    """  Rect lockButtonRect() const {
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const auto backLayout = TouchHeaderBackButton::layout(header);
    const int controlOffset = std::min(
        TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
        std::max(0, header.y + header.height -
                        (backLayout.iconRect.y +
                         (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
    return Rect{renderer.getScreenWidth() - kLockButtonWidth, header.y + controlOffset, kLockButtonWidth,
                header.height};
  }
""",
    "Notes header lock alignment",
)

begin_lock_start = "  void beginLock() {\n"
begin_lock_end = "\n  }\n};\n}  // namespace"
new_lock_methods = """  bool hasSessionPattern() const {
    return vaultPattern.size() == kPatternLength || vaultPattern.size() == kLegacyPatternLength;
  }

  bool lockWithPattern(const std::string& pattern) {
    if (!saveEncryptedNoteFile(path, currentText(), pattern)) {
      LOG_ERR("NOTES", "Failed to encrypt note: %s", path.c_str());
      requestUpdate();
      return false;
    }
    if (!createLockMarker(path)) {
      saveNoteFile(path, currentText());
      LOG_ERR("NOTES", "Failed to lock note: %s", path.c_str());
      requestUpdate();
      return false;
    }
    vaultPattern = pattern;
    requestUpdate(true);
    return true;
  }

  void beginUnlock() {
    if (!saveNoteFile(path, currentText())) {
      LOG_ERR("NOTES", "Failed to decrypt note: %s", path.c_str());
      requestUpdate();
      return;
    }
    removeLockMarker(path);
    requestUpdate(true);
  }

  void beginLock() {
    if (hasSessionPattern()) {
      lockWithPattern(vaultPattern);
      return;
    }

    uint64_t expectedFingerprint = 0;
    const bool hasVault = readVaultFingerprint(expectedFingerprint);
    startActivityForResult(
        std::make_unique<VaultPatternActivity>(renderer, mappedInput, hasVault, expectedFingerprint),
        [this, hasVault](const ActivityResult& result) {
          if (result.isCancelled) {
            requestUpdate();
            return;
          }
          const auto* pattern = std::get_if<KeyboardResult>(&result.data);
          const bool validPattern =
              pattern && (pattern->text.size() == kPatternLength ||
                          (hasVault && pattern->text.size() == kLegacyPatternLength));
          if (!validPattern) {
            requestUpdate();
            return;
          }
          if (!hasVault && !writeVaultFingerprint(patternFingerprint(pattern->text))) {
            LOG_ERR("NOTES", "Failed to save Notes vault fingerprint");
            requestUpdate();
            return;
          }
          lockWithPattern(pattern->text);
        });"""
core = replace_section(core, begin_lock_start, begin_lock_end, new_lock_methods, "Notes session-aware lock methods")

core = replace_once(
    core,
    """      std::make_unique<NotesKeyboardActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes, path,
                                              noteLockedByPath(path) ? vaultPattern : std::string{}),
""",
    """      std::make_unique<NotesKeyboardActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes, path,
                                              vaultMode ? vaultPattern : std::string{}),
""",
    "Notes session pattern propagation",
)
core_path.write_text(core)

viewer_path = Path("src/activities/home/NotesViewerKeyboardBase.h")
viewer = viewer_path.read_text()
viewer = replace_once(
    viewer,
    """  Rect headerActionRect() const {
    const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
    const int width = std::max(0, headerActionReserveWidth());
    return Rect{renderer.getScreenWidth() - width, header.y, width, header.height};
  }
""",
    """  Rect headerActionRect() const {
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
""",
    "Notes viewer lock alignment",
)
viewer_path.write_text(viewer)

mine_h_path = Path("src/activities/home/MinesweeperActivity.h")
mine_h = mine_h_path.read_text()
mine_h = replace_once(
    mine_h,
    """  int selectedIndex_ = 0;
  int gridSizeIndex_ = 0;
  int visibleRows_ = 1;
""",
    """  int selectedIndex_ = 0;
  int gridSizeIndex_ = 0;
  int savedGridSizeIndex_ = 0;
  std::array<char, 48> continueLabel_{};
  int visibleRows_ = 1;
""",
    "Minesweeper saved grid state",
)
mine_h_path.write_text(mine_h)

mine_path = Path("src/activities/home/MinesweeperActivity.cpp")
mine = mine_path.read_text()
mine = replace_once(
    mine,
    """  hasSavedGame_ = loadSavedGame();
  selectedIndex_ = gridSizeIndex_;
""",
    """  hasSavedGame_ = loadSavedGame();
  if (hasSavedGame_) savedGridSizeIndex_ = gridSizeIndex_;
  selectedIndex_ = gridSizeIndex_;
""",
    "Minesweeper saved grid initialization",
)
mine = replace_once(
    mine,
    """void MinesweeperActivity::continueGame() {
  assistedCounterChoice = assistedCounterActive;
  enterGrid();
}
""",
    """void MinesweeperActivity::continueGame() {
  gridSizeIndex_ = std::clamp(savedGridSizeIndex_, 0, kGridOptionCount - 1);
  assistedCounterChoice = assistedCounterActive;
  enterGrid();
}
""",
    "Minesweeper continue saved grid restoration",
)
mine = replace_once(
    mine,
    """  hasSavedGame_ = true;
  return true;
}

bool MinesweeperActivity::loadSavedGame() {
""",
    """  hasSavedGame_ = true;
  savedGridSizeIndex_ = gridSizeIndex_;
  return true;
}

bool MinesweeperActivity::loadSavedGame() {
""",
    "Minesweeper remember saved grid after save",
)
mine = replace_once(
    mine,
    """  gridSizeIndex_ = grid;
  const int cellCount = totalCells();
""",
    """  gridSizeIndex_ = grid;
  savedGridSizeIndex_ = grid;
  const int cellCount = totalCells();
""",
    "Minesweeper remember loaded grid",
)
mine = replace_once(
    mine,
    """  items[5].label = "Continuer";
  items[5].value = hasSavedGame_ ? "Partie sauvegardee" : "Aucune partie";
  items[5].actionValue = 5;
""",
    """  if (hasSavedGame_) {
    const int savedGrid = std::clamp(savedGridSizeIndex_, 0, kGridOptionCount - 1);
    std::snprintf(continueLabel_.data(), continueLabel_.size(), "Continuer la partie %s", GRID_DIMS[savedGrid]);
    items[5].label = continueLabel_.data();
    items[5].value = nullptr;
  } else {
    items[5].label = "Continuer";
    items[5].value = "Aucune partie";
  }
  items[5].actionValue = 5;
""",
    "Minesweeper continue label",
)
mine_path.write_text(mine)

print("Applied Notes lock/session alignment and Minesweeper continue-label refinements.")
