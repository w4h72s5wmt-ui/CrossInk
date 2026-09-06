from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"missing replacement: {label}")
    return text.replace(old, new, 1)


def replace_span(text, start_marker, end_marker, replacement, label):
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"missing start marker: {label}")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"missing end marker: {label}")
    return text[:start] + replacement + text[end:]


# Minesweeper: pack 256 boolean cells into 32 bytes per plane.
header = Path("src/activities/home/MinesweeperActivity.h")
text = header.read_text()
text = replace_once(
    text,
    "  static constexpr int kMaxCells = 16 * 16;\n  static constexpr unsigned long kFlagHoldMs = 700;\n\n  enum class ViewMode {\n",
    """  static constexpr int kMaxCells = 16 * 16;\n  static constexpr int kPackedBytes = (kMaxCells + 7) / 8;\n  static constexpr unsigned long kFlagHoldMs = 700;\n\n  struct CellBits {\n    class Reference {\n     public:\n      Reference(CellBits& owner, const int index) : owner_(owner), index_(index) {}\n      Reference& operator=(const bool value) {\n        owner_.set(index_, value);\n        return *this;\n      }\n      Reference& operator=(const Reference& other) { return *this = static_cast<bool>(other); }\n      operator bool() const { return owner_.get(index_); }\n\n     private:\n      CellBits& owner_;\n      int index_;\n    };\n\n    std::array<uint8_t, kPackedBytes> bytes{};\n\n    bool get(const int index) const {\n      return (bytes[static_cast<size_t>(index >> 3)] & static_cast<uint8_t>(1u << (index & 7))) != 0;\n    }\n    void set(const int index, const bool value = true) {\n      auto& byte = bytes[static_cast<size_t>(index >> 3)];\n      const uint8_t mask = static_cast<uint8_t>(1u << (index & 7));\n      if (value) {\n        byte = static_cast<uint8_t>(byte | mask);\n      } else {\n        byte = static_cast<uint8_t>(byte & static_cast<uint8_t>(~mask));\n      }\n    }\n    void fill(const uint8_t value) { bytes.fill(value ? 0xFF : 0); }\n    Reference operator[](const int index) { return Reference(*this, index); }\n    bool operator[](const int index) const { return get(index); }\n    uint8_t* data() { return bytes.data(); }\n    const uint8_t* data() const { return bytes.data(); }\n    bool any() const {\n      for (const uint8_t byte : bytes) {\n        if (byte != 0) return true;\n      }\n      return false;\n    }\n  };\n\n  enum class ViewMode {\n""",
    "minesweeper bitset helper",
)
text = replace_once(
    text,
    "  std::array<uint8_t, kMaxCells> mines_{};\n  std::array<uint8_t, kMaxCells> revealed_{};\n  std::array<uint8_t, kMaxCells> flagged_{};\n",
    "  CellBits mines_{};\n  CellBits revealed_{};\n  CellBits flagged_{};\n",
    "minesweeper packed planes",
)
header.write_text(text)

mine = Path("src/activities/home/MinesweeperActivity.cpp")
text = mine.read_text()
text = replace_once(
    text,
    "constexpr uint32_t SAVE_MAGIC = 0x4D535731;\nconstexpr uint8_t SAVE_VERSION = 3;\nconstexpr uint8_t PREVIOUS_SAVE_VERSION = 2;\nconstexpr uint8_t LEGACY_SAVE_VERSION = 1;\n",
    "constexpr uint32_t SAVE_MAGIC = 0x4D535734;  // MSW4: packed, intentionally incompatible with old saves.\n",
    "minesweeper drop legacy save versions",
)

flood = """void MinesweeperActivity::revealFlood(const int startIndex) {\n  std::array<uint8_t, kMaxCells> queue{};\n  const int dimension = gridDimension();\n  const int cellCount = dimension * dimension;\n  int head = 0;\n  int tail = 0;\n  queue[tail++] = static_cast<uint8_t>(startIndex);\n\n  while (head < tail) {\n    const int index = queue[head++];\n    if (index < 0 || index >= cellCount || revealed_[index] || flagged_[index] || mines_[index]) continue;\n    revealed_[index] = 1;\n    ++revealedSafeCells_;\n    if (adjacentMineCount(index) != 0) continue;\n\n    const int row = index / dimension;\n    const int col = index % dimension;\n    for (int dr = -1; dr <= 1; ++dr) {\n      for (int dc = -1; dc <= 1; ++dc) {\n        if (dr == 0 && dc == 0) continue;\n        const int nr = row + dr;\n        const int nc = col + dc;\n        if (nr < 0 || nr >= dimension || nc < 0 || nc >= dimension) continue;\n        const int next = nr * dimension + nc;\n        if (!revealed_[next] && !flagged_[next] && !mines_[next] && tail < kMaxCells) {\n          queue[tail++] = static_cast<uint8_t>(next);\n        }\n      }\n    }\n  }\n}\n\n"""
text = replace_span(
    text,
    "void MinesweeperActivity::revealFlood(const int startIndex) {",
    "void MinesweeperActivity::toggleFlag",
    flood,
    "minesweeper compact flood queue",
)

save_load = """bool MinesweeperActivity::saveGame() {\n  if (gameOver_) return false;\n  Storage.mkdir(SAVE_DIR);\n  FsFile file;\n  if (!Storage.openFileForWrite(\"MINE\", SAVE_PATH, file)) return false;\n\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  const uint8_t grid = static_cast<uint8_t>(gridSizeIndex_);\n  const uint8_t stateFlags = static_cast<uint8_t>((assistedCounterActive ? 0x01 : 0x00) |\n                                                   (scoreFrozen ? 0x02 : 0x00));\n  const uint8_t selected = static_cast<uint8_t>(std::clamp(selectedCellIndex_, 0, cellCount - 1));\n  const uint8_t savedOfficialScore = static_cast<uint8_t>(std::clamp(officialScore, 0, 255));\n\n  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, grid) && writeValue(file, stateFlags) &&\n            writeValue(file, selected) && writeValue(file, savedOfficialScore);\n  if (ok) ok = file.write(mines_.data(), packedBytes) == packedBytes;\n  if (ok) ok = file.write(revealed_.data(), packedBytes) == packedBytes;\n  if (ok) ok = file.write(flagged_.data(), packedBytes) == packedBytes;\n  file.close();\n\n  if (!ok) {\n    Storage.remove(SAVE_PATH);\n    hasSavedGame_ = false;\n    return false;\n  }\n  hasSavedGame_ = true;\n  return true;\n}\n\nbool MinesweeperActivity::loadSavedGame() {\n  undoAvailable = false;\n  undoMineIndex = -1;\n  lossUndoDeadlineUs = 0;\n  assistedCounterActive = false;\n  assistedCounterChoice = false;\n  if (!Storage.exists(SAVE_PATH)) return false;\n\n  FsFile file;\n  if (!Storage.openFileForRead(\"MINE\", SAVE_PATH, file)) return false;\n\n  uint32_t magic = 0;\n  uint8_t grid = 0;\n  uint8_t stateFlags = 0;\n  uint8_t selected = 0;\n  uint8_t savedOfficialScore = 0;\n  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n            readValue(file, selected) && readValue(file, savedOfficialScore);\n\n  if (!ok || magic != SAVE_MAGIC || grid >= kGridOptionCount) {\n    file.close();\n    clearSavedGame();\n    return false;\n  }\n\n  gridSizeIndex_ = grid;\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  constexpr size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t);\n  const size_t expectedSize = headerBytes + 3 * packedBytes;\n  if (file.size() != expectedSize || selected >= cellCount) {\n    file.close();\n    clearSavedGame();\n    resetGame();\n    return false;\n  }\n\n  mines_.fill(0);\n  revealed_.fill(0);\n  flagged_.fill(0);\n  ok = file.read(mines_.data(), packedBytes) == static_cast<int>(packedBytes);\n  if (ok) ok = file.read(revealed_.data(), packedBytes) == static_cast<int>(packedBytes);\n  if (ok) ok = file.read(flagged_.data(), packedBytes) == static_cast<int>(packedBytes);\n  file.close();\n\n  if (!ok) {\n    clearSavedGame();\n    resetGame();\n    return false;\n  }\n\n  minesPlaced_ = mines_.any();\n  assistedCounterActive = (stateFlags & 0x01) != 0;\n  assistedCounterChoice = assistedCounterActive;\n  selectedCellIndex_ = selected;\n  revealedSafeCells_ = 0;\n  for (int i = 0; i < cellCount; ++i) {\n    if (revealed_[i] && !mines_[i]) ++revealedSafeCells_;\n  }\n\n  scoreFrozen = (stateFlags & 0x02) != 0;\n  if (scoreFrozen && savedOfficialScore > revealedSafeCells_) {\n    clearSavedGame();\n    resetGame();\n    return false;\n  }\n  officialScore = scoreFrozen ? savedOfficialScore : revealedSafeCells_;\n  updateBestScore(gridSizeIndex_, officialScore);\n  gameOver_ = false;\n  won_ = false;\n  return true;\n}\n\n"""
text = replace_span(
    text,
    "bool MinesweeperActivity::saveGame() {",
    "void MinesweeperActivity::clearSavedGame() {",
    save_load,
    "minesweeper packed save format",
)
mine.write_text(text)

# Predictive text: parse and write the personal dictionary without whole-file heap buffers.
predictive = Path("src/activities/util/PredictiveText.cpp")
text = predictive.read_text()
text = replace_once(text, "#include <cctype>\n#include <cstdlib>\n", "#include <cctype>\n#include <cstdio>\n#include <cstdlib>\n", "predictive cstdio include")

streaming_io = """void PredictiveText::load() {\n  personal_.clear();\n  dirty_ = false;\n  invalidateSuggestionCache();\n  if (!Storage.exists(kPersonalPath)) return;\n\n  FsFile file;\n  if (!Storage.openFileForRead(\"PRED\", std::string(kPersonalPath), file)) return;\n  const uint32_t size = file.size();\n  if (size == 0 || size > kMaxPersonalFileBytes) {\n    file.close();\n    return;\n  }\n\n  std::array<uint8_t, 256> input{};\n  std::array<char, 64> line{};\n  size_t lineLength = 0;\n  bool overflow = false;\n\n  const auto consumeLine = [&]() {\n    if (!overflow && lineLength > 0) {\n      line[lineLength] = '\\0';\n      char* tab = std::strchr(line.data(), '\\t');\n      if (tab && tab[1] != '\\0') {\n        *tab = '\\0';\n        const unsigned long parsed = std::strtoul(line.data(), nullptr, 10);\n        addPersonalWord(std::string(tab + 1),\n                        static_cast<uint16_t>(std::min<unsigned long>(65535, std::max<unsigned long>(1, parsed))),\n                        true);\n      }\n    }\n    lineLength = 0;\n    overflow = false;\n  };\n\n  while (personal_.size() < kMaxPersonalWords) {\n    const int count = file.read(input.data(), input.size());\n    if (count <= 0) break;\n    for (int i = 0; i < count; ++i) {\n      const char c = static_cast<char>(input[static_cast<size_t>(i)]);\n      if (c == '\\n') {\n        consumeLine();\n        if (personal_.size() >= kMaxPersonalWords) break;\n        continue;\n      }\n      if (lineLength + 1 < line.size()) {\n        line[lineLength++] = c;\n      } else {\n        overflow = true;\n      }\n    }\n  }\n  if (personal_.size() < kMaxPersonalWords && (lineLength > 0 || overflow)) consumeLine();\n  file.close();\n  dirty_ = false;\n}\n\nvoid PredictiveText::save() {\n  if (!dirty_) return;\n  Storage.mkdir(kPersonalDir);\n  FsFile file = Storage.open(kPersonalPath, O_WRONLY | O_CREAT | O_TRUNC);\n  if (!file) return;\n\n  const size_t count = std::min(personal_.size(), kMaxPersonalWords);\n  std::array<uint16_t, kMaxPersonalWords> order{};\n  for (size_t i = 0; i < count; ++i) order[i] = static_cast<uint16_t>(i);\n  std::sort(order.begin(), order.begin() + count, [this](const uint16_t a, const uint16_t b) {\n    const auto& left = personal_[a];\n    const auto& right = personal_[b];\n    if (left.count != right.count) return left.count > right.count;\n    return left.word < right.word;\n  });\n\n  std::array<char, 64> line{};\n  bool ok = true;\n  for (size_t i = 0; i < count; ++i) {\n    const auto& item = personal_[order[i]];\n    const int lineSize = std::snprintf(line.data(), line.size(), \"%u\\t%s\\n\",\n                                       static_cast<unsigned>(item.count), item.word.c_str());\n    if (lineSize <= 0 || static_cast<size_t>(lineSize) >= line.size() ||\n        file.write(reinterpret_cast<const uint8_t*>(line.data()), static_cast<size_t>(lineSize)) !=\n            static_cast<size_t>(lineSize)) {\n      ok = false;\n      break;\n    }\n  }\n  file.close();\n  if (ok) dirty_ = false;\n}\n\n"""
text = replace_span(
    text,
    "void PredictiveText::load() {",
    "void PredictiveText::seedFromText",
    streaming_io,
    "predictive streaming dictionary io",
)
predictive.write_text(text)

# Restore the normal workflow in the same bot commit so the final branch stays clean.
workflow = Path(".github/workflows/notes-build.yml")
text = workflow.read_text()
text = replace_once(text, "permissions:\n  contents: write\n", "permissions:\n  contents: read\n", "restore workflow permissions")
apply_block = """      - name: Apply V3 app optimizations\n        run: |\n          set -euo pipefail\n          python3 scripts/app_optimize_v3.py\n          git config user.name \"github-actions[bot]\"\n          git config user.email \"41898282+github-actions[bot]@users.noreply.github.com\"\n          git rm scripts/app_optimize_v3.py\n          git add .github/workflows/notes-build.yml src/activities/home/MinesweeperActivity.h \\
                  src/activities/home/MinesweeperActivity.cpp src/activities/util/PredictiveText.cpp\n          git commit -m \"perf: pack minesweeper state and stream predictive storage\"\n          git push origin HEAD:x4-pro-notes\n\n"""
text = replace_once(text, apply_block, "", "restore clean workflow step")
workflow.write_text(text)
