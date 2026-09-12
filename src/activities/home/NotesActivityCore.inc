#include "NotesActivity.h"

#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <esp_random.h>
#include <mbedtls/gcm.h>
#include <mbedtls/sha256.h>
#include <nvs.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>
#include <utility>

#include "MappedInputManager.h"
#include "activities/util/ConfirmationActivity.h"
#include "activities/util/KeyboardEntryActivity.h"
#include "components/TouchHeaderBackButton.h"
#include "components/OptionPopup.h"
#include "components/UITheme.h"
#include "components/UiAppHelpers.h"
#include "fontIds.h"

namespace {
constexpr int kTopMargin = 12;
constexpr int kControlHeight = 52;
constexpr int kControlGap = 8;
constexpr int kSideButtonWidth = 52;
constexpr int kSearchClearWidth = 44;
constexpr int kDeleteButtonWidth = 48;
constexpr int kRenameButtonWidth = 44;
constexpr int kLockButtonWidth = 48;
constexpr int kRowHeight = 58;
constexpr size_t kPatternLength = 6;
constexpr size_t kMaxEncryptedPlaintextBytes = 32 * 1024;
constexpr const char* kVaultFingerprintPath = "/Notes/.vault";
constexpr const char* kVaultKeyBackupPath = "/Notes/.vaultkey";
constexpr const char* kVaultNvsNamespace = "crossinknotes";
constexpr const char* kVaultNvsKey = "vaultkey";
constexpr const char* kResetVaultToken = "__RESET_VAULT__";
constexpr size_t kCryptoMagicBytes = 8;
constexpr size_t kCryptoNonceBytes = 12;
constexpr size_t kCryptoTagBytes = 16;
constexpr size_t kCryptoKeyBytes = 32;
constexpr size_t kCryptoChunkBytes = 512;
constexpr uint8_t kCryptoMagic[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'N', 'T', '2'};
constexpr uint8_t kVaultKeyBackupMagic[kCryptoMagicBytes] = {'C', 'R', 'O', 'S', 'S', 'V', 'K', '1'};
constexpr int kRowSidePadding = 16;
constexpr int kCornerRadius = 6;

bool pointInRect(const Rect& rect, const int x, const int y) {
  return x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

std::string lowerAscii(std::string value) {
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

bool asciiTitleContains(const std::string& filename, const std::string& needle) {
  size_t titleBytes = filename.size();
  if (titleBytes >= 4 && filename.compare(titleBytes - 4, 4, ".txt") == 0) titleBytes -= 4;
  if (needle.empty()) return true;
  if (needle.size() > titleBytes) return false;
  const auto fold = [](const unsigned char c) {
    return static_cast<unsigned char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
  };
  for (size_t start = 0; start + needle.size() <= titleBytes; ++start) {
    bool match = true;
    for (size_t i = 0; i < needle.size(); ++i) {
      if (fold(static_cast<unsigned char>(filename[start + i])) != static_cast<unsigned char>(needle[i])) {
        match = false;
        break;
      }
    }
    if (match) return true;
  }
  return false;
}

void drawCenteredLabel(GfxRenderer& renderer, const Rect& rect, const char* label) {
  const int textW = renderer.getTextWidth(UI_12_FONT_ID, label);
  const int textH = renderer.getLineHeight(UI_12_FONT_ID);
  renderer.drawText(UI_12_FONT_ID, rect.x + (rect.width - textW) / 2, rect.y + (rect.height - textH) / 2, label);
}

void drawPlusIcon(GfxRenderer& renderer, const Rect& rect) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  const int half = 10;
  renderer.fillRect(cx - half, cy - 1, half * 2 + 1, 3, true);
  renderer.fillRect(cx - 1, cy - half, 3, half * 2 + 1, true);
}

void drawSearchIcon(GfxRenderer& renderer, const Rect& rect) {
  const int size = 15;
  const int x = rect.x + std::max(0, (rect.width - size - 6) / 2);
  const int y = rect.y + std::max(0, (rect.height - size) / 2 - 2);
  renderer.drawRoundedRect(x, y, size, size, 2, size / 2, true);
  renderer.drawLine(x + size - 2, y + size - 2, x + size + 6, y + size + 6, 2, true);
}

void drawClearIcon(GfxRenderer& renderer, const Rect& rect) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  const int half = 7;
  renderer.drawLine(cx - half, cy - half, cx + half, cy + half, 2, true);
  renderer.drawLine(cx + half, cy - half, cx - half, cy + half, 2, true);
}

void drawRenameIcon(GfxRenderer& renderer, const Rect& rect, const bool black) {
  const int cx = rect.x + rect.width / 2;
  const int cy = rect.y + rect.height / 2;
  renderer.drawLine(cx - 8, cy + 8, cx + 8, cy - 8, 3, black);
  renderer.drawLine(cx - 10, cy + 10, cx - 5, cy + 9, 2, black);
  renderer.drawLine(cx + 6, cy - 10, cx + 10, cy - 6, 2, black);
  renderer.drawLine(cx - 11, cy + 11, cx - 7, cy + 7, 1, black);
}

void drawTrashIcon(GfxRenderer& renderer, const Rect& rect, const bool black) {
  const int iconWidth = 18;
  const int iconHeight = 22;
  const int x = rect.x + (rect.width - iconWidth) / 2;
  const int y = rect.y + (rect.height - iconHeight) / 2;

  renderer.drawLine(x, y + 4, x + iconWidth - 1, y + 4, 2, black);
  renderer.drawLine(x + 5, y + 1, x + iconWidth - 6, y + 1, 2, black);
  renderer.drawRect(x + 2, y + 6, iconWidth - 4, iconHeight - 6, 1, black);
  renderer.drawLine(x + 6, y + 9, x + 6, y + iconHeight - 3, 1, black);
  renderer.drawLine(x + iconWidth - 7, y + 9, x + iconWidth - 7, y + iconHeight - 3, 1, black);
}

void drawLockIcon(GfxRenderer& renderer, const Rect& rect, const bool black) {
  const int bodyW = 20;
  const int bodyH = 16;
  const int bodyX = rect.x + (rect.width - bodyW) / 2;
  const int bodyY = rect.y + rect.height / 2;
  const int shackleW = 14;
  const int shackleH = 12;
  const int shackleX = rect.x + (rect.width - shackleW) / 2;
  const int shackleY = bodyY - shackleH + 2;
  renderer.drawRoundedRect(shackleX, shackleY, shackleW, shackleH, 2, 6, black);
  renderer.fillRect(bodyX, bodyY, bodyW, bodyH, black);
  renderer.fillRect(bodyX + bodyW / 2 - 1, bodyY + 5, 3, 7, !black);
}

std::string lockMarkerPath(const std::string& notePath) { return notePath + ".lock"; }

bool noteLockedByPath(const std::string& notePath) { return Storage.exists(lockMarkerPath(notePath).c_str()); }

bool noteLockedByFilename(const std::string& filename) {
  return noteLockedByPath(std::string("/Notes") + "/" + filename);
}

bool createLockMarker(const std::string& notePath) {
  const std::string marker = lockMarkerPath(notePath);
  FsFile file = Storage.open(marker.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const uint8_t value = 1;
  const size_t written = file.write(&value, 1);
  file.close();
  return written == 1;
}

bool removeLockMarker(const std::string& notePath) {
  const std::string marker = lockMarkerPath(notePath);
  return !Storage.exists(marker.c_str()) || Storage.remove(marker.c_str());
}

uint64_t patternFingerprint(const std::string& pattern) {
  // Salted fingerprint only: this is a privacy gate, not note-content encryption.
  uint64_t hash = UINT64_C(1469598103934665603);
  static constexpr char salt[] = "CrossInk-Notes-Vault-v1";
  for (const unsigned char c : std::string(salt) + pattern) {
    hash ^= c;
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

bool readVaultFingerprint(uint64_t& fingerprint) {
  FsFile file = Storage.open(kVaultFingerprintPath, O_RDONLY);
  if (!file) return false;
  if (file.size() != sizeof(fingerprint)) {
    file.close();
    return false;
  }
  const int read = file.read(reinterpret_cast<uint8_t*>(&fingerprint), sizeof(fingerprint));
  file.close();
  return read == static_cast<int>(sizeof(fingerprint));
}

bool writeVaultFingerprint(const uint64_t fingerprint) {
  FsFile file = Storage.open(kVaultFingerprintPath, O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const size_t written = file.write(reinterpret_cast<const uint8_t*>(&fingerprint), sizeof(fingerprint));
  file.close();
  return written == sizeof(fingerprint);
}

class VaultRecoveryChoiceActivity final : public Activity {
 public:
  VaultRecoveryChoiceActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
      : Activity("NotesVaultRecovery", renderer, mappedInput) {}

  void onEnter() override {
    Activity::onEnter();
    const char* options[] = {"Continuer", "Reinitialiser"};
    popup.show("3 codes incorrects. Reinitialiser supprime les notes protegees.", options, 2, 0,
               [this](const int index) {
                 const std::string choice = index == 1 ? kResetVaultToken : "__CONTINUE_VAULT__";
                 setResult(ActivityResult{KeyboardResult{choice}});
                 finish();
               });
    popup.setPrimaryOptionIndex(0);
    requestUpdate(true);
  }

  void loop() override {
    if (popup.handleInput(mappedInput, [this] { requestUpdate(); })) return;
    setResult(ActivityResult{KeyboardResult{"__CONTINUE_VAULT__"}});
    finish();
  }

  void render(RenderLock&&) override {
    if (popup.processRender(renderer, mappedInput)) return;
  }

 private:
  OptionPopup popup;
};

class VaultPatternActivity final : public Activity {
 public:
  VaultPatternActivity(GfxRenderer& renderer, MappedInputManager& mappedInput, const bool verify,
                       const uint64_t expectedFingerprint, const bool allowResetAfterFailures = false)
      : Activity("NotesVaultPattern", renderer, mappedInput),
        verify(verify),
        expectedFingerprint(expectedFingerprint),
        allowResetAfterFailures(allowResetAfterFailures) {}

  void onEnter() override {
    Activity::onEnter();
    requestUpdate();
  }

  void loop() override {
    int tx = 0;
    int ty = 0;
    if (mappedInput.wasScreenTapped(tx, ty)) {
      for (int i = 0; i < 9; ++i) {
        if (pointInRect(cellRect(i), tx, ty)) {
          appendCell(i);
          return;
        }
      }
    }

    if (mappedInput.wasReleased(MappedInputManager::Button::Up)) {
      hardwareSelection = true;
      selectedCell = (selectedCell + 6) % 9;
      requestUpdate();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Down)) {
      hardwareSelection = true;
      selectedCell = (selectedCell + 3) % 9;
      requestUpdate();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Left)) {
      hardwareSelection = true;
      selectedCell = selectedCell % 3 == 0 ? selectedCell + 2 : selectedCell - 1;
      requestUpdate();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Right)) {
      hardwareSelection = true;
      selectedCell = selectedCell % 3 == 2 ? selectedCell - 2 : selectedCell + 1;
      requestUpdate();
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      appendCell(selectedCell);
      return;
    }
    if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
      ActivityResult cancelled;
      cancelled.isCancelled = true;
      setResult(std::move(cancelled));
      finish();
    }
  }

  void render(RenderLock&&) override {
    renderer.clearScreen();
    for (int i = 0; i < 9; ++i) {
      const Rect rect = cellRect(i);
      renderer.drawRoundedRect(rect.x, rect.y, rect.width, rect.height, 2, 8, true);
      if (hardwareSelection && i == selectedCell) {
        renderer.drawRoundedRect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8, 2, 6, true);
      }
    }
    if (invalidPattern) renderer.drawCenteredText(UI_12_FONT_ID, 12, "Code incorrect", true);
    renderer.displayBuffer();
  }

 private:
  bool verify = false;
  uint64_t expectedFingerprint = 0;
  bool allowResetAfterFailures = false;
  uint8_t failedAttempts = 0;
  std::string pattern;
  int selectedCell = 4;
  bool hardwareSelection = false;
  bool invalidPattern = false;

  Rect cellRect(const int index) const {
    constexpr int gap = 12;
    const int width = renderer.getScreenWidth();
    const int height = renderer.getScreenHeight();
    const int cell = std::max(1, std::min((width - gap * 4) / 3, (height - gap * 4) / 3));
    const int gridW = cell * 3 + gap * 2;
    const int gridH = cell * 3 + gap * 2;
    const int startX = (width - gridW) / 2;
    const int startY = (height - gridH) / 2;
    const int row = index / 3;
    const int col = index % 3;
    return Rect{startX + col * (cell + gap), startY + row * (cell + gap), cell, cell};
  }

  void appendCell(const int index) {
    invalidPattern = false;
    pattern.push_back(static_cast<char>('0' + index));
    if (pattern.size() < kPatternLength) {
      requestUpdate();
      return;
    }
    const uint64_t fingerprint = patternFingerprint(pattern);
    if (verify && fingerprint != expectedFingerprint) {
      pattern.clear();
      invalidPattern = true;
      ++failedAttempts;
      if (allowResetAfterFailures && failedAttempts >= 3) {
        failedAttempts = 0;
        invalidPattern = false;
        startActivityForResult(
            std::make_unique<VaultRecoveryChoiceActivity>(renderer, mappedInput),
            [this](const ActivityResult& result) {
              const auto* choice = std::get_if<KeyboardResult>(&result.data);
              if (!result.isCancelled && choice && choice->text == kResetVaultToken) {
                setResult(ActivityResult{KeyboardResult{std::string(kResetVaultToken)}});
                finish();
                return;
              }
              pattern.clear();
              invalidPattern = false;
              requestUpdate();
            });
        return;
      }
      requestUpdate();
      return;
    }
    setResult(ActivityResult{KeyboardResult{pattern}});
    finish();
  }
};


bool deriveVaultKey(const std::string& pattern, std::array<uint8_t, kCryptoKeyBytes>& key) {
  if (pattern.size() != kPatternLength) return false;
  static constexpr char domain[] = "CrossInk Notes AES-256-GCM v1";
  std::array<uint8_t, sizeof(domain) - 1 + kPatternLength> seed{};
  memcpy(seed.data(), domain, sizeof(domain) - 1);
  memcpy(seed.data() + sizeof(domain) - 1, pattern.data(), pattern.size());
  const size_t seedSize = sizeof(domain) - 1 + pattern.size();
  return mbedtls_sha256(seed.data(), seedSize, key.data(), 0) == 0;
}

bool writeRawNoteFile(const std::string& path, const uint8_t* data, const size_t size) {
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
  const bool validPattern = pattern.size() == kPatternLength;
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

bool saveEncryptedNoteFile(const std::string& path, const std::string& text, const std::string& pattern) {
  if (text.size() > kMaxEncryptedPlaintextBytes) return false;
  std::array<uint8_t, kCryptoKeyBytes> key{};
  if (!ensureDeviceVaultKey(pattern, true, key)) return false;

  constexpr size_t aadBytes = kCryptoMagicBytes + kCryptoNonceBytes;
  constexpr size_t headerBytes = aadBytes + kCryptoTagBytes;
  std::array<uint8_t, headerBytes> header{};
  memcpy(header.data(), kCryptoMagic, kCryptoMagicBytes);
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

bool loadProtectedNoteFile(const std::string& path, const std::string& pattern, std::string& text) {
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

bool purgeProtectedVaultNotes() {
  std::vector<std::string> protectedPaths;
  auto dir = Storage.open("/Notes");
  if (dir && dir.isDirectory()) {
    char name[256];
    for (auto file = dir.openNextFile(); file; file = dir.openNextFile()) {
      if (!file.isDirectory()) {
        file.getName(name, sizeof(name));
        const std::string filename{name};
        if (filename.size() >= 4 && filename.compare(filename.size() - 4, 4, ".txt") == 0) {
          const std::string path = std::string("/Notes/") + filename;
          if (noteLockedByPath(path) || noteFileIsEncrypted(path)) protectedPaths.push_back(path);
        }
      }
      file.close();
    }
  }
  if (dir) dir.close();

  bool success = true;
  for (const auto& path : protectedPaths) {
    if (Storage.exists(path.c_str()) && !Storage.remove(path.c_str())) {
      LOG_ERR("NOTES", "Failed to purge protected note: %s", path.c_str());
      success = false;
      continue;
    }
    removeLockMarker(path);
  }
  if (!success) return false;

  if (Storage.exists(kVaultFingerprintPath) && !Storage.remove(kVaultFingerprintPath)) {
    LOG_ERR("NOTES", "Failed to remove Notes vault fingerprint");
    return false;
  }
  if (Storage.exists(kVaultKeyBackupPath) && !Storage.remove(kVaultKeyBackupPath)) {
    LOG_ERR("NOTES", "Failed to remove Notes vault key backup");
    return false;
  }
  if (!clearNvsVaultKey()) {
    LOG_ERR("NOTES", "Failed to clear Notes vault key from NVS");
    return false;
  }
  return true;
}

bool saveNoteFile(const std::string& path, const std::string& text) {
  FsFile file = Storage.open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return false;
  const size_t written = text.empty() ? 0 : file.write(reinterpret_cast<const uint8_t*>(text.data()), text.size());
  file.close();
  return written == text.size();
}

class NotesKeyboardActivity final : public KeyboardEntryActivity {
 public:
  NotesKeyboardActivity(GfxRenderer& renderer, MappedInputManager& mappedInput, std::string title,
                        std::string initialText, const size_t maxLength, std::string path, std::string vaultPattern)
      : KeyboardEntryActivity(renderer, mappedInput, std::move(title), std::move(initialText), maxLength,
                              InputType::Multiline),
        path(std::move(path)), vaultPattern(std::move(vaultPattern)) {
    capturePersistedState();
  }

  void onExit() override {
    if (contentChanged()) {
      const bool saved = noteLockedByPath(path) ? saveEncryptedNoteFile(path, currentText(), vaultPattern)
                                                 : saveNoteFile(path, currentText());
      if (!saved) {
        LOG_ERR("NOTES", "Failed to autosave note before editor exit: %s", path.c_str());
      } else {
        capturePersistedState();
      }
    }
    std::fill(vaultPattern.begin(), vaultPattern.end(), '\0');
    vaultPattern.clear();
    KeyboardEntryActivity::onExit();
  }

 protected:
  bool handleHeaderActionTap(const int x, const int y) override {
    if (!pointInRect(lockButtonRect(), x, y)) return false;
    if (noteLockedByPath(path)) {
      beginUnlock();
    } else {
      beginLock();
    }
    return true;
  }

  int headerActionReserveWidth() const override { return kLockButtonWidth; }

  bool headerActionLocked() const override { return noteLockedByPath(path); }

  void drawHeaderAction() override {
    drawLockIcon(renderer, lockArtworkRectOnTitleBaseline(lockButtonRect()), true);
  }

 private:
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
    if (!pattern.empty()) vaultPattern = pattern;
    capturePersistedState();
    requestUpdate(true);
    return true;
  }

  void beginUnlock() {
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
    capturePersistedState();
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
        });
  }
};
}  // namespace

NotesActivity::NotesActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
    : Activity("Notes", renderer, mappedInput) {}

void NotesActivity::onEnter() {
  Activity::onEnter();
  Storage.mkdir(kNotesDir);
  reloadNotes();
  applyFilter();
  selectorIndex = 0;
  topIndex = 0;
  requestUpdate();
}

void NotesActivity::onExit() {
  filteredNotes.clear();
  noteLockedStates.clear();
  notes.clear();
  std::fill(vaultPattern.begin(), vaultPattern.end(), '\0');
  vaultPattern.clear();
  vaultMode = false;
  Activity::onExit();
}

void NotesActivity::reloadNotes() {
  notes.clear();
  noteLockedStates.clear();
  auto dir = Storage.open(kNotesDir);
  if (!dir || !dir.isDirectory()) {
    if (dir) dir.close();
    return;
  }

  char name[256];
  for (auto file = dir.openNextFile(); file; file = dir.openNextFile()) {
    if (!file.isDirectory()) {
      file.getName(name, sizeof(name));
      const std::string filename{name};
      if (filename.size() >= 4 && filename.compare(filename.size() - 4, 4, ".txt") == 0) {
        notes.push_back(filename);
      }
    }
    file.close();
  }
  dir.close();
  std::sort(notes.begin(), notes.end());
  noteLockedStates.reserve(notes.size());
  for (const auto& filename : notes) {
    noteLockedStates.push_back(noteLockedByFilename(filename) ? 1u : 0u);
  }
}

void NotesActivity::applyFilter() {
  filteredNotes.clear();
  filteredNotes.reserve(notes.size());
  const std::string needle = lowerAscii(searchQuery);
  for (size_t i = 0; i < notes.size(); ++i) {
    const auto& filename = notes[i];
    const bool locked = i < noteLockedStates.size() && noteLockedStates[i] != 0;
    if (!vaultMode && locked) continue;
    bool matches = asciiTitleContains(filename, needle);
    if (!matches) matches = noteContains(std::string(kNotesDir) + "/" + filename, needle, locked);
    if (matches) filteredNotes.push_back(i);
  }

  if (filteredNotes.empty()) {
    selectorIndex = 0;
    topIndex = 0;
  } else {
    selectorIndex = std::clamp(selectorIndex, 0, static_cast<int>(filteredNotes.size()) - 1);
    topIndex = std::clamp(topIndex, 0, selectorIndex);
  }
}

std::string NotesActivity::displayName(const std::string& filename) {
  if (filename.size() > 4 && filename.compare(filename.size() - 4, 4, ".txt") == 0) {
    return filename.substr(0, filename.size() - 4);
  }
  return filename;
}

std::string NotesActivity::sanitizeFilename(const std::string& title) {
  std::string out;
  out.reserve(std::min<size_t>(title.size(), 48));
  for (const unsigned char c : title) {
    if (out.size() >= 48) break;
    if (c < 0x20 || c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' || c == '"' || c == '<' ||
        c == '>' || c == '|') {
      out.push_back('_');
    } else {
      out.push_back(static_cast<char>(c));
    }
  }
  while (!out.empty() && (out.back() == ' ' || out.back() == '.')) out.pop_back();
  if (out.empty()) out = "Note";
  return out;
}

std::string NotesActivity::uniquePathForTitle(const std::string& title) const {
  const std::string base = sanitizeFilename(title);
  std::string path = std::string(kNotesDir) + "/" + base + ".txt";
  if (!Storage.exists(path.c_str())) return path;

  for (int suffix = 2; suffix < 1000; ++suffix) {
    path = std::string(kNotesDir) + "/" + base + " " + std::to_string(suffix) + ".txt";
    if (!Storage.exists(path.c_str())) return path;
  }
  return std::string(kNotesDir) + "/Note.txt";
}

bool NotesActivity::loadNote(const std::string& path, std::string& text) const {
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

bool NotesActivity::noteContains(const std::string& path, const std::string& needle, const bool locked) const {
  if (needle.empty()) return true;
  if (locked) {
    std::string plain;
    if (!loadNote(path, plain)) return false;
    return lowerAscii(std::move(plain)).find(needle) != std::string::npos;
  }
  constexpr size_t kSearchBufferSize = 512;
  constexpr size_t kMaxSearchBytes = 80;
  if (needle.size() > kMaxSearchBytes) return false;

  FsFile file;
  if (!Storage.openFileForRead("NOTES", path, file)) return false;
  if (file.size() > kMaxNoteBytes) {
    file.close();
    return false;
  }

  const auto foldByte = [](const unsigned char c) {
    return static_cast<unsigned char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
  };

  std::array<uint8_t, kMaxSearchBytes> prefix{};
  for (size_t i = 1, matched = 0; i < needle.size(); ++i) {
    const unsigned char current = foldByte(static_cast<unsigned char>(needle[i]));
    while (matched > 0 && current != foldByte(static_cast<unsigned char>(needle[matched]))) matched = prefix[matched - 1];
    if (current == foldByte(static_cast<unsigned char>(needle[matched]))) ++matched;
    prefix[i] = static_cast<uint8_t>(matched);
  }

  std::array<uint8_t, kSearchBufferSize> buffer{};
  size_t matched = 0;
  while (true) {
    const int count = file.read(buffer.data(), buffer.size());
    if (count <= 0) break;
    for (int i = 0; i < count; ++i) {
      const unsigned char current = foldByte(buffer[static_cast<size_t>(i)]);
      while (matched > 0 && current != foldByte(static_cast<unsigned char>(needle[matched]))) matched = prefix[matched - 1];
      if (current == foldByte(static_cast<unsigned char>(needle[matched]))) ++matched;
      if (matched == needle.size()) {
        file.close();
        return true;
      }
    }
  }
  file.close();
  return false;
}

bool NotesActivity::saveNote(const std::string& path, const std::string& text) const {
  if (text.size() > kMaxNoteBytes) return false;
  if (noteLockedByPath(path)) return saveEncryptedNoteFile(path, text, vaultPattern);
  return saveNoteFile(path, text);
}

void NotesActivity::editNote(const std::string& path, const std::string& title) {
  std::string initialText;
  if (!loadNote(path, initialText)) initialText.clear();

  startActivityForResult(
      std::make_unique<NotesKeyboardActivity>(renderer, mappedInput, title, std::move(initialText), kMaxNoteBytes, path,
                                              vaultMode ? vaultPattern : std::string{}),
      [this, path](const ActivityResult&) {
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
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_NOTE_TITLE), "", 48, InputType::Text, 1),
      [this](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
        if (!keyboard || keyboard->text.empty()) {
          requestUpdate();
          return;
        }
        const std::string path = uniquePathForTitle(keyboard->text);
        if (!saveNote(path, "")) {
          LOG_ERR("NOTES", "Failed to create note: %s", path.c_str());
          requestUpdate();
          return;
        }
        reloadNotes();
        applyFilter();
        editNote(path, keyboard->text);
      });
}

void NotesActivity::renameNote(const std::string& filename) {
  const std::string oldTitle = displayName(filename);
  const std::string oldPath = std::string(kNotesDir) + "/" + filename;
  const bool wasLocked = noteLockedByPath(oldPath);
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_NOTE_TITLE), oldTitle, 48,
                                              InputType::Text, 1),
      [this, filename, oldPath, wasLocked](const ActivityResult& result) {
        if (result.isCancelled) {
          requestUpdate();
          return;
        }
        const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
        if (!keyboard || keyboard->text.empty()) {
          requestUpdate();
          return;
        }

        const std::string sanitized = sanitizeFilename(keyboard->text);
        const std::string requestedFilename = sanitized + ".txt";
        if (requestedFilename == filename) {
          requestUpdate();
          return;
        }

        std::string content;
        if (!loadNote(oldPath, content)) {
          LOG_ERR("NOTES", "Failed to read note for rename: %s", oldPath.c_str());
          requestUpdate();
          return;
        }
        const std::string newPath = uniquePathForTitle(keyboard->text);
        const bool wroteNew = wasLocked ? saveEncryptedNoteFile(newPath, content, vaultPattern) : saveNote(newPath, content);
        if (!wroteNew) {
          LOG_ERR("NOTES", "Failed to write renamed note: %s", newPath.c_str());
          requestUpdate();
          return;
        }
        if (wasLocked && !createLockMarker(newPath)) {
          Storage.remove(newPath.c_str());
          LOG_ERR("NOTES", "Failed to preserve lock while renaming note: %s", oldPath.c_str());
          requestUpdate();
          return;
        }
        if (!Storage.remove(oldPath.c_str())) {
          Storage.remove(newPath.c_str());
          if (wasLocked) removeLockMarker(newPath);
          LOG_ERR("NOTES", "Failed to remove old note after rename: %s", oldPath.c_str());
          requestUpdate();
          return;
        }
        if (wasLocked) removeLockMarker(oldPath);
        reloadNotes();
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::editSearch() {
  startActivityForResult(
      std::make_unique<KeyboardEntryActivity>(renderer, mappedInput, tr(STR_SEARCH_NOTES), searchQuery, 80,
                                              InputType::Text),
      [this](const ActivityResult& result) {
        if (!result.isCancelled) {
          const auto* keyboard = std::get_if<KeyboardResult>(&result.data);
          if (keyboard) searchQuery = keyboard->text;
        }
        selectorIndex = 0;
        topIndex = 0;
        applyFilter();
        requestUpdate();
      });
}

void NotesActivity::openNoteAt(const int index) {
  if (index < 0 || index >= static_cast<int>(filteredNotes.size())) return;
  selectorIndex = index;
  const std::string& filename = notes[filteredNotes[static_cast<size_t>(index)]];
  editNote(std::string(kNotesDir) + "/" + filename, displayName(filename));
}

void NotesActivity::openSelectedNote() { openNoteAt(selectorIndex); }

bool NotesActivity::handleVaultSequenceStep(const bool next) {
  if (vaultMode) {
    vaultSequencePos = 0;
    return false;
  }
  static constexpr bool sequence[] = {true, false, true, false};
  if (next == sequence[vaultSequencePos]) {
    ++vaultSequencePos;
  } else {
    vaultSequencePos = next ? 1 : 0;
  }
  if (vaultSequencePos < sizeof(sequence) / sizeof(sequence[0])) return false;
  vaultSequencePos = 0;
  promptVaultAccess();
  return true;
}

void NotesActivity::promptVaultAccess() {
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


void NotesActivity::loop() {
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto backLayout = TouchHeaderBackButton::layout(header);
  const Rect backRect = backLayout.touchRect;
  const int controlOffset = std::min(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
                                     std::max(0, header.y + header.height -
                                                     (backLayout.iconRect.y +
                                                      (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
  const Rect addRect{width - kSideButtonWidth, header.y + controlOffset, kSideButtonWidth, header.height};
  const int searchLeft = backLayout.iconRect.x + backLayout.iconRect.width + kControlGap;
  const int searchRight = addRect.x - kControlGap;
  const Rect searchRect{searchLeft, header.y + controlOffset, std::max(1, searchRight - searchLeft), header.height};
  const int listTop = header.y + header.height + metrics.verticalSpacing;
  const int listBottom = height - metrics.buttonHintsHeight - kTopMargin;
  const int visibleRows = std::max(1, (listBottom - listTop) / kRowHeight);

  int tx = 0;
  int ty = 0;
  if (mappedInput.wasScreenTapped(tx, ty)) {
    if (pointInRect(backRect, tx, ty)) {
      finish();
      return;
    }
    if (pointInRect(addRect, tx, ty)) {
      createNote();
      return;
    }
    if (pointInRect(searchRect, tx, ty)) {
      const Rect clearRect{searchRect.x + searchRect.width - kSearchClearWidth, searchRect.y, kSearchClearWidth,
                           searchRect.height};
      if (!searchQuery.empty() && pointInRect(clearRect, tx, ty)) {
        searchQuery.clear();
        selectorIndex = 0;
        topIndex = 0;
        applyFilter();
        requestUpdate();
      } else {
        editSearch();
      }
      return;
    }
    if (ty >= listTop && ty < listBottom) {
      const int row = (ty - listTop) / kRowHeight;
      const int index = topIndex + row;
      if (row >= 0 && row < visibleRows && index >= 0 && index < static_cast<int>(filteredNotes.size())) {
        selectorIndex = index;
        const Rect rowRect{kTopMargin, listTop + row * kRowHeight, width - kTopMargin * 2, kRowHeight - 2};
        const Rect deleteRect{rowRect.x + rowRect.width - kDeleteButtonWidth, rowRect.y, kDeleteButtonWidth,
                              rowRect.height};
        const Rect lockRect{deleteRect.x - (vaultMode ? kLockButtonWidth : 0), rowRect.y,
                            vaultMode ? kLockButtonWidth : 0, rowRect.height};
        const Rect renameRect{lockRect.x - kRenameButtonWidth, rowRect.y, kRenameButtonWidth, rowRect.height};
        if (pointInRect(deleteRect, tx, ty)) {
          const std::string& filename = notes[filteredNotes[static_cast<size_t>(index)]];
          const std::string path = std::string(kNotesDir) + "/" + filename;
          const std::string heading = "Supprimer '" + displayName(filename) + "' ?";
          startActivityForResult(
              std::make_unique<ConfirmationActivity>(renderer, mappedInput, heading, ""),
              [this, path](const ActivityResult& result) {
                if (result.isCancelled) {
                  requestUpdate();
                  return;
                }
                if (!Storage.remove(path.c_str())) {
                  LOG_ERR("NOTES", "Failed to delete note: %s", path.c_str());
                } else {
                  removeLockMarker(path);
                }
                reloadNotes();
                applyFilter();
                requestUpdate();
              });
          return;
        }
        const size_t tappedNoteIndex = filteredNotes[static_cast<size_t>(index)];
        const std::string& tappedFilename = notes[tappedNoteIndex];
        const bool tappedLocked = tappedNoteIndex < noteLockedStates.size() && noteLockedStates[tappedNoteIndex] != 0;
        if (vaultMode && tappedLocked && pointInRect(lockRect, tx, ty)) return;
        if (pointInRect(renameRect, tx, ty)) {
          const std::string& filename = notes[filteredNotes[static_cast<size_t>(index)]];
          renameNote(filename);
          return;
        }
        openNoteAt(index);
        return;
      }
    }
  }

  const int itemCount = static_cast<int>(filteredNotes.size());
  const auto moveSelection = [this, itemCount, visibleRows](const int next) {
    if (itemCount <= 0) return;
    selectorIndex = next;
    if (selectorIndex < topIndex) topIndex = selectorIndex;
    if (selectorIndex >= topIndex + visibleRows) topIndex = selectorIndex - visibleRows + 1;
    topIndex = std::clamp(topIndex, 0, std::max(0, itemCount - visibleRows));
    requestUpdate();
  };

  buttonNavigator.onNextRelease([this, itemCount, &moveSelection] {
    if (handleVaultSequenceStep(true)) return;
    if (itemCount > 0) moveSelection(ButtonNavigator::nextIndex(selectorIndex, itemCount));
  });
  buttonNavigator.onPreviousRelease([this, itemCount, &moveSelection] {
    if (handleVaultSequenceStep(false)) return;
    if (itemCount > 0) moveSelection(ButtonNavigator::previousIndex(selectorIndex, itemCount));
  });

  if (itemCount > 0) {
    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      openSelectedNote();
      return;
    }

    const auto swipe = mappedInput.wasSwipe();
    if (swipe == MappedInputManager::SwipeDir::Up || swipe == MappedInputManager::SwipeDir::Down) {
      const int maxTop = std::max(0, itemCount - visibleRows);
      const int delta = swipe == MappedInputManager::SwipeDir::Up ? visibleRows : -visibleRows;
      topIndex = std::clamp(topIndex + delta, 0, maxTop);
      selectorIndex = std::clamp(selectorIndex, topIndex, std::min(itemCount - 1, topIndex + visibleRows - 1));
      requestUpdate();
      return;
    }
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
    finish();
  }
}

void NotesActivity::render(RenderLock&&) {
  renderer.clearScreen();
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  const Rect header = TouchHeaderBackButton::headerRect(renderer, mappedInput);
  const auto backLayout = TouchHeaderBackButton::layout(header);
  const int controlOffset = std::min(TouchHeaderBackButton::TITLE_VERTICAL_OFFSET,
                                     std::max(0, header.y + header.height -
                                                     (backLayout.iconRect.y +
                                                      (backLayout.iconRect.height + TouchHeaderBackButton::ICON_SIZE) / 2)));
  const Rect addRect{width - kSideButtonWidth, header.y + controlOffset, kSideButtonWidth, header.height};
  const int searchLeft = backLayout.iconRect.x + backLayout.iconRect.width + kControlGap;
  const int searchRight = addRect.x - kControlGap;
  const Rect searchRect{searchLeft, header.y + controlOffset, std::max(1, searchRight - searchLeft), header.height};

  TouchHeaderBackButton::draw(renderer, header, "", false, kSideButtonWidth + kControlGap);
  drawPlusIcon(renderer, addRect);

  const Rect searchIconRect{searchRect.x, searchRect.y, 34, searchRect.height};
  drawSearchIcon(renderer, searchIconRect);

  const char* placeholder = tr(STR_SEARCH_NOTES);
  const int searchTextReserve = searchQuery.empty() ? 8 : 8 + kSearchClearWidth;
  const int searchTextX = searchRect.x + searchIconRect.width + 4;
  const int searchTextWidth = std::max(1, searchRect.x + searchRect.width - searchTextX - searchTextReserve);
  const std::string searchLabel =
      searchQuery.empty()
          ? std::string(placeholder)
          : renderer.truncatedText(UI_12_FONT_ID, searchQuery.c_str(), searchTextWidth);
  const int searchTextH = renderer.getLineHeight(UI_12_FONT_ID);
  renderer.drawText(UI_12_FONT_ID, searchTextX, searchRect.y + (searchRect.height - searchTextH) / 2,
                    searchLabel.c_str());
  renderer.drawLine(searchTextX, searchRect.y + searchRect.height - 5, searchRect.x + searchRect.width - 4,
                    searchRect.y + searchRect.height - 5, 1, true);
  if (!searchQuery.empty()) {
    const Rect clearRect{searchRect.x + searchRect.width - kSearchClearWidth, searchRect.y, kSearchClearWidth,
                         searchRect.height};
    drawClearIcon(renderer, clearRect);
  }

  const int listTop = header.y + header.height + metrics.verticalSpacing;
  const int listBottom = height - metrics.buttonHintsHeight - kTopMargin;
  const int visibleRows = std::max(1, (listBottom - listTop) / kRowHeight);
  const int itemCount = static_cast<int>(filteredNotes.size());
  const int maxTop = std::max(0, itemCount - visibleRows);
  topIndex = std::clamp(topIndex, 0, maxTop);

  if (filteredNotes.empty()) {
    renderer.drawCenteredText(UI_12_FONT_ID, listTop + kRowHeight, tr(STR_NO_NOTES), true);
  } else {
    for (int row = 0; row < visibleRows; ++row) {
      const int index = topIndex + row;
      if (index >= itemCount) break;
      const int rowY = listTop + row * kRowHeight;
      const Rect rowRect{kTopMargin, rowY, width - kTopMargin * 2, kRowHeight - 2};
      const Rect deleteRect{rowRect.x + rowRect.width - kDeleteButtonWidth, rowRect.y, kDeleteButtonWidth,
                            rowRect.height};
      const Rect lockRect{deleteRect.x - (vaultMode ? kLockButtonWidth : 0), rowRect.y,
                          vaultMode ? kLockButtonWidth : 0, rowRect.height};
      const Rect renameRect{lockRect.x - kRenameButtonWidth, rowRect.y, kRenameButtonWidth, rowRect.height};
      const bool selected = index == selectorIndex;
      if (selected) {
        auto target = makeUiTarget(renderer);
        target.fill(freeink::ui::Rect{static_cast<int16_t>(rowRect.x), static_cast<int16_t>(rowRect.y),
                                      static_cast<int16_t>(rowRect.width), static_cast<int16_t>(rowRect.height)},
                    freeink::ui::Paint::dither(freeink::ui::Color::LightGray));
      }
      const size_t rowNoteIndex = filteredNotes[static_cast<size_t>(index)];
      const std::string& rowFilename = notes[rowNoteIndex];
      const bool rowLocked = rowNoteIndex < noteLockedStates.size() && noteLockedStates[rowNoteIndex] != 0;
      const std::string title = renderer.truncatedText(UI_12_FONT_ID, displayName(rowFilename).c_str(),
                                                       rowRect.width - kRowSidePadding * 2 - kRenameButtonWidth -
                                                           kDeleteButtonWidth - (vaultMode ? kLockButtonWidth : 0));
      const int textH = renderer.getLineHeight(UI_12_FONT_ID);
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
    }
  }

  const auto labels = mappedInput.mapLabels(tr(STR_SELECT), tr(STR_BACK), tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);
  renderer.displayBuffer();
}