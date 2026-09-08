from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


header_path = Path("src/activities/home/MinesweeperActivity.h")
header = header_path.read_text()
header = replace_once(
    header,
    '''  uint8_t savedGridSizeIndex_ = 0;\n  std::array<char, 32> continueLabel_{};\n  int visibleRows_ = 1;\n''',
    '''  uint8_t savedGridSizeIndex_ = 0;\n  uint32_t savedAtPacked_ = 0;\n  std::array<char, 64> continueLabel_{};\n  int visibleRows_ = 1;\n''',
    "Minesweeper saved timestamp state",
)
header_path.write_text(header)

cpp_path = Path("src/activities/home/MinesweeperActivity.cpp")
cpp = cpp_path.read_text()

cpp = replace_once(
    cpp,
    '#include <I18n.h>\n',
    '#include <I18n.h>\n#include <Rtc.h>\n',
    "Minesweeper RTC include",
)

cpp = replace_once(
    cpp,
    '''constexpr uint32_t SAVE_MAGIC = 0x4D535734;  // MSW4: packed, intentionally incompatible with old saves.\n''',
    '''constexpr uint32_t SAVE_MAGIC_V4 = 0x4D535734;  // MSW4: packed state without timestamp.\nconstexpr uint32_t SAVE_MAGIC = 0x4D535735;     // MSW5: packed state + local RTC save time.\n''',
    "Minesweeper save format version",
)

insert_before = '''bool undoAvailable = false;\n'''
helpers = r'''uint32_t packSaveDateTime(const Rtc::DateTime& dt) {
  if (dt.year < 2000 || dt.year > 2127 || dt.month < 1 || dt.month > 12 || dt.day < 1 || dt.day > 31 ||
      dt.hour > 23 || dt.minute > 59) {
    return 0;
  }
  return (static_cast<uint32_t>(dt.year - 2000) << 20) | (static_cast<uint32_t>(dt.month) << 16) |
         (static_cast<uint32_t>(dt.day) << 11) | (static_cast<uint32_t>(dt.hour) << 6) |
         static_cast<uint32_t>(dt.minute);
}

uint32_t currentSaveDateTime() {
  // Rtc::begin() only has to initialise/probe the shared I2C clock once per boot.
  static Rtc rtc;
  static bool beginAttempted = false;
  static bool available = false;
  if (!beginAttempted) {
    available = rtc.begin();
    beginAttempted = true;
  }
  if (!available) return 0;
  Rtc::DateTime now{};
  if (!rtc.now(now)) return 0;
  return packSaveDateTime(now);
}

bool formatSaveDateTime(const uint32_t packed, char* out, const size_t outSize) {
  if (packed == 0 || out == nullptr || outSize == 0) return false;
  const unsigned year = 2000u + ((packed >> 20) & 0x7Fu);
  const unsigned month = (packed >> 16) & 0x0Fu;
  const unsigned day = (packed >> 11) & 0x1Fu;
  const unsigned hour = (packed >> 6) & 0x1Fu;
  const unsigned minute = packed & 0x3Fu;
  if (year < 2000 || year > 2127 || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59)
    return false;
  std::snprintf(out, outSize, "%02u/%02u %02u:%02u", day, month, hour, minute);
  return true;
}

'''
cpp = replace_once(cpp, insert_before, helpers + insert_before, "Minesweeper RTC timestamp helpers")

cpp = replace_once(
    cpp,
    '''  const uint8_t savedOfficialScore = static_cast<uint8_t>(std::clamp(officialScore, 0, 255));\n\n  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, grid) && writeValue(file, stateFlags) &&\n            writeValue(file, selected) && writeValue(file, savedOfficialScore);\n''',
    '''  const uint8_t savedOfficialScore = static_cast<uint8_t>(std::clamp(officialScore, 0, 255));\n  const uint32_t rtcNow = currentSaveDateTime();\n  const uint32_t savedAt = rtcNow != 0 ? rtcNow : savedAtPacked_;\n\n  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, grid) && writeValue(file, stateFlags) &&\n            writeValue(file, selected) && writeValue(file, savedOfficialScore) && writeValue(file, savedAt);\n''',
    "Minesweeper write save timestamp",
)

cpp = replace_once(
    cpp,
    '''  hasSavedGame_ = true;\n  savedGridSizeIndex_ = static_cast<uint8_t>(gridSizeIndex_);\n  return true;\n}\n\nbool MinesweeperActivity::loadSavedGame() {\n''',
    '''  hasSavedGame_ = true;\n  savedGridSizeIndex_ = static_cast<uint8_t>(gridSizeIndex_);\n  savedAtPacked_ = savedAt;\n  return true;\n}\n\nbool MinesweeperActivity::loadSavedGame() {\n''',
    "Minesweeper remember save timestamp",
)

cpp = replace_once(
    cpp,
    '''  uint8_t savedOfficialScore = 0;\n  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n            readValue(file, selected) && readValue(file, savedOfficialScore);\n\n  if (!ok || magic != SAVE_MAGIC || grid >= kGridOptionCount) {\n    file.close();\n    clearSavedGame();\n    return false;\n  }\n\n  gridSizeIndex_ = grid;\n  savedGridSizeIndex_ = grid;\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  constexpr size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t);\n  const size_t expectedSize = headerBytes + 3 * packedBytes;\n''',
    '''  uint8_t savedOfficialScore = 0;\n  uint32_t savedAt = 0;\n  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n            readValue(file, selected) && readValue(file, savedOfficialScore);\n  const bool legacyV4 = ok && magic == SAVE_MAGIC_V4;\n  const bool timestampedV5 = ok && magic == SAVE_MAGIC;\n  if (timestampedV5) ok = readValue(file, savedAt);\n\n  if (!ok || (!legacyV4 && !timestampedV5) || grid >= kGridOptionCount) {\n    file.close();\n    clearSavedGame();\n    return false;\n  }\n\n  gridSizeIndex_ = grid;\n  savedGridSizeIndex_ = grid;\n  savedAtPacked_ = timestampedV5 ? savedAt : 0;\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  const size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t) +\n                             (timestampedV5 ? sizeof(uint32_t) : 0);\n  const size_t expectedSize = headerBytes + 3 * packedBytes;\n''',
    "Minesweeper read V4/V5 timestamped saves",
)

cpp = replace_once(
    cpp,
    '''void MinesweeperActivity::clearSavedGame() {\n  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);\n  hasSavedGame_ = false;\n}\n''',
    '''void MinesweeperActivity::clearSavedGame() {\n  if (Storage.exists(SAVE_PATH)) Storage.remove(SAVE_PATH);\n  hasSavedGame_ = false;\n  savedAtPacked_ = 0;\n}\n''',
    "Minesweeper clear timestamp",
)

cpp = replace_once(
    cpp,
    '''  if (hasSavedGame_) {\n    const int savedGrid = std::clamp(static_cast<int>(savedGridSizeIndex_), 0, kGridOptionCount - 1);\n    std::snprintf(continueLabel_.data(), continueLabel_.size(), "Continuer la partie %s", GRID_DIMS[savedGrid]);\n    items[5].label = continueLabel_.data();\n    items[5].value = nullptr;\n  } else {\n''',
    '''  if (hasSavedGame_) {\n    const int savedGrid = std::clamp(static_cast<int>(savedGridSizeIndex_), 0, kGridOptionCount - 1);\n    std::array<char, 16> savedWhen{};\n    if (formatSaveDateTime(savedAtPacked_, savedWhen.data(), savedWhen.size())) {\n      std::snprintf(continueLabel_.data(), continueLabel_.size(), "Continuer la partie %s - %s",\n                    GRID_DIMS[savedGrid], savedWhen.data());\n    } else {\n      std::snprintf(continueLabel_.data(), continueLabel_.size(), "Continuer la partie %s", GRID_DIMS[savedGrid]);\n    }\n    items[5].label = continueLabel_.data();\n    items[5].value = nullptr;\n  } else {\n''',
    "Minesweeper dated continue label",
)

cpp_path.write_text(cpp)
print("Applied Minesweeper RTC save timestamp with MSW4 backward compatibility.")
