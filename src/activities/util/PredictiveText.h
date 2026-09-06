#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

class PredictiveText {
 public:
  void load();
  void save();
  void seedFromText(const std::string& text);
  void learnWordBefore(const std::string& text, size_t endPos);
  void learnCurrentWord(const std::string& text, size_t cursorPos);

  std::array<std::string, 3> suggestions(const std::string& text, size_t cursorPos) const;
  bool applySuggestion(std::string& text, size_t& cursorPos, size_t maxLength, const std::string& suggestion);

  bool dirty() const { return dirty_; }

 private:
  struct PersonalWord {
    std::string word;
    uint16_t count = 1;
  };

  std::vector<PersonalWord> personal_;
  bool dirty_ = false;
  uint32_t revision_ = 1;
  mutable uint32_t cachedRevision_ = 0;
  mutable std::string cachedKey_;
  mutable std::array<std::string, 3> cachedSuggestions_{};

  static bool isWordByte(unsigned char c);
  static std::string normalizeWord(std::string word);
  static std::string foldForMatch(const std::string& word);
  static void currentWordRange(const std::string& text, size_t cursorPos, size_t& start, size_t& end);
  static bool startsWithFolded(const std::string& word, const std::string& foldedPrefix);
  static bool isBuiltinWord(const std::string& normalizedWord);

  void addPersonalWord(const std::string& word, uint16_t increment, bool allowBuiltin);
  void invalidateSuggestionCache();
};
