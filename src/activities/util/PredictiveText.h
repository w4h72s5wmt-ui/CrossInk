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
  static constexpr size_t kPersonalWordBytes = 40;

  class CompactWord {
   public:
    CompactWord() = default;
    CompactWord(const std::string& value) { assign(value); }

    CompactWord& operator=(const std::string& value) {
      assign(value);
      return *this;
    }

    const char* c_str() const { return data_.data(); }

    bool operator<(const CompactWord& other) const {
      const char* left = data_.data();
      const char* right = other.data_.data();
      while (*left != '\0' && *right != '\0' && *left == *right) {
        ++left;
        ++right;
      }
      return static_cast<unsigned char>(*left) < static_cast<unsigned char>(*right);
    }

   private:
    std::array<char, kPersonalWordBytes + 1> data_{};

    void assign(const std::string& value) {
      const size_t length = value.size() < kPersonalWordBytes ? value.size() : kPersonalWordBytes;
      for (size_t i = 0; i < length; ++i) data_[i] = value[i];
      data_[length] = '\0';
    }
  };

  struct PersonalWord {
    CompactWord word;
    uint16_t count = 1;
  };

  // All personal words now live directly inside this single contiguous vector.
  // CompactWord owns no heap memory, so learning hundreds of words no longer
  // creates hundreds of independent std::string allocations.
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
