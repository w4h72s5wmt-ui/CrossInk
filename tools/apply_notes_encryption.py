from pathlib import Path
import re


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    p.write_text(text.replace(old, new, 1))


# NotesActivity state: keep the verified vault pattern only while the activity is open.
replace_once(
    "src/activities/home/NotesActivity.h",
    "  bool vaultMode = false;\n  uint8_t vaultSequencePos = 0;\n\n  void reloadNotes();\n",
    "  bool vaultMode = false;\n  uint8_t vaultSequencePos = 0;\n  std::string vaultPattern;\n\n  void reloadNotes();\n",
    "vault pattern state",
)
replace_once(
    "src/activities/home/NotesActivity.h",
    "  bool handleVaultSequenceStep(bool next);\n  void promptVaultAccess();\n",
    "  bool handleVaultSequenceStep(bool next);\n  void promptVaultAccess();\n  void migrateLockedNotes();\n",
    "migration declaration",
)

notes = Path("src/activities/home/NotesActivity.cpp")
text = notes.read_text()

# Crypto is already part of the ESP32 framework; no external library is added.
text = text.replace(
    '#include <I18n.h>\n\n#include <algorithm>\n',
    '#include <I18n.h>\n#include <esp_random.h>\n#include <mbedtls/gcm.h>\n#include <mbedtls/sha256.h>\n\n#include <algorithm>\n',
    1,
)
text = text.replace(
    '#include <cstdint>\n#include <memory>\n',
    '#include <cstdint>\n#include <cstring>\n#include <memory>\n#include <vector>\n',
    1,
)
text = text.replace(
    'constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\n',
    'constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\n'
    'constexpr size_t kCryptoMagicBytes = 8;\n'
    'constexpr size_t kCryptoNonceBytes = 12;\n'
    'constexpr size_t kCryptoTagBytes = 16;\n'
    'constexpr size_t kCryptoKeyBytes = 32;\n'
    'constexpr uint8_t kCryptoMagic[kCryptoMagicBytes] = {\'C\', \'R\', \'O\', \'S\', \'S\', \'N\', \'T\', \'1\'};\n',
    1,
)

crypto_helpers = r'''
bool deriveVaultKey(const std::string& pattern, std::array<uint8_t, kCryptoKeyBytes>& key) {
  if (pattern.size() != kPatternLength) return false;
  static constexpr char domain[] = "CrossInk Notes AES-256-GCM v1";
  std::array<uint8_t, sizeof(domain) - 1 + kPatternLength> seed{};
  memcpy(seed.data(), domain, sizeof(domain) - 1);
  memcpy(seed.data() + sizeof(domain) - 1, pattern.data(), kPatternLength);
  return mbedtls_sha256(seed.data(), seed.size(), key.data(), 0) == 0;
}

bool isEncryptedPayload(const uint8_t* data, const size_t size) {
  return size >= kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes &&
         memcmp(data, kCryptoMagic, kCryptoMagicBytes) == 0;
}

bool readRawNoteFile(const std::string& path, std::vector<uint8_t>& bytes) {
  bytes.clear();
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  const uint32_t size = file.size();
  if (size > NotesActivity::kMaxNoteBytes + kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes) {
    file.close();
    return false;
  }
  bytes.resize(size);
  if (size > 0 && file.read(bytes.data(), size) != static_cast<int>(size)) {
    file.close();
    bytes.clear();
    return false;
  }
  file.close();
  return true;
}

bool writeRawNoteFile(const std::string& path, const uint8_t* data, const size_t size) {
  FsFile file = Storage.open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const size_t written = size == 0 ? 0 : file.write(data, size);
  file.close();
  return written == size;
}

bool saveEncryptedNoteFile(const std::string& path, const std::string& text, const std::string& pattern) {
  if (text.size() > NotesActivity::kMaxNoteBytes) return false;
  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!deriveVaultKey(pattern, key)) return false;

  std::array<uint8_t, kCryptoNonceBytes> nonce{};
  esp_fill_random(nonce.data(), nonce.size());

  const size_t headerBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes;
  std::vector<uint8_t> payload(headerBytes + text.size());
  memcpy(payload.data(), kCryptoMagic, kCryptoMagicBytes);
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
  std::vector<uint8_t> payload;
  if (!readRawNoteFile(path, payload)) return false;

  if (!isEncryptedPayload(payload.data(), payload.size())) {
    text.assign(reinterpret_cast<const char*>(payload.data()), payload.size());
    return text.size() <= NotesActivity::kMaxNoteBytes;
  }

  const size_t headerBytes = kCryptoMagicBytes + kCryptoNonceBytes + kCryptoTagBytes;
  const size_t cipherBytes = payload.size() - headerBytes;
  if (cipherBytes > NotesActivity::kMaxNoteBytes) return false;

  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!deriveVaultKey(pattern, key)) return false;
  const uint8_t* nonce = payload.data() + kCryptoMagicBytes;
  const uint8_t* tag = nonce + kCryptoNonceBytes;
  const uint8_t* cipher = tag + kCryptoTagBytes;
  text.resize(cipherBytes);

  mbedtls_gcm_context gcm;
  mbedtls_gcm_init(&gcm);
  int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key.data(), key.size() * 8);
  if (rc == 0) {
    rc = mbedtls_gcm_auth_decrypt(&gcm, cipherBytes, nonce, kCryptoNonceBytes, payload.data(),
                                  kCryptoMagicBytes + kCryptoNonceBytes, tag, kCryptoTagBytes, cipher,
                                  reinterpret_cast<uint8_t*>(text.data()));
  }
  mbedtls_gcm_free(&gcm);
  std::fill(key.begin(), key.end(), 0);
  if (rc != 0) {
    text.clear();
    return false;
  }
  return true;
}

bool noteFileIsEncrypted(const std::string& path) {
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

anchor = 'bool saveNoteFile(const std::string& path, const std::string& text) {\n'
if text.count(anchor) != 1:
    raise SystemExit("saveNoteFile anchor mismatch")
text = text.replace(anchor, crypto_helpers + anchor, 1)

# Notes editor: encrypted autosave when the note is locked; retain the verified pattern in-memory.
text = text.replace(
    '                        std::string initialText, const size_t maxLength, std::string path)\n'
    '      : KeyboardEntryActivity(renderer, mappedInput, std::move(title), std::move(initialText), maxLength,\n'
    '                              InputType::Multiline),\n'
    '        path(std::move(path)) {}\n',
    '                        std::string initialText, const size_t maxLength, std::string path, std::string vaultPattern)\n'
    '      : KeyboardEntryActivity(renderer, mappedInput, std::move(title), std::move(initialText), maxLength,\n'
    '                              InputType::Multiline),\n'
    '        path(std::move(path)), vaultPattern(std::move(vaultPattern)) {}\n',
    1,
)
text = text.replace(
    '  void onExit() override {\n'
    '    if (!saveNoteFile(path, currentText())) {\n'
    '      LOG_ERR("NOTES", "Failed to autosave note before editor exit: %s", path.c_str());\n'
    '    }\n'
    '    KeyboardEntryActivity::onExit();\n'
    '  }\n',
    '  void onExit() override {\n'
    '    const bool saved = noteLockedByPath(path) ? saveEncryptedNoteFile(path, currentText(), vaultPattern)\n'
    '                                               : saveNoteFile(path, currentText());\n'
    '    if (!saved) LOG_ERR("NOTES", "Failed to autosave note before editor exit: %s", path.c_str());\n'
    '    std::fill(vaultPattern.begin(), vaultPattern.end(), \'\\0\');\n'
    '    vaultPattern.clear();\n'
    '    KeyboardEntryActivity::onExit();\n'
    '  }\n',
    1,
)
text = text.replace(
    ' private:\n  std::string path;\n\n  Rect lockButtonRect() const {\n',
    ' private:\n  std::string path;\n  std::string vaultPattern;\n\n  Rect lockButtonRect() const {\n',
    1,
)
old_lock = '''          if (!hasVault && !writeVaultFingerprint(patternFingerprint(pattern->text))) {
            LOG_ERR("NOTES", "Failed to save Notes vault fingerprint");
            requestUpdate();
            return;
          }
          if (!createLockMarker(path)) {
            LOG_ERR("NOTES", "Failed to lock note: %s", path.c_str());
            requestUpdate();
            return;
          }
          finish();
'''
new_lock = '''          if (!hasVault && !writeVaultFingerprint(patternFingerprint(pattern->text))) {
            LOG_ERR("NOTES", "Failed to save Notes vault fingerprint");
            requestUpdate();
            return;
          }
          if (!saveEncryptedNoteFile(path, currentText(), pattern->text)) {
            LOG_ERR("NOTES", "Failed to encrypt note: %s", path.c_str());
            requestUpdate();
            return;
          }
          if (!createLockMarker(path)) {
            saveNoteFile(path, currentText());
            LOG_ERR("NOTES", "Failed to lock note: %s", path.c_str());
            requestUpdate();
            return;
          }
          vaultPattern = pattern->text;
          finish();
'''
if text.count(old_lock) != 1:
    raise SystemExit("lock conversion anchor mismatch")
text = text.replace(old_lock, new_lock, 1)

# Forget the decryption material whenever Notes closes.
text = text.replace(
    'void NotesActivity::onExit() {\n  filteredNotes.clear();\n  notes.clear();\n  Activity::onExit();\n}\n',
    'void NotesActivity::onExit() {\n  filteredNotes.clear();\n  notes.clear();\n  std::fill(vaultPattern.begin(), vaultPattern.end(), \'\\0\');\n  vaultPattern.clear();\n  vaultMode = false;\n  Activity::onExit();\n}\n',
    1,
)

# Read encrypted locked notes transparently; legacy locked notes remain readable for migration.
load_re = re.compile(r'bool NotesActivity::loadNote\(const std::string& path, std::string& text\) const \{.*?\n\}\n\nbool NotesActivity::noteContains', re.S)
load_new = r'''bool NotesActivity::loadNote(const std::string& path, std::string& text) const {
  if (noteLockedByPath(path)) return loadProtectedNoteFile(path, vaultPattern, text);
  text.clear();
  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;

  const uint32_t size = file.size();
  if (size > kMaxNoteBytes) {
    file.close();
    return false;
  }

  text.resize(size);
  if (size > 0 && file.read(text.data(), size) != static_cast<int>(size)) {
    file.close();
    text.clear();
    return false;
  }
  file.close();
  return true;
}

bool NotesActivity::noteContains'''
text, n = load_re.subn(load_new, text, count=1)
if n != 1:
    raise SystemExit(f"loadNote replacement count={n}")

# Search locked notes after decrypting them in memory. Normal notes retain the streaming search path.
needle = '''bool NotesActivity::noteContains(const std::string& path, const std::string& needle) const {
  if (needle.empty()) return true;
  constexpr size_t kSearchBufferSize = 512;
'''
replacement = '''bool NotesActivity::noteContains(const std::string& path, const std::string& needle) const {
  if (needle.empty()) return true;
  if (noteLockedByPath(path)) {
    std::string plain;
    if (!loadNote(path, plain)) return false;
    return lowerAscii(std::move(plain)).find(needle) != std::string::npos;
  }
  constexpr size_t kSearchBufferSize = 512;
'''
if text.count(needle) != 1:
    raise SystemExit("noteContains anchor mismatch")
text = text.replace(needle, replacement, 1)

text = text.replace(
    'bool NotesActivity::saveNote(const std::string& path, const std::string& text) const {\n'
    '  if (text.size() > kMaxNoteBytes) return false;\n'
    '  return saveNoteFile(path, text);\n'
    '}\n',
    'bool NotesActivity::saveNote(const std::string& path, const std::string& text) const {\n'
    '  if (text.size() > kMaxNoteBytes) return false;\n'
    '  if (noteLockedByPath(path)) return saveEncryptedNoteFile(path, text, vaultPattern);\n'
    '  return saveNoteFile(path, text);\n'
    '}\n',
    1,
)

text = text.replace(
    '      std::make_unique<NotesKeyboardActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes, path),\n',
    '      std::make_unique<NotesKeyboardActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes, path,\n'
    '                                              noteLockedByPath(path) ? vaultPattern : std::string{}),\n',
    1,
)

# Preserve encryption during rename instead of briefly writing plaintext.
rename_save = '''        const std::string newPath = uniquePathForTitle(keyboard->text);
        if (!saveNote(newPath, content)) {
          LOG_ERR("NOTES", "Failed to write renamed note: %s", newPath.c_str());
          requestUpdate();
          return;
        }
'''
rename_save_new = '''        const std::string newPath = uniquePathForTitle(keyboard->text);
        const bool wroteNew = wasLocked ? saveEncryptedNoteFile(newPath, content, vaultPattern) : saveNote(newPath, content);
        if (!wroteNew) {
          LOG_ERR("NOTES", "Failed to write renamed note: %s", newPath.c_str());
          requestUpdate();
          return;
        }
'''
if text.count(rename_save) != 1:
    raise SystemExit("rename save anchor mismatch")
text = text.replace(rename_save, rename_save_new, 1)

# Keep the verified pattern for the vault session, then migrate any old plaintext locked notes.
access_old = '''        vaultMode = true;
        searchQuery.clear();
        selectorIndex = 0;
        topIndex = 0;
        reloadNotes();
        applyFilter();
        requestUpdate();
'''
access_new = '''        vaultPattern = pattern->text;
        vaultMode = true;
        searchQuery.clear();
        selectorIndex = 0;
        topIndex = 0;
        reloadNotes();
        migrateLockedNotes();
        applyFilter();
        requestUpdate();
'''
if text.count(access_old) != 1:
    raise SystemExit("vault access anchor mismatch")
text = text.replace(access_old, access_new, 1)

migration = r'''
void NotesActivity::migrateLockedNotes() {
  if (vaultPattern.size() != kPatternLength) return;
  for (const auto& filename : notes) {
    const std::string path = std::string(kNotesDir) + "/" + filename;
    if (!noteLockedByPath(path) || noteFileIsEncrypted(path)) continue;
    std::string plain;
    if (!loadProtectedNoteFile(path, vaultPattern, plain)) {
      LOG_ERR("NOTES", "Failed to read legacy locked note for encryption: %s", path.c_str());
      continue;
    }
    if (!saveEncryptedNoteFile(path, plain, vaultPattern)) {
      LOG_ERR("NOTES", "Failed to migrate locked note to encrypted storage: %s", path.c_str());
    }
  }
}

'''
loop_anchor = 'void NotesActivity::loop() {\n'
if text.count(loop_anchor) != 1:
    raise SystemExit("loop anchor mismatch")
text = text.replace(loop_anchor, migration + loop_anchor, 1)

notes.write_text(text)

required = [
    'mbedtls_gcm_auth_decrypt',
    'saveEncryptedNoteFile(path, currentText(), pattern->text)',
    'vaultPattern = pattern->text;',
    'void NotesActivity::migrateLockedNotes()',
    'noteFileIsEncrypted(path)',
]
final = notes.read_text()
for item in required:
    if item not in final:
        raise SystemExit(f"missing expected encryption code: {item}")
