from pathlib import Path

p = Path('src/activities/home/NotesActivity.cpp')
s = p.read_text()

def one(old, new, label):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    s = s.replace(old, new, 1)

# Six taps for all new vault codes; retain four-tap recognition only for migrating an old vault.
one('constexpr size_t kPatternLength = 4;\n',
    'constexpr size_t kPatternLength = 6;\nconstexpr size_t kLegacyPatternLength = 4;\nconstexpr size_t kMaxEncryptedPlaintextBytes = 32 * 1024;\n',
    'pattern length')

# A verified keypad accepts an old 4-tap fingerprint immediately, otherwise it keeps collecting to 6 taps.
old_append = '''    const uint64_t fingerprint = patternFingerprint(pattern);\n    if (verify && fingerprint != expectedFingerprint) {\n      pattern.clear();\n      invalidPattern = true;\n      requestUpdate();\n      return;\n    }\n    setResult(ActivityResult{KeyboardResult{pattern}});\n    finish();\n'''
new_append = '''    if (verify && pattern.size() == kLegacyPatternLength &&\n        patternFingerprint(pattern) == expectedFingerprint) {\n      setResult(ActivityResult{KeyboardResult{pattern}});\n      finish();\n      return;\n    }\n    if (pattern.size() < kPatternLength) {\n      requestUpdate();\n      return;\n    }\n    const uint64_t fingerprint = patternFingerprint(pattern);\n    if (verify && fingerprint != expectedFingerprint) {\n      pattern.clear();\n      invalidPattern = true;\n      requestUpdate();\n      return;\n    }\n    setResult(ActivityResult{KeyboardResult{pattern}});\n    finish();\n'''
# The original function already has a preliminary "size < kPatternLength" block. Remove it so the
# legacy check can happen exactly on tap four without finishing non-verifying setup early.
one('''    if (pattern.size() < kPatternLength) {\n      requestUpdate();\n      return;\n    }\n    const uint64_t fingerprint = patternFingerprint(pattern);\n    if (verify && fingerprint != expectedFingerprint) {\n      pattern.clear();\n      invalidPattern = true;\n      requestUpdate();\n      return;\n    }\n    setResult(ActivityResult{KeyboardResult{pattern}});\n    finish();\n''', new_append, 'pattern verifier')

# Key derivation can still decrypt a legacy 4-tap encrypted payload during compatibility access.
one('''bool deriveVaultKey(const std::string& pattern, std::array<uint8_t, kCryptoKeyBytes>& key) {\n  if (pattern.size() != kPatternLength) return false;\n  static constexpr char domain[] = "CrossInk Notes AES-256-GCM v1";\n  std::array<uint8_t, sizeof(domain) - 1 + kPatternLength> seed{};\n  memcpy(seed.data(), domain, sizeof(domain) - 1);\n  memcpy(seed.data() + sizeof(domain) - 1, pattern.data(), kPatternLength);\n  return mbedtls_sha256(seed.data(), seed.size(), key.data(), 0) == 0;\n}\n''',
'''bool deriveVaultKey(const std::string& pattern, std::array<uint8_t, kCryptoKeyBytes>& key) {\n  if (pattern.size() != kPatternLength && pattern.size() != kLegacyPatternLength) return false;\n  static constexpr char domain[] = "CrossInk Notes AES-256-GCM v1";\n  std::array<uint8_t, sizeof(domain) - 1 + kPatternLength> seed{};\n  memcpy(seed.data(), domain, sizeof(domain) - 1);\n  memcpy(seed.data() + sizeof(domain) - 1, pattern.data(), pattern.size());\n  const size_t seedSize = sizeof(domain) - 1 + pattern.size();\n  return mbedtls_sha256(seed.data(), seedSize, key.data(), 0) == 0;\n}\n''', 'legacy key derivation')

# Fix helper visibility: crypto helpers live outside NotesActivity and should use their own matching limit.
s = s.replace('NotesActivity::kMaxNoteBytes', 'kMaxEncryptedPlaintextBytes')

# Before unlock: locked notes remain hidden. After unlock: show BOTH normal and locked notes together.
one('    if (noteLockedByFilename(filename) != vaultMode) continue;\n',
    '    if (!vaultMode && noteLockedByFilename(filename)) continue;\n',
    'mixed vault filter')

# Legacy 4-tap migration: if the old vault only contains plaintext locked notes, require a new 6-tap
# code immediately and then encrypt them with it. If an already-encrypted legacy file exists, keep
# compatibility access with the old key rather than risking data loss during an in-place key rotation.
old_access = '''        vaultPattern = pattern->text;\n        vaultMode = true;\n        searchQuery.clear();\n        selectorIndex = 0;\n        topIndex = 0;\n        reloadNotes();\n        migrateLockedNotes();\n        applyFilter();\n        requestUpdate();\n'''
new_access = '''        reloadNotes();\n        if (pattern->text.size() == kLegacyPatternLength) {\n          bool hasLegacyEncryptedPayload = false;\n          for (const auto& filename : notes) {\n            const std::string path = std::string(kNotesDir) + "/" + filename;\n            if (noteLockedByPath(path) && noteFileIsEncrypted(path)) {\n              hasLegacyEncryptedPayload = true;\n              break;\n            }\n          }\n          if (hasLegacyEncryptedPayload) {\n            vaultPattern = pattern->text;\n            vaultMode = true;\n            searchQuery.clear();\n            selectorIndex = 0;\n            topIndex = 0;\n            applyFilter();\n            requestUpdate();\n            return;\n          }\n\n          startActivityForResult(\n              std::make_unique<VaultPatternActivity>(renderer, mappedInput, false, 0),\n              [this](const ActivityResult& upgradeResult) {\n                if (upgradeResult.isCancelled) {\n                  requestUpdate();\n                  return;\n                }\n                const auto* newPattern = std::get_if<KeyboardResult>(&upgradeResult.data);\n                if (!newPattern || newPattern->text.size() != kPatternLength) {\n                  requestUpdate();\n                  return;\n                }\n                if (!writeVaultFingerprint(patternFingerprint(newPattern->text))) {\n                  LOG_ERR("NOTES", "Failed to upgrade Notes vault fingerprint");\n                  requestUpdate();\n                  return;\n                }\n                vaultPattern = newPattern->text;\n                vaultMode = true;\n                searchQuery.clear();\n                selectorIndex = 0;\n                topIndex = 0;\n                reloadNotes();\n                migrateLockedNotes();\n                applyFilter();\n                requestUpdate();\n              });\n          return;\n        }\n\n        if (pattern->text.size() != kPatternLength) {\n          requestUpdate();\n          return;\n        }\n        vaultPattern = pattern->text;\n        vaultMode = true;\n        searchQuery.clear();\n        selectorIndex = 0;\n        topIndex = 0;\n        migrateLockedNotes();\n        applyFilter();\n        requestUpdate();\n'''
one(old_access, new_access, 'vault access migration')

# The callback currently rejects anything that is not the new length before the migration logic runs.
one('''        if (!pattern || pattern->text.size() != kPatternLength) {\n          requestUpdate();\n          return;\n        }\n        reloadNotes();\n''',
'''        if (!pattern || (pattern->text.size() != kPatternLength &&\n                         pattern->text.size() != kLegacyPatternLength)) {\n          requestUpdate();\n          return;\n        }\n        reloadNotes();\n''', 'accept legacy callback')

# Render a lock only on rows that are actually locked. Reserve the column after vault unlock so rows line up.
one('''      const std::string title = renderer.truncatedText(UI_12_FONT_ID, displayName(notes[filteredNotes[static_cast<size_t>(index)]]).c_str(),\n                                                       rowRect.width - kRowSidePadding * 2 - kRenameButtonWidth -\n                                                           kDeleteButtonWidth - (vaultMode ? kLockButtonWidth : 0));\n''',
'''      const std::string& rowFilename = notes[filteredNotes[static_cast<size_t>(index)]];\n      const bool rowLocked = noteLockedByFilename(rowFilename);\n      const std::string title = renderer.truncatedText(UI_12_FONT_ID, displayName(rowFilename).c_str(),\n                                                       rowRect.width - kRowSidePadding * 2 - kRenameButtonWidth -\n                                                           kDeleteButtonWidth - (vaultMode ? kLockButtonWidth : 0));\n''', 'row filename render')
one('      if (vaultMode) drawLockIcon(renderer, lockRect, true);\n',
    '      if (vaultMode && rowLocked) drawLockIcon(renderer, lockRect, true);\n',
    'locked row icon')

# On unlocked rows the empty reserved lock column should behave like the row instead of swallowing taps.
one('''        if (pointInRect(lockRect, tx, ty)) return;\n        if (pointInRect(renameRect, tx, ty)) {\n''',
'''        const std::string& tappedFilename = notes[filteredNotes[static_cast<size_t>(index)]];\n        if (vaultMode && noteLockedByFilename(tappedFilename) && pointInRect(lockRect, tx, ty)) return;\n        if (pointInRect(renameRect, tx, ty)) {\n''', 'lock hit target')

p.write_text(s)

# Header declaration stays valid; no new methods were needed.
print('Applied 6-cell vault + mixed unlocked list patch')
