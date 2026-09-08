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


# Development policy: only the current Notes format is supported. Old 4-step
# vault codes, CROSSNT1 encrypted notes and plaintext-with-lock-marker migration
# paths are deliberately removed. Losing old development data is acceptable.
core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()

core = replace_once(core, "constexpr size_t kLegacyPatternLength = 4;\n", "", "Notes remove legacy pattern length")
core = replace_once(
    core,
    "constexpr uint8_t kCryptoMagicV1[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '1'};\n"
    "constexpr uint8_t kCryptoMagicV2[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '2'};\n",
    "constexpr uint8_t kCryptoMagic[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '2'};\n",
    "Notes keep current crypto magic only",
)
core = core.replace("kCryptoMagicV2", "kCryptoMagic")

core = replace_once(
    core,
    '''    if (verify && pattern.size() == kLegacyPatternLength &&\n        patternFingerprint(pattern) == expectedFingerprint) {\n      setResult(ActivityResult{KeyboardResult{pattern}});\n      finish();\n      return;\n    }\n''',
    "",
    "Notes remove 4-step vault acceptance",
)
core = replace_once(
    core,
    "  if (pattern.size() != kPatternLength && pattern.size() != kLegacyPatternLength) return false;\n",
    "  if (pattern.size() != kPatternLength) return false;\n",
    "Notes current-only vault KDF length",
)
core = replace_once(
    core,
    "  const bool validPattern = pattern.size() == kPatternLength || pattern.size() == kLegacyPatternLength;\n",
    "  const bool validPattern = pattern.size() == kPatternLength;\n",
    "Notes current-only device-key pattern length",
)
core = replace_once(
    core,
    '''bool rewrapDeviceVaultKey(const std::string& pattern) {\n  std::array<uint8_t, kCryptoKeyBytes> vaultKey{};\n  if (!ensureDeviceVaultKey(pattern, true, vaultKey)) return false;\n  const bool ok = writeVaultKeyBackup(pattern, vaultKey);\n  std::fill(vaultKey.begin(), vaultKey.end(), 0);\n  return ok;\n}\n\n''',
    "",
    "Notes remove legacy vault rewrap helper",
)

current_load = r'''bool loadProtectedNoteFile(const std::string& path, const std::string& pattern, std::string& text) {
  text.clear();
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  const uint32_t size = file.size();
  constexpr size_t aadBytes = kCryptoMagicBytes + kCryptoNonceBytes;
  constexpr size_t headerBytes = aadBytes + kCryptoTagBytes;
  if (size < headerBytes || size > kMaxEncryptedPlaintextBytes + headerBytes) {
    file.close();
    return false;
  }

  std::array<uint8_t, kCryptoMagicBytes> magic{};
  std::array<uint8_t, kCryptoNonceBytes> nonce{};
  std::array<uint8_t, kCryptoTagBytes> storedTag{};
  if (file.read(magic.data(), magic.size()) != static_cast<int>(magic.size()) ||
      memcmp(magic.data(), kCryptoMagic, kCryptoMagicBytes) != 0 ||
      file.read(nonce.data(), nonce.size()) != static_cast<int>(nonce.size()) ||
      file.read(storedTag.data(), storedTag.size()) != static_cast<int>(storedTag.size())) {
    file.close();
    return false;
  }

  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!ensureDeviceVaultKey(pattern, false, key)) {
    file.close();
    return false;
  }

  std::array<uint8_t, aadBytes> aad{};
  memcpy(aad.data(), magic.data(), magic.size());
  memcpy(aad.data() + kCryptoMagicBytes, nonce.data(), nonce.size());
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key.data(), key.size() * 8);
  if (rc == 0) rc = mbedtls_gcm_starts(&gcm, MBEDTLS_GCM_DECRYPT, nonce.data(), nonce.size());
  if (rc == 0) rc = mbedtls_gcm_update_ad(&gcm, aad.data(), aad.size());

  const size_t cipherBytes = size - headerBytes;
  text.resize(cipherBytes);
  std::array<uint8_t, kCryptoChunkBytes> input{};
  std::array<uint8_t, kCryptoChunkBytes + 15> output{};
  size_t remaining = cipherBytes;
  size_t plainOffset = 0;
  while (rc == 0 && remaining > 0) {
    const size_t chunk = std::min(remaining, input.size());
    if (file.read(input.data(), chunk) != static_cast<int>(chunk)) {
      rc = -1;
      break;
    }
    size_t outputLength = 0;
    rc = mbedtls_gcm_update(&gcm, input.data(), chunk, output.data(), output.size(), &outputLength);
    if (rc == 0 && outputLength > 0) {
      if (plainOffset + outputLength > text.size()) {
        rc = -1;
        break;
      }
      memcpy(text.data() + plainOffset, output.data(), outputLength);
      plainOffset += outputLength;
    }
    remaining -= chunk;
  }

  std::array<uint8_t, 15> finalOutput{};
  size_t finalLength = 0;
  std::array<uint8_t, kCryptoTagBytes> computedTag{};
  if (rc == 0) {
    rc = mbedtls_gcm_finish(&gcm, finalOutput.data(), finalOutput.size(), &finalLength, computedTag.data(), computedTag.size());
  }
  mbedtls_gcm_free(&gcm);
  file.close();
  std::fill(key.begin(), key.end(), 0);

  if (rc == 0 && finalLength > 0) {
    if (plainOffset + finalLength > text.size()) {
      rc = -1;
    } else {
      memcpy(text.data() + plainOffset, finalOutput.data(), finalLength);
      plainOffset += finalLength;
    }
  }
  uint8_t tagDiff = 0;
  for (size_t i = 0; i < storedTag.size(); ++i) tagDiff |= static_cast<uint8_t>(storedTag[i] ^ computedTag[i]);
  if (rc != 0 || tagDiff != 0 || plainOffset != cipherBytes) {
    std::fill(text.begin(), text.end(), '\0');
    text.clear();
    return false;
  }
  return true;
}

'''
core = replace_section(
    core,
    "bool loadProtectedNoteFile(const std::string& path, const std::string& pattern, std::string& text) {\n",
    "bool noteFileIsEncrypted(const std::string& path) {\n",
    current_load,
    "Notes current-only encrypted loader",
)

current_detect = r'''bool noteFileIsEncrypted(const std::string& path) {
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  if (file.size() < kCryptoMagicBytes) {
    file.close();
    return false;
  }
  std::array<uint8_t, kCryptoMagicBytes> magic{};
  const int count = file.read(magic.data(), magic.size());
  file.close();
  return count == static_cast<int>(magic.size()) && memcmp(magic.data(), kCryptoMagic, kCryptoMagicBytes) == 0;
}

'''
core = replace_section(
    core,
    "bool noteFileIsEncrypted(const std::string& path) {\n",
    "bool purgeProtectedVaultNotes() {\n",
    current_detect,
    "Notes current-only encrypted detection",
)

current_prompt = r'''void NotesActivity::promptVaultAccess() {
  uint64_t expectedFingerprint = 0;
  if (!readVaultFingerprint(expectedFingerprint)) {
    requestUpdate();
    return;
  }
  startActivityForResult(
      std::make_unique<VaultPatternActivity>(renderer, mappedInput, true, expectedFingerprint, true),
      [this](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        const auto* pattern = std::get_if<KeyboardResult>(&result.data);
        if (!pattern) {
          requestUpdate();
          return;
        }
        if (pattern->text == kResetVaultToken) {
          if (!purgeProtectedVaultNotes()) {
            requestUpdate();
            return;
          }
          std::fill(vaultPattern.begin(), vaultPattern.end(), '\0');
          vaultPattern.clear();
          vaultMode = false;
          searchQuery.clear();
          selectorIndex = 0;
          topIndex = 0;
          reloadNotes();
          applyFilter();
          startActivityForResult(
              std::make_unique<VaultPatternActivity>(renderer, mappedInput, false, 0),
              [this](const ActivityResult& newCodeResult) {
                if (newCodeResult.isCancelled) {
                  requestUpdate();
                  return;
                }
                const auto* newCode = std::get_if<KeyboardResult>(&newCodeResult.data);
                if (!newCode || newCode->text.size() != kPatternLength) {
                  requestUpdate();
                  return;
                }
                if (!writeVaultFingerprint(patternFingerprint(newCode->text))) {
                  LOG_ERR("NOTES", "Failed to save reset Notes vault fingerprint");
                  requestUpdate();
                  return;
                }
                std::array<uint8_t, kCryptoKeyBytes> vaultKey{};
                if (!ensureDeviceVaultKey(newCode->text, true, vaultKey)) {
                  LOG_ERR("NOTES", "Failed to initialize reset Notes vault key");
                }
                std::fill(vaultKey.begin(), vaultKey.end(), 0);
                requestUpdate();
              });
          return;
        }
        if (pattern->text.size() != kPatternLength) {
          requestUpdate();
          return;
        }

        reloadNotes();
        std::array<uint8_t, kCryptoKeyBytes> vaultKey{};
        if (!ensureDeviceVaultKey(pattern->text, true, vaultKey)) {
          LOG_ERR("NOTES", "Failed to initialize/restore Notes vault key");
          requestUpdate();
          return;
        }
        std::fill(vaultKey.begin(), vaultKey.end(), 0);
        vaultPattern = pattern->text;
        vaultMode = true;
        searchQuery.clear();
        selectorIndex = 0;
        topIndex = 0;
        applyFilter();
        requestUpdate();
      });
}


'''
core = replace_section(
    core,
    "void NotesActivity::promptVaultAccess() {\n",
    "void NotesActivity::loop() {\n",
    current_prompt,
    "Notes remove legacy vault upgrade and note migration",
)
core_path.write_text(core)

notes_h_path = Path("src/activities/home/NotesActivity.h")
notes_h = notes_h_path.read_text()
notes_h = replace_once(notes_h, "  void migrateLockedNotes();\n", "", "Notes remove migration declaration")
notes_h_path.write_text(notes_h)


# Development policy: Minesweeper accepts only the current timestamped MSW5
# save. Older MSW4 data is rejected and cleared instead of being upgraded.
mine_path = Path("src/activities/home/MinesweeperActivity.cpp")
mine = mine_path.read_text()
mine = replace_once(
    mine,
    "constexpr uint32_t SAVE_MAGIC_V4 = 0x4D535734;  // MSW4: packed state without timestamp.\n"
    "constexpr uint32_t SAVE_MAGIC = 0x4D535735;     // MSW5: packed state + local RTC save time.\n",
    "constexpr uint32_t SAVE_MAGIC = 0x4D535735;  // MSW5: current timestamped save format.\n",
    "Minesweeper remove V4 save magic",
)
mine = replace_once(
    mine,
    '''  uint8_t savedOfficialScore = 0;\n  uint32_t savedAt = 0;\n  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n            readValue(file, selected) && readValue(file, savedOfficialScore);\n  const bool legacyV4 = ok && magic == SAVE_MAGIC_V4;\n  const bool timestampedV5 = ok && magic == SAVE_MAGIC;\n  if (timestampedV5) ok = readValue(file, savedAt);\n\n  if (!ok || (!legacyV4 && !timestampedV5) || grid >= kGridOptionCount) {\n    file.close();\n    clearSavedGame();\n    return false;\n  }\n\n  gridSizeIndex_ = grid;\n  savedGridSizeIndex_ = grid;\n  savedAtPacked_ = timestampedV5 ? savedAt : 0;\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  const size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t) +\n                             (timestampedV5 ? sizeof(uint32_t) : 0);\n  const size_t expectedSize = headerBytes + 3 * packedBytes;\n''',
    '''  uint8_t savedOfficialScore = 0;\n  uint32_t savedAt = 0;\n  const bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n                  readValue(file, selected) && readValue(file, savedOfficialScore) && readValue(file, savedAt);\n\n  if (!ok || magic != SAVE_MAGIC || grid >= kGridOptionCount) {\n    file.close();\n    clearSavedGame();\n    return false;\n  }\n\n  gridSizeIndex_ = grid;\n  savedGridSizeIndex_ = grid;\n  savedAtPacked_ = savedAt;\n  const int cellCount = totalCells();\n  const size_t packedBytes = static_cast<size_t>((cellCount + 7) / 8);\n  constexpr size_t headerBytes = sizeof(uint32_t) + 4 * sizeof(uint8_t) + sizeof(uint32_t);\n  const size_t expectedSize = headerBytes + 3 * packedBytes;\n''',
    "Minesweeper current-only save loader",
)
mine_path.write_text(mine)


# Fail early if any compiled compatibility path survived the cleanup.
def reject(path: str, needle: str, label: str) -> None:
    if needle in Path(path).read_text():
        raise RuntimeError(f"Current-format cleanup failed: {label}")


def require(path: str, needle: str, label: str) -> None:
    if needle not in Path(path).read_text():
        raise RuntimeError(f"Current-format cleanup failed: {label}")


for legacy_needle in (
    "kLegacyPatternLength",
    "kCryptoMagicV1",
    "migrateLockedNotes",
    "hasLegacyEncryptedPayload",
    "rewrapDeviceVaultKey",
):
    reject("src/activities/home/NotesActivityCore.inc", legacy_needle, f"Notes legacy token remains: {legacy_needle}")
reject("src/activities/home/NotesActivity.h", "migrateLockedNotes", "Notes migration declaration remains")
require("src/activities/home/NotesActivityCore.inc", "kCryptoMagic", "Notes current crypto magic missing")
reject("src/activities/home/MinesweeperActivity.cpp", "SAVE_MAGIC_V4", "Minesweeper V4 compatibility remains")
reject("src/activities/home/MinesweeperActivity.cpp", "legacyV4", "Minesweeper legacy branch remains")
reject("src/activities/home/MinesweeperActivity.cpp", "timestampedV5", "Minesweeper compatibility branch remains")
require("src/activities/home/MinesweeperActivity.cpp", "magic != SAVE_MAGIC", "Minesweeper current-format gate missing")

print("Removed legacy Notes/Minesweeper save compatibility; current development formats only.")
