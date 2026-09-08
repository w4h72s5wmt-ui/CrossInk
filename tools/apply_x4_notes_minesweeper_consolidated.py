from pathlib import Path
import runpy


# Build 145 is the development baseline. The four historical patches recreate
# its behaviour, then current-only format cleanup removes migration/compat paths.
PATCHES = (
    "tools/apply_x4_notes_minesweeper_overrides.py",
    "tools/apply_x4_notes_minesweeper_optimizations.py",
    "tools/apply_x4_notes_title_lock_visibility_fix.py",
    "tools/apply_x4_minesweeper_save_timestamp.py",
)

for patch in PATCHES:
    runpy.run_path(patch, run_name="__main__")


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


# Notes: stream encrypted saves to avoid a second note-sized payload in heap.
core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()
streaming_save = r'''bool saveEncryptedNoteFile(const std::string& path, const std::string& text, const std::string& pattern) {
  if (text.size() > kMaxEncryptedPlaintextBytes) return false;
  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!ensureDeviceVaultKey(pattern, true, key)) return false;

  constexpr size_t aadBytes = kCryptoMagicBytes + kCryptoNonceBytes;
  constexpr size_t headerBytes = aadBytes + kCryptoTagBytes;
  std::array<uint8_t, headerBytes> header{};
  memcpy(header.data(), kCryptoMagicV2, kCryptoMagicBytes);
  esp_fill_random(header.data() + kCryptoMagicBytes, kCryptoNonceBytes);

  const std::string tempPath = path + ".crypt.tmp";
  const std::string backupPath = path + ".crypt.bak";
  if (Storage.exists(tempPath.c_str())) Storage.remove(tempPath.c_str());
  if (Storage.exists(backupPath.c_str())) {
    if (!Storage.exists(path.c_str())) {
      Storage.rename(backupPath.c_str(), path.c_str());
    } else {
      Storage.remove(backupPath.c_str());
    }
  }

  FsFile file = Storage.open(tempPath.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) {
    std::fill(key.begin(), key.end(), 0);
    return false;
  }

  int rc = file.write(header.data(), header.size()) == header.size() ? 0 : -1;
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  if (rc == 0) rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key.data(), key.size() * 8);
  if (rc == 0) {
    rc = mbedtls_gcm_starts(&gcm, MBEDTLS_GCM_ENCRYPT, header.data() + kCryptoMagicBytes, kCryptoNonceBytes);
  }
  if (rc == 0) rc = mbedtls_gcm_update_ad(&gcm, header.data(), aadBytes);

  std::array<uint8_t, kCryptoChunkBytes + 15> output{};
  size_t offset = 0;
  while (rc == 0 && offset < text.size()) {
    const size_t chunk = std::min(kCryptoChunkBytes, text.size() - offset);
    size_t outputLength = 0;
    rc = mbedtls_gcm_update(&gcm, reinterpret_cast<const uint8_t*>(text.data() + offset), chunk,
                            output.data(), output.size(), &outputLength);
    if (rc == 0 && outputLength > 0 && file.write(output.data(), outputLength) != outputLength) rc = -1;
    offset += chunk;
  }

  std::array<uint8_t, 15> finalOutput{};
  std::array<uint8_t, kCryptoTagBytes> tag{};
  size_t finalLength = 0;
  if (rc == 0) {
    rc = mbedtls_gcm_finish(&gcm, finalOutput.data(), finalOutput.size(), &finalLength, tag.data(), tag.size());
  }
  mbedtls_gcm_free(&gcm);
  std::fill(key.begin(), key.end(), 0);

  if (rc == 0 && finalLength > 0 && file.write(finalOutput.data(), finalLength) != finalLength) rc = -1;
  if (rc == 0 && (!file.seekSet(aadBytes) || file.write(tag.data(), tag.size()) != tag.size())) rc = -1;
  if (rc == 0 && !file.sync()) rc = -1;
  file.close();

  if (rc != 0) {
    if (Storage.exists(tempPath.c_str())) Storage.remove(tempPath.c_str());
    return false;
  }

  bool movedOriginal = false;
  if (Storage.exists(path.c_str())) {
    if (!Storage.rename(path.c_str(), backupPath.c_str())) {
      Storage.remove(tempPath.c_str());
      return false;
    }
    movedOriginal = true;
  }
  if (!Storage.rename(tempPath.c_str(), path.c_str())) {
    if (movedOriginal) Storage.rename(backupPath.c_str(), path.c_str());
    if (Storage.exists(tempPath.c_str())) Storage.remove(tempPath.c_str());
    return false;
  }
  if (movedOriginal && Storage.exists(backupPath.c_str())) Storage.remove(backupPath.c_str());
  return true;
}

'''
core = replace_section(
    core,
    "bool saveEncryptedNoteFile(const std::string& path, const std::string& text, const std::string& pattern) {\n",
    "bool loadProtectedNoteFile(const std::string& path, const std::string& pattern, std::string& text) {\n",
    streaming_save,
    "Notes streaming encrypted save",
)
core_path.write_text(core)

# Safe compact state that does not disturb std::clamp/max arithmetic.
header_path = Path("src/activities/home/MinesweeperActivity.h")
header = header_path.read_text()
header = replace_once(header, "  enum class ViewMode {\n", "  enum class ViewMode : uint8_t {\n", "Minesweeper compact view mode")
header = replace_once(header, "  std::array<char, 64> continueLabel_{};\n",
                      "  std::array<char, 48> continueLabel_{};\n",
                      "Minesweeper compact continue label")
header_path.write_text(header)

cpp_path = Path("src/activities/home/MinesweeperActivity.cpp")
cpp = cpp_path.read_text()
cpp = replace_once(cpp, "    std::array<char, 16> savedWhen{};\n", "    std::array<char, 12> savedWhen{};\n",
                   "Minesweeper compact timestamp scratch")
cpp_path.write_text(cpp)

# Development-only policy: do not carry compatibility code for unpublished
# formats. Old saves/notes may be discarded during development.
runpy.run_path("tools/apply_x4_dev_current_formats_only.py", run_name="__main__")


def require(path: str, needle: str, label: str) -> None:
    text = Path(path).read_text()
    if needle not in text:
        raise RuntimeError(f"Consolidation validation failed: {label}")


def reject(path: str, needle: str, label: str) -> None:
    text = Path(path).read_text()
    if needle in text:
        raise RuntimeError(f"Consolidation validation failed: {label}")


require("src/activities/home/NotesActivityCore.inc", ".crypt.tmp", "Notes streaming save missing")
require("src/activities/home/NotesActivityCore.inc", "if (hasVault) {", "Notes passwordless locking missing")
reject("src/activities/home/NotesActivityCore.inc", "std::vector<uint8_t> payload(headerBytes + text.size())",
       "Notes full-size encryption buffer still present")
reject("src/activities/home/NotesActivityCore.inc", "kCryptoMagicV1", "Notes legacy encrypted format remains")
reject("src/activities/home/NotesActivityCore.inc", "kLegacyPatternLength", "Notes legacy vault code remains")
reject("src/activities/home/NotesActivityCore.inc", "migrateLockedNotes", "Notes migration code remains")
require("src/activities/home/NotesViewerKeyboardBase.h", "if (headerActionReserveWidth() <= 0) return;",
        "Notes title/search lock suppression missing")
require("src/activities/home/MinesweeperActivity.cpp", "currentSaveDateTime()", "Minesweeper RTC timestamp missing")
reject("src/activities/home/MinesweeperActivity.cpp", "SAVE_MAGIC_V4", "Minesweeper legacy save support remains")
reject("src/activities/home/MinesweeperActivity.cpp", "CellBits queued{};", "Minesweeper duplicate flood queue still present")
require("src/activities/home/MinesweeperActivity.h", "std::array<char, 48> continueLabel_{};",
        "Minesweeper compact continue label missing")

print("Applied and validated build-145 current-format-only Notes/Minesweeper overlay.")
