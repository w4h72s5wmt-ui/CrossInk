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


# Notes: passwordless locking with a device-side vault key, lower peak heap
# while decrypting, and fewer SD probes / temporary strings during search.
core_path = Path("src/activities/home/NotesActivityCore.inc")
core = core_path.read_text()

core = replace_once(core, '#include <mbedtls/sha256.h>\n', '#include <mbedtls/sha256.h>\n#include <nvs.h>\n',
                    "Notes NVS include")

core = replace_once(
    core,
    '''constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\nconstexpr const char* kResetVaultToken = "__RESET_VAULT__";\nconstexpr size_t kCryptoMagicBytes = 8;\nconstexpr size_t kCryptoNonceBytes = 12;\nconstexpr size_t kCryptoTagBytes = 16;\nconstexpr size_t kCryptoKeyBytes = 32;\nconstexpr uint8_t kCryptoMagic[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '1'};\n''',
    '''constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\nconstexpr const char* kVaultKeyBackupPath = "/Notes/.vaultkey";\nconstexpr const char* kVaultNvsNamespace = "crossinknotes";\nconstexpr const char* kVaultNvsKey = "vaultkey";\nconstexpr const char* kResetVaultToken = "__RESET_VAULT__";\nconstexpr size_t kCryptoMagicBytes = 8;\nconstexpr size_t kCryptoNonceBytes = 12;\nconstexpr size_t kCryptoTagBytes = 16;\nconstexpr size_t kCryptoKeyBytes = 32;\nconstexpr size_t kCryptoChunkBytes = 512;\nconstexpr uint8_t kCryptoMagicV1[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '1'};\nconstexpr uint8_t kCryptoMagicV2[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '2'};\nconstexpr uint8_t kVaultKeyBackupMagic[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'V', 'K', '1'};\n''',
    "Notes crypto constants",
)

core = replace_once(
    core,
    '''std::string lowerAscii(std::string value) {\n  for (char& c : value) {\n    const unsigned char uc = static_cast<unsigned char>(c);\n    if (uc < 0x80) c = static_cast<char>(std::tolower(uc));\n  }\n  return value;\n}\n''',
    '''std::string lowerAscii(std::string value) {\n  for (char& c : value) {\n    const unsigned char uc = static_cast<unsigned char>(c);\n    if (uc < 0x80) c = static_cast<char>(std::tolower(uc));\n  }\n  return value;\n}\n\nbool asciiTitleContains(const std::string& filename, const std::string& needle) {\n  size_t titleBytes = filename.size();\n  if (titleBytes >= 4 && filename.compare(titleBytes - 4, 4, ".txt") == 0) titleBytes -= 4;\n  if (needle.empty()) return true;\n  if (needle.size() > titleBytes) return false;\n  const auto fold = [](const unsigned char c) {\n    return static_cast<unsigned char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);\n  };\n  for (size_t start = 0; start + needle.size() <= titleBytes; ++start) {\n    bool match = true;\n    for (size_t i = 0; i < needle.size(); ++i) {\n      if (fold(static_cast<unsigned char>(filename[start + i])) != static_cast<unsigned char>(needle[i])) {\n        match = false;\n        break;\n      }\n    }\n    if (match) return true;\n  }\n  return false;\n}\n''',
    "Notes allocation-free title search",
)

crypto_start = "bool isEncryptedPayload(const uint8_t* data, const size_t size) {\n"
crypto_end = "bool noteFileIsEncrypted(const std::string& path) {\n"
new_crypto = r'''bool writeRawNoteFile(const std::string& path, const uint8_t* data, const size_t size) {
  FsFile file = Storage.open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const size_t written = size == 0 ? 0 : file.write(data, size);
  file.close();
  return written == size;
}

bool loadNvsVaultKey(std::array<uint8_t, kCryptoKeyBytes>& key) {
  nvs_handle_t handle = 0;
  if (nvs_open(kVaultNvsNamespace, NVS_READONLY, &handle) != ESP_OK) return false;
  size_t length = key.size();
  const esp_err_t rc = nvs_get_blob(handle, kVaultNvsKey, key.data(), &length);
  nvs_close(handle);
  if (rc != ESP_OK || length != key.size()) {
    std::fill(key.begin(), key.end(), 0);
    return false;
  }
  return true;
}

bool storeNvsVaultKey(const std::array<uint8_t, kCryptoKeyBytes>& key) {
  nvs_handle_t handle = 0;
  if (nvs_open(kVaultNvsNamespace, NVS_READWRITE, &handle) != ESP_OK) return false;
  esp_err_t rc = nvs_set_blob(handle, kVaultNvsKey, key.data(), key.size());
  if (rc == ESP_OK) rc = nvs_commit(handle);
  nvs_close(handle);
  return rc == ESP_OK;
}

bool clearNvsVaultKey() {
  nvs_handle_t handle = 0;
  const esp_err_t openRc = nvs_open(kVaultNvsNamespace, NVS_READWRITE, &handle);
  if (openRc == ESP_ERR_NVS_NOT_FOUND) return true;
  if (openRc != ESP_OK) return false;
  esp_err_t rc = nvs_erase_key(handle, kVaultNvsKey);
  if (rc == ESP_ERR_NVS_NOT_FOUND) rc = ESP_OK;
  if (rc == ESP_OK) rc = nvs_commit(handle);
  nvs_close(handle);
  return rc == ESP_OK;
}

bool writeVaultKeyBackup(const std::string& pattern,
                         const std::array<uint8_t, kCryptoKeyBytes>& vaultKey) {
  std::array<uint8_t, kCryptoKeyBytes> wrappingKey{};
  if (!deriveVaultKey(pattern, wrappingKey)) return false;
  constexpr size_t backupBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes + kCryptoKeyBytes;
  std::array<uint8_t, backupBytes> payload{};
  memcpy(payload.data(), kVaultKeyBackupMagic, kCryptoMagicBytes);
  uint8_t* nonce = payload.data() + kCryptoMagicBytes;
  esp_fill_random(nonce, kCryptoNonceBytes);
  uint8_t* tag = nonce + kCryptoNonceBytes;
  uint8_t* cipher = tag + kCryptoTagBytes;
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, wrappingKey.data(), wrappingKey.size() * 8);
  if (rc == 0) {
    rc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, vaultKey.size(), nonce, kCryptoNonceBytes,
                                   payload.data(), kCryptoMagicBytes + kCryptoNonceBytes, vaultKey.data(), cipher,
                                   kCryptoTagBytes, tag);
  }
  mbedtls_gcm_free(&gcm);
  std::fill(wrappingKey.begin(), wrappingKey.end(), 0);
  if (rc != 0) return false;
  return writeRawNoteFile(kVaultKeyBackupPath, payload.data(), payload.size());
}

bool readVaultKeyBackup(const std::string& pattern, std::array<uint8_t, kCryptoKeyBytes>& vaultKey) {
  constexpr size_t backupBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes + kCryptoKeyBytes;
  FsFile file;
  if (!Storage.openFileForRead("NOTES", kVaultKeyBackupPath, file)) return false;
  if (file.size() != backupBytes) {
    file.close();
    return false;
  }
  std::array<uint8_t, backupBytes> payload{};
  const int count = file.read(payload.data(), payload.size());
  file.close();
  if (count != static_cast<int>(payload.size()) || memcmp(payload.data(), kVaultKeyBackupMagic, kCryptoMagicBytes) != 0)
    return false;
  std::array<uint8_t, kCryptoKeyBytes> wrappingKey{};
  if (!deriveVaultKey(pattern, wrappingKey)) return false;
  const uint8_t* nonce = payload.data() + kCryptoMagicBytes;
  const uint8_t* tag = nonce + kCryptoNonceBytes;
  const uint8_t* cipher = tag + kCryptoTagBytes;
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, wrappingKey.data(), wrappingKey.size() * 8);
  if (rc == 0) {
    rc = mbedtls_gcm_auth_decrypt(&gcm, vaultKey.size(), nonce, kCryptoNonceBytes, payload.data(),
                                  kCryptoMagicBytes + kCryptoNonceBytes, tag, kCryptoTagBytes, cipher, vaultKey.data());
  }
  mbedtls_gcm_free(&gcm);
  std::fill(wrappingKey.begin(), wrappingKey.end(), 0);
  if (rc != 0) {
    std::fill(vaultKey.begin(), vaultKey.end(), 0);
    return false;
  }
  return true;
}

bool ensureDeviceVaultKey(const std::string& pattern, const bool allowCreate,
                          std::array<uint8_t, kCryptoKeyBytes>& vaultKey) {
  const bool validPattern = pattern.size() == kPatternLength || pattern.size() == kLegacyPatternLength;
  if (loadNvsVaultKey(vaultKey)) {
    if (validPattern && !Storage.exists(kVaultKeyBackupPath) && !writeVaultKeyBackup(pattern, vaultKey)) {
      std::fill(vaultKey.begin(), vaultKey.end(), 0);
      return false;
    }
    return true;
  }
  if (Storage.exists(kVaultKeyBackupPath)) {
    if (!validPattern || !readVaultKeyBackup(pattern, vaultKey)) return false;
    if (!storeNvsVaultKey(vaultKey)) {
      std::fill(vaultKey.begin(), vaultKey.end(), 0);
      return false;
    }
    return true;
  }
  if (!allowCreate) return false;
  esp_fill_random(vaultKey.data(), vaultKey.size());
  if (!storeNvsVaultKey(vaultKey)) {
    std::fill(vaultKey.begin(), vaultKey.end(), 0);
    return false;
  }
  if (validPattern && !writeVaultKeyBackup(pattern, vaultKey)) {
    clearNvsVaultKey();
    std::fill(vaultKey.begin(), vaultKey.end(), 0);
    return false;
  }
  return true;
}

bool rewrapDeviceVaultKey(const std::string& pattern) {
  std::array<uint8_t, kCryptoKeyBytes> vaultKey{};
  if (!ensureDeviceVaultKey(pattern, true, vaultKey)) return false;
  const bool ok = writeVaultKeyBackup(pattern, vaultKey);
  std::fill(vaultKey.begin(), vaultKey.end(), 0);
  return ok;
}

bool saveEncryptedNoteFile(const std::string& path, const std::string& text, const std::string& pattern) {
  if (text.size() > kMaxEncryptedPlaintextBytes) return false;
  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!ensureDeviceVaultKey(pattern, true, key)) return false;
  std::array<uint8_t, kCryptoNonceBytes> nonce{};
  esp_fill_random(nonce.data(), nonce.size());
  const size_t headerBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes;
  std::vector<uint8_t> payload(headerBytes + text.size());
  memcpy(payload.data(), kCryptoMagicV2, kCryptoMagicBytes);
  memcpy(payload.data() + kCryptoMagicBytes, nonce.data(), nonce.size());
  uint8_t* tag = payload.data() + kCryptoMagicBytes + kCryptoNonceBytes;
  uint8_t* cipher = payload.data() + headerBytes;
  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key.data(), key.size() * 8);
  if (rc == 0) {
    rc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, text.size(), nonce.data(), nonce.size(),
                                   payload.data(), kCryptoMagicBytes + kCryptoNonceBytes,
                                   reinterpret_cast<const uint8_t*>(text.data()), cipher, kCryptoTagBytes, tag);
  }
  mbedtls_gcm_free(&gcm);
  std::fill(key.begin(), key.end(), 0);
  if (rc != 0) return false;
  return writeRawNoteFile(path, payload.data(), payload.size());
}

bool loadProtectedNoteFile(const std::string& path, const std::string& pattern, std::string& text) {
  text.clear();
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  const uint32_t size = file.size();
  const size_t headerBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes;
  if (size > kMaxEncryptedPlaintextBytes + headerBytes) {
    file.close();
    return false;
  }
  std::array<uint8_t, kCryptoMagicBytes> magic{};
  if (size < headerBytes || file.read(magic.data(), magic.size()) != static_cast<int>(magic.size())) {
    file.close();
    if (size > kMaxEncryptedPlaintextBytes || !Storage.openFileForRead("NOTES", path, file)) return false;
    text.resize(size);
    const bool ok = size == 0 || file.read(reinterpret_cast<uint8_t*>(text.data()), size) == static_cast<int>(size);
    file.close();
    if (!ok) text.clear();
    return ok;
  }
  const bool isV1 = memcmp(magic.data(), kCryptoMagicV1, kCryptoMagicBytes) == 0;
  const bool isV2 = memcmp(magic.data(), kCryptoMagicV2, kCryptoMagicBytes) == 0;
  if (!isV1 && !isV2) {
    file.close();
    if (size > kMaxEncryptedPlaintextBytes || !Storage.openFileForRead("NOTES", path, file)) return false;
    text.resize(size);
    const bool ok = size == 0 || file.read(reinterpret_cast<uint8_t*>(text.data()), size) == static_cast<int>(size);
    file.close();
    if (!ok) text.clear();
    return ok;
  }
  std::array<uint8_t, kCryptoNonceBytes> nonce{};
  std::array<uint8_t, kCryptoTagBytes> storedTag{};
  if (file.read(nonce.data(), nonce.size()) != static_cast<int>(nonce.size()) ||
      file.read(storedTag.data(), storedTag.size()) != static_cast<int>(storedTag.size())) {
    file.close();
    return false;
  }
  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (isV1) {
    if (!deriveVaultKey(pattern, key)) {
      file.close();
      return false;
    }
  } else if (!ensureDeviceVaultKey(pattern, false, key)) {
    file.close();
    return false;
  }
  std::array<uint8_t, kCryptoMagicBytes + kCryptoNonceBytes> aad{};
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
core = replace_section(core, crypto_start, crypto_end, new_crypto, "Notes crypto/key storage rewrite")

core = replace_section(
    core,
    "bool noteFileIsEncrypted(const std::string& path) {\n",
    "bool purgeProtectedVaultNotes() {\n",
    r'''bool noteFileIsEncrypted(const std::string& path) {
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  if (file.size() < kCryptoMagicBytes) {
    file.close();
    return false;
  }
  std::array<uint8_t, kCryptoMagicBytes> magic{};
  const int count = file.read(magic.data(), magic.size());
  file.close();
  return count == static_cast<int>(magic.size()) &&
         (memcmp(magic.data(), kCryptoMagicV1, kCryptoMagicBytes) == 0 ||
          memcmp(magic.data(), kCryptoMagicV2, kCryptoMagicBytes) == 0);
}

''',
    "Notes encrypted payload detection",
)

core = replace_once(
    core,
    '''  if (Storage.exists(kVaultFingerprintPath) && !Storage.remove(kVaultFingerprintPath)) {\n    LOG_ERR("NOTES", "Failed to remove Notes vault fingerprint");\n    return false;\n  }\n  return true;\n}\n''',
    '''  if (Storage.exists(kVaultFingerprintPath) && !Storage.remove(kVaultFingerprintPath)) {\n    LOG_ERR("NOTES", "Failed to remove Notes vault fingerprint");\n    return false;\n  }\n  if (Storage.exists(kVaultKeyBackupPath) && !Storage.remove(kVaultKeyBackupPath)) {\n    LOG_ERR("NOTES", "Failed to remove Notes vault key backup");\n    return false;\n  }\n  if (!clearNvsVaultKey()) {\n    LOG_ERR("NOTES", "Failed to clear Notes vault key from NVS");\n    return false;\n  }\n  return true;\n}\n''',
    "Notes vault reset key cleanup",
)

core = replace_section(
    core,
    "  bool hasSessionPattern() const {\n",
    "\n  }\n};\n}  // namespace",
    r'''  bool lockWithPattern(const std::string& pattern) {
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
    if (!pattern.empty()) vaultPattern = pattern;
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
    uint64_t expectedFingerprint = 0;
    const bool hasVault = readVaultFingerprint(expectedFingerprint);
    if (hasVault) {
      lockWithPattern(vaultPattern);
      return;
    }
    startActivityForResult(
        std::make_unique<VaultPatternActivity>(renderer, mappedInput, false, 0),
        [this](const ActivityResult& result) {
          if (result.isCancelled) {
            requestUpdate();
            return;
          }
          const auto* pattern = std::get_if<KeyboardResult>(&result.data);
          if (!pattern || pattern->text.size() != kPatternLength) {
            requestUpdate();
            return;
          }
          if (!writeVaultFingerprint(patternFingerprint(pattern->text))) {
            LOG_ERR("NOTES", "Failed to save Notes vault fingerprint");
            requestUpdate();
            return;
          }
          lockWithPattern(pattern->text);
        });''',
    "Notes passwordless lock flow",
)

core = replace_once(
    core,
    '''  for (size_t i = 0; i < notes.size(); ++i) {\n    const auto& filename = notes[i];\n    if (!vaultMode && noteLockedByFilename(filename)) continue;\n    bool matches = searchQuery.empty() || lowerAscii(displayName(filename)).find(needle) != std::string::npos;\n    if (!matches) matches = noteContains(std::string(kNotesDir) + "/" + filename, needle);\n    if (matches) filteredNotes.push_back(i);\n  }\n''',
    '''  for (size_t i = 0; i < notes.size(); ++i) {\n    const auto& filename = notes[i];\n    const bool locked = noteLockedByFilename(filename);\n    if (!vaultMode && locked) continue;\n    bool matches = asciiTitleContains(filename, needle);\n    if (!matches) matches = noteContains(std::string(kNotesDir) + "/" + filename, needle, locked);\n    if (matches) filteredNotes.push_back(i);\n  }\n''',
    "Notes filter SD/allocation optimization",
)

core = replace_once(
    core,
    '''bool NotesActivity::noteContains(const std::string& path, const std::string& needle) const {\n  if (needle.empty()) return true;\n  if (noteLockedByPath(path)) {\n''',
    '''bool NotesActivity::noteContains(const std::string& path, const std::string& needle, const bool locked) const {\n  if (needle.empty()) return true;\n  if (locked) {\n''',
    "Notes search cached lock state",
)

core = replace_once(
    core,
    '''        reloadNotes();\n        if (pattern->text.size() == kLegacyPatternLength) {\n''',
    '''        reloadNotes();\n        {\n          std::array<uint8_t, kCryptoKeyBytes> vaultKey{};\n          if (!ensureDeviceVaultKey(pattern->text, true, vaultKey)) {\n            LOG_ERR("NOTES", "Failed to initialize/restore Notes vault key");\n            requestUpdate();\n            return;\n          }\n          std::fill(vaultKey.begin(), vaultKey.end(), 0);\n        }\n        if (pattern->text.size() == kLegacyPatternLength) {\n''',
    "Notes restore vault key after authentication",
)

core = replace_once(
    core,
    '''                if (!writeVaultFingerprint(patternFingerprint(newPattern->text))) {\n                  LOG_ERR("NOTES", "Failed to upgrade Notes vault fingerprint");\n                  requestUpdate();\n                  return;\n                }\n                vaultPattern = newPattern->text;\n''',
    '''                if (!writeVaultFingerprint(patternFingerprint(newPattern->text))) {\n                  LOG_ERR("NOTES", "Failed to upgrade Notes vault fingerprint");\n                  requestUpdate();\n                  return;\n                }\n                if (!rewrapDeviceVaultKey(newPattern->text)) {\n                  LOG_ERR("NOTES", "Failed to rewrap Notes vault key after code upgrade");\n                  requestUpdate();\n                  return;\n                }\n                vaultPattern = newPattern->text;\n''',
    "Notes rewrap vault key on legacy code upgrade",
)

core = replace_once(
    core,
    '''                if (!writeVaultFingerprint(patternFingerprint(newCode->text))) {\n                  LOG_ERR("NOTES", "Failed to save reset Notes vault fingerprint");\n                }\n                requestUpdate();\n''',
    '''                if (!writeVaultFingerprint(patternFingerprint(newCode->text))) {\n                  LOG_ERR("NOTES", "Failed to save reset Notes vault fingerprint");\n                  requestUpdate();\n                  return;\n                }\n                std::array<uint8_t, kCryptoKeyBytes> vaultKey{};\n                if (!ensureDeviceVaultKey(newCode->text, true, vaultKey)) {\n                  LOG_ERR("NOTES", "Failed to initialize reset Notes vault key");\n                }\n                std::fill(vaultKey.begin(), vaultKey.end(), 0);\n                requestUpdate();\n''',
    "Notes initialize vault key after reset",
)

core_path.write_text(core)

notes_h_path = Path("src/activities/home/NotesActivity.h")
notes_h = notes_h_path.read_text()
notes_h = replace_once(notes_h,
                       "  bool noteContains(const std::string& path, const std::string& needle) const;\n",
                       "  bool noteContains(const std::string& path, const std::string& needle, bool locked) const;\n",
                       "Notes search signature")
notes_h_path.write_text(notes_h)

# Minesweeper: shave persistent/stack RAM and reduce redundant SD writes.
mine_h_path = Path("src/activities/home/MinesweeperActivity.h")
mine_h = mine_h_path.read_text()
mine_h = replace_once(
    mine_h,
    '''  int gridSizeIndex_ = 0;\n  int savedGridSizeIndex_ = 0;\n  std::array<char, 48> continueLabel_{};\n  int visibleRows_ = 1;\n''',
    '''  int gridSizeIndex_ = 0;\n  uint8_t savedGridSizeIndex_ = 0;\n  std::array<char, 32> continueLabel_{};\n  int visibleRows_ = 1;\n''',
    "Minesweeper compact saved-grid menu state",
)
mine_h_path.write_text(mine_h)

mine_path = Path("src/activities/home/MinesweeperActivity.cpp")
mine = mine_path.read_text()
mine = mine.replace("savedGridSizeIndex_ = gridSizeIndex_;", "savedGridSizeIndex_ = static_cast<uint8_t>(gridSizeIndex_);")
mine = mine.replace("std::clamp(savedGridSizeIndex_, 0, kGridOptionCount - 1)",
                    "std::clamp(static_cast<int>(savedGridSizeIndex_), 0, kGridOptionCount - 1)")

mine = replace_section(
    mine,
    "void MinesweeperActivity::revealFlood(const int startIndex) {\n",
    "void MinesweeperActivity::toggleFlag(const int index) {\n",
    r'''void MinesweeperActivity::revealFlood(const int startIndex) {
  std::array<uint8_t, kMaxCells> queue{};
  const int dimension = gridDimension();
  const int cellCount = dimension * dimension;
  if (startIndex < 0 || startIndex >= cellCount || revealed_[startIndex] || flagged_[startIndex] || mines_[startIndex])
    return;
  int head = 0;
  int tail = 0;
  revealed_[startIndex] = 1;
  ++revealedSafeCells_;
  queue[tail++] = static_cast<uint8_t>(startIndex);
  while (head < tail) {
    const int index = queue[head++];
    if (adjacentMineCount(index) != 0) continue;
    const int row = index / dimension;
    const int col = index % dimension;
    for (int dr = -1; dr <= 1; ++dr) {
      for (int dc = -1; dc <= 1; ++dc) {
        if (dr == 0 && dc == 0) continue;
        const int nr = row + dr;
        const int nc = col + dc;
        if (nr < 0 || nr >= dimension || nc < 0 || nc >= dimension) continue;
        const int next = nr * dimension + nc;
        if (!revealed_[next] && !flagged_[next] && !mines_[next] && tail < kMaxCells) {
          revealed_[next] = 1;
          ++revealedSafeCells_;
          queue[tail++] = static_cast<uint8_t>(next);
        }
      }
    }
  }
}

''',
    "Minesweeper flood-fill RAM optimization",
)

mine = replace_once(
    mine,
    '''  flagged_[index] = flagged_[index] ? 0 : 1;\n  saveGame();\n  flushBestScores();\n}\n''',
    '''  flagged_[index] = flagged_[index] ? 0 : 1;\n  // The game save already contains officialScore; loadSavedGame() restores it\n  // through updateBestScore(), so a second score-file write per flag is redundant.\n  saveGame();\n}\n''',
    "Minesweeper avoid duplicate score write on flag",
)

mine_path.write_text(mine)
print("Applied Notes/Minesweeper performance, RAM, and passwordless-lock optimizations.")
