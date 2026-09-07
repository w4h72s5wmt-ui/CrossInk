#include "PersistableStore.h"

#include <HalStorage.h>
#include <Logging.h>
#include <ObfuscationUtils.h>

#include <cstdio>

namespace {
constexpr size_t kMaxJsonBytes = 50000;
constexpr size_t kJsonReadChunkBytes = 512;
constexpr size_t kSidecarPathBytes = 320;

bool makeSidecarPath(const char* path, const char* suffix, char* out, const size_t outSize) {
  const int written = snprintf(out, outSize, "%s%s", path, suffix);
  return written > 0 && static_cast<size_t>(written) < outSize;
}

bool removeIfPresent(const char* path) { return !Storage.exists(path) || Storage.remove(path); }

bool readJsonFile(const char* path, JsonDocument& doc) {
  HalFile file;
  if (!Storage.openFileForRead("PERSIST", path, file)) {
    LOG_ERR("PERSIST", "Failed to open %s", path);
    return false;
  }

  const uint64_t fileSize = file.fileSize64();
  const size_t readLimit =
      fileSize > kMaxJsonBytes ? kMaxJsonBytes : static_cast<size_t>(fileSize);

  String json;
  if (readLimit > 0 && !json.reserve(readLimit)) {
    file.close();
    LOG_ERR("PERSIST", "Failed to reserve %u bytes for %s", static_cast<unsigned>(readLimit), path);
    return false;
  }

  uint8_t buffer[kJsonReadChunkBytes];
  size_t totalRead = 0;
  while (totalRead < readLimit) {
    const size_t remaining = readLimit - totalRead;
    const size_t wanted = remaining < sizeof(buffer) ? remaining : sizeof(buffer);
    const int read = file.read(buffer, wanted);
    if (read < 0) {
      file.close();
      LOG_ERR("PERSIST", "Failed while reading %s", path);
      return false;
    }
    if (read == 0) break;

    if (!json.concat(reinterpret_cast<const char*>(buffer), static_cast<unsigned int>(read))) {
      file.close();
      LOG_ERR("PERSIST", "Out of memory while reading %s", path);
      return false;
    }
    totalRead += static_cast<size_t>(read);
  }

  if (!file.close()) {
    LOG_ERR("PERSIST", "Failed to close %s after read", path);
    return false;
  }
  if (json.isEmpty()) {
    LOG_ERR("PERSIST", "Failed to read %s (empty)", path);
    return false;
  }

  const auto error = deserializeJson(doc, json);
  if (error) {
    LOG_ERR("PERSIST", "JSON parse error in %s: %s", path, error.c_str());
    return false;
  }
  return true;
}
}  // namespace

bool PersistableStoreBase::writeDocToFile(const char* path, const JsonDocument& doc) {
  Storage.mkdir("/.crosspoint");

  char tempPath[kSidecarPathBytes];
  char backupPath[kSidecarPathBytes];
  if (!makeSidecarPath(path, ".tmp", tempPath, sizeof(tempPath)) ||
      !makeSidecarPath(path, ".bak", backupPath, sizeof(backupPath))) {
    LOG_ERR("PERSIST", "Persistence path too long: %s", path);
    return false;
  }

  if (!removeIfPresent(tempPath)) {
    LOG_ERR("PERSIST", "Failed to remove stale temp file %s", tempPath);
    return false;
  }

  HalFile file;
  if (!Storage.openFileForWrite("PERSIST", tempPath, file)) {
    LOG_ERR("PERSIST", "Failed to open temp file %s", tempPath);
    return false;
  }

  const size_t expectedBytes = measureJson(doc);
  const size_t writtenBytes = serializeJson(doc, file);
  const bool synced = file.sync();
  const bool closed = file.close();
  if (writtenBytes != expectedBytes || !synced || !closed) {
    Storage.remove(tempPath);
    LOG_ERR("PERSIST", "Failed to write %s", path);
    return false;
  }

  const bool hadOriginal = Storage.exists(path);
  if (hadOriginal) {
    if (!removeIfPresent(backupPath)) {
      Storage.remove(tempPath);
      LOG_ERR("PERSIST", "Failed to remove stale backup %s", backupPath);
      return false;
    }
    if (!Storage.rename(path, backupPath)) {
      Storage.remove(tempPath);
      LOG_ERR("PERSIST", "Failed to back up %s", path);
      return false;
    }
  }

  if (!Storage.rename(tempPath, path)) {
    Storage.remove(tempPath);
    if (hadOriginal && !Storage.exists(path) && !Storage.rename(backupPath, path)) {
      LOG_ERR("PERSIST", "Failed to restore backup for %s", path);
    }
    LOG_ERR("PERSIST", "Failed to install new %s", path);
    return false;
  }

  // A leftover backup is harmless, but normally remove it once the new file is
  // durably installed. If power is lost during the swap, readDocFromFile() can
  // still fall back to this sidecar on the next boot.
  if (hadOriginal && Storage.exists(backupPath) && !Storage.remove(backupPath)) {
    LOG_ERR("PERSIST", "Failed to remove backup %s", backupPath);
  }
  return true;
}

bool PersistableStoreBase::readDocFromFile(const char* path, JsonDocument& doc) {
  const bool primaryExists = Storage.exists(path);
  if (primaryExists && readJsonFile(path, doc)) {
    return true;
  }

  char backupPath[kSidecarPathBytes];
  if (!makeSidecarPath(path, ".bak", backupPath, sizeof(backupPath)) || !Storage.exists(backupPath)) {
    return false;  // Expected on first boot when neither primary nor backup exists.
  }

  doc.clear();
  if (!readJsonFile(backupPath, doc)) {
    return false;
  }
  LOG_INF("PERSIST", "Recovered %s from backup", path);
  return true;
}

std::string PersistableStoreBase::extractPassword(JsonVariantConst doc, bool& needsResave) {
  obfuscation::DecodeStatus status = obfuscation::DecodeStatus::INVALID;
  std::string pass = obfuscation::deobfuscateFromBase64(doc["password_obf"] | "", &status);
  if (status == obfuscation::DecodeStatus::LEGACY && !pass.empty()) {
    needsResave = true;
  }
  if (status == obfuscation::DecodeStatus::INVALID || status == obfuscation::DecodeStatus::EMPTY || pass.empty()) {
    // Deobfuscation failed or no obfuscated password was stored; fall back to legacy plaintext.
    pass = doc["password"] | "";
    if (!pass.empty()) needsResave = true;
  }
  return pass;
}
