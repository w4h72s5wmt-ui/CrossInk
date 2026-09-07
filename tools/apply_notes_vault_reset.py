from pathlib import Path

p = Path('src/activities/home/NotesActivity.cpp')
s = p.read_text()

def rep(old, new, label):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    s = s.replace(old, new, 1)

rep('#include "components/TouchHeaderBackButton.h"\n',
    '#include "components/TouchHeaderBackButton.h"\n#include "components/OptionPopup.h"\n',
    'OptionPopup include')

rep('constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\n',
    'constexpr const char* kVaultFingerprintPath = "/Notes/.vault";\nconstexpr const char* kResetVaultToken = "__RESET_VAULT__";\n',
    'reset token')

anchor = 'class VaultPatternActivity final : public Activity {\n'
choice = r'''class VaultRecoveryChoiceActivity final : public Activity {
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

'''
rep(anchor, choice + anchor, 'recovery choice insertion')

rep('''  VaultPatternActivity(GfxRenderer& renderer, MappedInputManager& mappedInput, const bool verify,
                       const uint64_t expectedFingerprint)
      : Activity("NotesVaultPattern", renderer, mappedInput),
        verify(verify),
        expectedFingerprint(expectedFingerprint) {}
''',
'''  VaultPatternActivity(GfxRenderer& renderer, MappedInputManager& mappedInput, const bool verify,
                       const uint64_t expectedFingerprint, const bool allowResetAfterFailures = false)
      : Activity("NotesVaultPattern", renderer, mappedInput),
        verify(verify),
        expectedFingerprint(expectedFingerprint),
        allowResetAfterFailures(allowResetAfterFailures) {}
''', 'pattern constructor')

rep('''  bool verify = false;
  uint64_t expectedFingerprint = 0;
  std::string pattern;
''',
'''  bool verify = false;
  uint64_t expectedFingerprint = 0;
  bool allowResetAfterFailures = false;
  uint8_t failedAttempts = 0;
  std::string pattern;
''', 'pattern fields')

old_wrong = '''    if (verify && fingerprint != expectedFingerprint) {
      pattern.clear();
      invalidPattern = true;
      requestUpdate();
      return;
    }
'''
new_wrong = '''    if (verify && fingerprint != expectedFingerprint) {
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
'''
rep(old_wrong, new_wrong, 'three-attempt recovery')

# Add purge helper after encryption detector.
anchor2 = '''bool saveNoteFile(const std::string& path, const std::string& text) {
'''
helper = r'''bool purgeProtectedVaultNotes() {
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
  return true;
}

'''
rep(anchor2, helper + anchor2, 'purge helper')

# Only vault-entry verification gets the 3-attempt reset option.
rep('''      std::make_unique<VaultPatternActivity>(renderer, mappedInput, true, expectedFingerprint),
      [this](const ActivityResult& result) {
''',
'''      std::make_unique<VaultPatternActivity>(renderer, mappedInput, true, expectedFingerprint, true),
      [this](const ActivityResult& result) {
''', 'vault access reset enable')

# Handle the special reset choice before normal pattern validation.
old_cb = '''        const auto* pattern = std::get_if<KeyboardResult>(&result.data);
        if (!pattern || (pattern->text.size() != kPatternLength &&
                         pattern->text.size() != kLegacyPatternLength)) {
          requestUpdate();
          return;
        }
        reloadNotes();
'''
new_cb = '''        const auto* pattern = std::get_if<KeyboardResult>(&result.data);
        if (!pattern) {
          requestUpdate();
          return;
        }
        if (pattern->text == kResetVaultToken) {
          if (!purgeProtectedVaultNotes()) {
            requestUpdate();
            return;
          }
          std::fill(vaultPattern.begin(), vaultPattern.end(), '\\0');
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
                }
                requestUpdate();
              });
          return;
        }
        if (pattern->text.size() != kPatternLength && pattern->text.size() != kLegacyPatternLength) {
          requestUpdate();
          return;
        }
        reloadNotes();
'''
rep(old_cb, new_cb, 'reset callback')

p.write_text(s)
print('Notes vault reset patch applied')
