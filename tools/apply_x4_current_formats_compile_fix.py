from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Existing MSW5 loader mutability compile fix.
path = Path("src/activities/home/MinesweeperActivity.cpp")
text = path.read_text()
old = "  const bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n"
new = "  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n"
text = replace_once(text, old, new, "Minesweeper MSW5 loader mutability fix")
path.write_text(text)


# ---------------------------------------------------------------------------
# Final Notes optimizations. This script runs after all Notes overlays so these
# edits target the exact code that is compiled, without touching generic
# CrossInk Activity/renderer/storage infrastructure.
# ---------------------------------------------------------------------------
notes_h_path = Path("src/activities/home/NotesActivity.h")
notes_h = notes_h_path.read_text()
notes_h = replace_once(
    notes_h,
    "  std::vector<std::string> notes;\n  std::vector<size_t> filteredNotes;\n",
    "  std::vector<std::string> notes;\n  std::vector<uint8_t> noteLockedStates;\n  std::vector<size_t> filteredNotes;\n",
    "Notes cached lock metadata member",
)
notes_h_path.write_text(notes_h)

core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()

core = replace_once(
    core,
    """std::string lowerAscii(std::string value) {
  for (char& c : value) {
    const unsigned char uc = static_cast<unsigned char>(c);
    if (uc < 0x80) c = static_cast<char>(std::tolower(uc));
  }
  return value;
}

bool asciiTitleContains""",
    """std::string lowerAscii(std::string value) {
  for (char& c : value) {
    const unsigned char uc = static_cast<unsigned char>(c);
    if (uc < 0x80) c = static_cast<char>(std::tolower(uc));
  }
  return value;
}

std::array<uint8_t, 32> noteTextDigest(const std::string& text) {
  std::array<uint8_t, 32> digest{};
  if (mbedtls_sha256(reinterpret_cast<const unsigned char*>(text.data()), text.size(), digest.data(), 0) != 0) {
    digest.fill(0xFF);
  }
  return digest;
}

bool asciiTitleContains""",
    "Notes content digest helper",
)

core = replace_once(
    core,
    """      : KeyboardEntryActivity(renderer, mappedInput, std::move(title), std::move(initialText), maxLength,
                              InputType::Multiline),
        path(std::move(path)), vaultPattern(std::move(vaultPattern)) {}

  void onExit() override {
    const bool saved = noteLockedByPath(path) ? saveEncryptedNoteFile(path, currentText(), vaultPattern)
                                               : saveNoteFile(path, currentText());
    if (!saved) LOG_ERR(\"NOTES\", \"Failed to autosave note before editor exit: %s\", path.c_str());
    std::fill(vaultPattern.begin(), vaultPattern.end(), '\\0');
    vaultPattern.clear();
    KeyboardEntryActivity::onExit();
  }
""",
    """      : KeyboardEntryActivity(renderer, mappedInput, std::move(title), std::move(initialText), maxLength,
                              InputType::Multiline),
        path(std::move(path)), vaultPattern(std::move(vaultPattern)) {
    capturePersistedState();
  }

  void onExit() override {
    if (contentChanged()) {
      const bool saved = noteLockedByPath(path) ? saveEncryptedNoteFile(path, currentText(), vaultPattern)
                                                 : saveNoteFile(path, currentText());
      if (!saved) {
        LOG_ERR(\"NOTES\", \"Failed to autosave note before editor exit: %s\", path.c_str());
      } else {
        capturePersistedState();
      }
    }
    std::fill(vaultPattern.begin(), vaultPattern.end(), '\\0');
    vaultPattern.clear();
    KeyboardEntryActivity::onExit();
  }
""",
    "Notes skip unchanged editor save",
)

core = replace_once(
    core,
    """ private:
  std::string path;
  std::string vaultPattern;

  Rect lockButtonRect() const {
""",
    """ private:
  std::string path;
  std::string vaultPattern;
  std::array<uint8_t, 32> persistedDigest{};
  bool persistedDigestValid = false;

  void capturePersistedState() {
    persistedDigest = noteTextDigest(currentText());
    persistedDigestValid = true;
  }

  bool contentChanged() const {
    return !persistedDigestValid || noteTextDigest(currentText()) != persistedDigest;
  }

  Rect lockButtonRect() const {
""",
    "Notes editor persisted digest state",
)

core = replace_once(
    core,
    """    if (!pattern.empty()) vaultPattern = pattern;
    requestUpdate(true);
    return true;
  }

  void beginUnlock() {
""",
    """    if (!pattern.empty()) vaultPattern = pattern;
    capturePersistedState();
    requestUpdate(true);
    return true;
  }

  void beginUnlock() {
""",
    "Notes lock save digest refresh",
)

core = replace_once(
    core,
    """    removeLockMarker(path);
    requestUpdate(true);
  }

  void beginLock() {
""",
    """    removeLockMarker(path);
    capturePersistedState();
    requestUpdate(true);
  }

  void beginLock() {
""",
    "Notes unlock save digest refresh",
)

core = replace_once(
    core,
    """void NotesActivity::onExit() {
  filteredNotes.clear();
  notes.clear();
""",
    """void NotesActivity::onExit() {
  filteredNotes.clear();
  noteLockedStates.clear();
  notes.clear();
""",
    "Notes clear lock metadata cache",
)

core = replace_once(
    core,
    """void NotesActivity::reloadNotes() {
  notes.clear();
  auto dir = Storage.open(kNotesDir);
""",
    """void NotesActivity::reloadNotes() {
  notes.clear();
  noteLockedStates.clear();
  auto dir = Storage.open(kNotesDir);
""",
    "Notes reset lock metadata cache",
)

core = replace_once(
    core,
    """  dir.close();
  std::sort(notes.begin(), notes.end());
}

void NotesActivity::applyFilter() {
""",
    """  dir.close();
  std::sort(notes.begin(), notes.end());
  noteLockedStates.reserve(notes.size());
  for (const auto& filename : notes) {
    noteLockedStates.push_back(noteLockedByFilename(filename) ? 1u : 0u);
  }
}

void NotesActivity::applyFilter() {
""",
    "Notes build lock metadata cache",
)

core = replace_once(
    core,
    """    const auto& filename = notes[i];
    const bool locked = noteLockedByFilename(filename);
    if (!vaultMode && locked) continue;
""",
    """    const auto& filename = notes[i];
    const bool locked = i < noteLockedStates.size() && noteLockedStates[i] != 0;
    if (!vaultMode && locked) continue;
""",
    "Notes filter cached lock state",
)

core = replace_once(
    core,
    """      [this](const ActivityResult&) {
        reloadNotes();
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::createNote() {
""",
    """      [this, path](const ActivityResult&) {
        const size_t slash = path.find_last_of('/');
        const std::string filename = slash == std::string::npos ? path : path.substr(slash + 1);
        const auto it = std::lower_bound(notes.begin(), notes.end(), filename);
        if (it == notes.end() || *it != filename) {
          reloadNotes();
          applyFilter();
          requestUpdate();
          return;
        }
        const size_t noteIndex = static_cast<size_t>(it - notes.begin());
        if (noteIndex >= noteLockedStates.size()) {
          reloadNotes();
          applyFilter();
          requestUpdate();
          return;
        }
        const bool wasLocked = noteLockedStates[noteIndex] != 0;
        const bool isLocked = noteLockedByPath(path);
        noteLockedStates[noteIndex] = isLocked ? 1u : 0u;
        if (!searchQuery.empty() || wasLocked != isLocked) applyFilter();
        requestUpdate();
      });
}

void NotesActivity::createNote() {
""",
    "Notes avoid directory rescan after editor",
)

core = replace_once(
    core,
    """        const std::string& tappedFilename = notes[filteredNotes[static_cast<size_t>(index)]];
        if (vaultMode && noteLockedByFilename(tappedFilename) && pointInRect(lockRect, tx, ty)) return;
""",
    """        const size_t tappedNoteIndex = filteredNotes[static_cast<size_t>(index)];
        const std::string& tappedFilename = notes[tappedNoteIndex];
        const bool tappedLocked = tappedNoteIndex < noteLockedStates.size() && noteLockedStates[tappedNoteIndex] != 0;
        if (vaultMode && tappedLocked && pointInRect(lockRect, tx, ty)) return;
""",
    "Notes touch cached lock state",
)

core = replace_once(
    core,
    """      const std::string& rowFilename = notes[filteredNotes[static_cast<size_t>(index)]];
      const bool rowLocked = noteLockedByFilename(rowFilename);
""",
    """      const size_t rowNoteIndex = filteredNotes[static_cast<size_t>(index)];
      const std::string& rowFilename = notes[rowNoteIndex];
      const bool rowLocked = rowNoteIndex < noteLockedStates.size() && noteLockedStates[rowNoteIndex] != 0;
""",
    "Notes render cached lock state",
)

core_path.write_text(core)


# ---------------------------------------------------------------------------
# Final Minesweeper optimizations: cache counters between real state changes
# and skip SD writes when the exact serialized game state did not change.
# The timestamp remains the timestamp of the last actual state save.
# ---------------------------------------------------------------------------
mine_h_path = Path("src/activities/home/MinesweeperActivity.h")
mine_h = mine_h_path.read_text()
mine_h = replace_once(
    mine_h,
    "  static constexpr int kPackedBytes = (kMaxCells + 7) / 8;\n",
    "  static constexpr int kPackedBytes = (kMaxCells + 7) / 8;\n  static constexpr int kMaxSaveStateBytes = 4 + 3 * kPackedBytes;\n",
    "Minesweeper save snapshot capacity",
)
mine_h = replace_once(
    mine_h,
    """  CellBits mines_{};
  CellBits revealed_{};
  CellBits flagged_{};
  bool minesPlaced_ = false;
""",
    """  CellBits mines_{};
  CellBits revealed_{};
  CellBits flagged_{};
  std::array<uint8_t, kMaxSaveStateBytes> savedStateSnapshot_{};
  uint16_t savedStateSize_ = 0;
  bool savedStateValid_ = false;
  int cachedFlagCount_ = 0;
  int cachedCorrectFlagCount_ = 0;
  bool countersDirty_ = true;
  bool minesPlaced_ = false;
""",
    "Minesweeper cached state members",
)
mine_h = replace_once(
    mine_h,
    """  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
""",
    """  uint16_t buildSaveStateSnapshot(std::array<uint8_t, kMaxSaveStateBytes>& snapshot) const;
  bool loadSavedGame();
  bool saveGame();
  void clearSavedGame();
""",
    "Minesweeper save snapshot helper declaration",
)
mine_h_path.write_text(mine_h)

mine_path = Path("src/activities/home/MinesweeperActivity.cpp")
mine = mine_path.read_text()

mine = replace_once(
    mine,
    """  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  hasSavedGame_ = loadSavedGame();
""",
    """  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  savedStateValid_ = false;
  savedStateSize_ = 0;
  countersDirty_ = true;
  hasSavedGame_ = loadSavedGame();
""",
    "Minesweeper reset cached state on enter",
)

mine = replace_once(
    mine,
    """  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  minesPlaced_ = false;
""",
    """  mines_.fill(0);
  revealed_.fill(0);
  flagged_.fill(0);
  countersDirty_ = true;
  minesPlaced_ = false;
""",
    "Minesweeper counters dirty on reset",
)

mine = replace_once(
    mine,
    """  minesPlaced_ = true;
}

void MinesweeperActivity::revealCell""",
    """  minesPlaced_ = true;
  countersDirty_ = true;
}

void MinesweeperActivity::revealCell""",
    "Minesweeper counters dirty after mine placement",
)

mine = replace_once(
    mine,
    """  flagged_[index] = flagged_[index] ? 0 : 1;
  // The game save already contains officialScore; loadSavedGame() restores it
""",
    """  flagged_[index] = flagged_[index] ? 0 : 1;
  countersDirty_ = true;
  // The game save already contains officialScore; loadSavedGame() restores it
""",
    "Minesweeper counters dirty on flag",
)

mine = replace_once(
    mine,
    """  flushBestScores();
  clearSavedGame();
  viewMode_ = ViewMode::Result;
""",
    """  countersDirty_ = true;
  flushBestScores();
  clearSavedGame();
  viewMode_ = ViewMode::Result;
""",
    "Minesweeper counters dirty on finish",
)

snapshot_helper = r'''uint16_t MinesweeperActivity::buildSaveStateSnapshot(
    std::array<uint8_t, kMaxSaveStateBytes>& snapshot) const {
  const int cellCount = totalCells();
  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);
  const uint8_t grid = static_cast<uint8_t>(gridSizeIndex_);
  const uint8_t stateFlags = static_cast<uint8_t>((assistedCounterActive ? 0x01 : 0x00) |
                                                   (scoreFrozen ? 0x02 : 0x00));
  const uint8_t selected = static_cast<uint8_t>(std::clamp(selectedCellIndex_, 0, cellCount - 1));
  const uint8_t savedOfficialScore = static_cast<uint8_t>(std::clamp(officialScore, 0, 255));

  size_t offset = 0;
  snapshot[offset++] = grid;
  snapshot[offset++] = stateFlags;
  snapshot[offset++] = selected;
  snapshot[offset++] = savedOfficialScore;
  memcpy(snapshot.data() + offset, mines_.data(), packedBytes);
  offset += packedBytes;
  memcpy(snapshot.data() + offset, revealed_.data(), packedBytes);
  offset += packedBytes;
  memcpy(snapshot.data() + offset, flagged_.data(), packedBytes);
  offset += packedBytes;
  return static_cast<uint16_t>(offset);
}

'''
mine = replace_once(
    mine,
    "bool MinesweeperActivity::saveGame() {\n",
    snapshot_helper + "bool MinesweeperActivity::saveGame() {\n",
    "Minesweeper save snapshot helper definition",
)

mine = replace_once(
    mine,
    """bool MinesweeperActivity::saveGame() {
  if (gameOver_) return false;
  Storage.mkdir(SAVE_DIR);
""",
    """bool MinesweeperActivity::saveGame() {
  if (gameOver_) return false;
  std::array<uint8_t, kMaxSaveStateBytes> currentState{};
  const uint16_t currentStateSize = buildSaveStateSnapshot(currentState);
  if (hasSavedGame_ && savedStateValid_ && savedStateSize_ == currentStateSize &&
      memcmp(savedStateSnapshot_.data(), currentState.data(), currentStateSize) == 0) {
    return true;
  }
  Storage.mkdir(SAVE_DIR);
""",
    "Minesweeper skip unchanged save",
)

mine = replace_once(
    mine,
    """  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    return false;
  }
""",
    """  if (!ok) {
    Storage.remove(SAVE_PATH);
    hasSavedGame_ = false;
    savedStateValid_ = false;
    savedStateSize_ = 0;
    return false;
  }
""",
    "Minesweeper invalidate snapshot on failed save",
)

mine = replace_once(
    mine,
    """  hasSavedGame_ = true;
  savedGridSizeIndex_ = static_cast<uint8_t>(gridSizeIndex_);
  savedAtPacked_ = savedAt;
  return true;
}

bool MinesweeperActivity::loadSavedGame() {
""",
    """  hasSavedGame_ = true;
  savedGridSizeIndex_ = static_cast<uint8_t>(gridSizeIndex_);
  savedAtPacked_ = savedAt;
  std::copy_n(currentState.data(), currentStateSize, savedStateSnapshot_.data());
  savedStateSize_ = currentStateSize;
  savedStateValid_ = true;
  return true;
}

bool MinesweeperActivity::loadSavedGame() {
""",
    "Minesweeper cache successful save state",
)

mine = replace_once(
    mine,
    """  officialScore = scoreFrozen ? savedOfficialScore : revealedSafeCells_;
  updateBestScore(gridSizeIndex_, officialScore);
  gameOver_ = false;
  won_ = false;
  return true;
}
""",
    """  officialScore = scoreFrozen ? savedOfficialScore : revealedSafeCells_;
  updateBestScore(gridSizeIndex_, officialScore);
  gameOver_ = false;
  won_ = false;
  countersDirty_ = true;
  savedStateSize_ = buildSaveStateSnapshot(savedStateSnapshot_);
  savedStateValid_ = true;
  return true;
}
""",
    "Minesweeper cache loaded save state",
)

mine = replace_once(
    mine,
    """void MinesweeperActivity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
  savedAtPacked_ = 0;
}
""",
    """void MinesweeperActivity::clearSavedGame() {
  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);
  hasSavedGame_ = false;
  savedAtPacked_ = 0;
  savedStateValid_ = false;
  savedStateSize_ = 0;
}
""",
    "Minesweeper invalidate snapshot on clear",
)

mine = replace_once(
    mine,
    """  int flags = 0;
  int correctFlags = 0;
  for (int i = 0; i < totalCells(); ++i) {
    if (!flagged_[i]) continue;
    ++flags;
    if (minesPlaced_ && mines_[i]) ++correctFlags;
  }

  char title[64];
""",
    """  if (countersDirty_) {
    cachedFlagCount_ = 0;
    cachedCorrectFlagCount_ = 0;
    for (int i = 0; i < totalCells(); ++i) {
      if (!flagged_[i]) continue;
      ++cachedFlagCount_;
      if (minesPlaced_ && mines_[i]) ++cachedCorrectFlagCount_;
    }
    countersDirty_ = false;
  }
  const int flags = cachedFlagCount_;
  const int correctFlags = cachedCorrectFlagCount_;

  char title[64];
""",
    "Minesweeper cached counter calculation",
)

mine_path.write_text(mine)


# Final self-checks make overlay drift fail loudly before compilation.
def require(path: str, needle: str, label: str) -> None:
    if needle not in Path(path).read_text():
        raise RuntimeError(f"Final Notes/Minesweeper optimization missing: {label}")


require("src/activities/home/NotesActivity.h", "noteLockedStates", "Notes lock metadata cache")
require("src/activities/home/NotesActivityCore.inc", "if (contentChanged())", "Notes unchanged-save guard")
require("src/activities/home/NotesActivityCore.inc", "if (!searchQuery.empty() || wasLocked != isLocked) applyFilter();",
        "Notes editor return fast path")
require("src/activities/home/MinesweeperActivity.h", "savedStateSnapshot_", "Minesweeper save snapshot")
require("src/activities/home/MinesweeperActivity.cpp", "memcmp(savedStateSnapshot_.data(), currentState.data()",
        "Minesweeper unchanged-save guard")
require("src/activities/home/MinesweeperActivity.cpp", "if (countersDirty_)", "Minesweeper cached counters")

print("Applied MSW5 compile fix and final Notes/Minesweeper IO/CPU optimizations.")
