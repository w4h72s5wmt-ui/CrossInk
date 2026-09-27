#pragma once

#include <RssParser.h>

#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace RssArticleMetadata {

struct Record {
  uint8_t sourceIndex = 0;
  uint8_t readingMinutes = 0;
  char title[RSS_TITLE_CAPACITY + 1] = {};
  char link[RSS_LINK_CAPACITY + 1] = {};
  char published[RSS_PUBLISHED_CAPACITY + 1] = {};
};

constexpr size_t RECORD_BYTES = 2 + (RSS_TITLE_CAPACITY + 1) + (RSS_LINK_CAPACITY + 1) +
                                (RSS_PUBLISHED_CAPACITY + 1);
static_assert(sizeof(Record) == RECORD_BYTES, "RSS history metadata must stay packed/lightweight");

inline bool sameFields(const char* leftLink, const char* leftTitle, const char* leftPublished,
                       const char* rightLink, const char* rightTitle, const char* rightPublished) {
  const bool leftHasLink = leftLink && leftLink[0];
  const bool rightHasLink = rightLink && rightLink[0];
  if (leftHasLink && rightHasLink) return std::strcmp(leftLink, rightLink) == 0;
  if (std::strcmp(leftTitle ? leftTitle : "", rightTitle ? rightTitle : "") != 0) return false;
  const bool leftHasPublished = leftPublished && leftPublished[0];
  const bool rightHasPublished = rightPublished && rightPublished[0];
  if (leftHasPublished || rightHasPublished) {
    return std::strcmp(leftPublished ? leftPublished : "", rightPublished ? rightPublished : "") == 0;
  }
  return true;
}

inline bool same(const RssItem& left, const RssItem& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline bool same(const Record& left, const RssItem& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline bool same(const Record& left, const Record& right) {
  return sameFields(left.link, left.title, left.published, right.link, right.title, right.published);
}

inline uint8_t readingMinutesForText(const char* text, const size_t length, const uint16_t wordsPerMinute = 220) {
  if (!text || length == 0 || wordsPerMinute == 0) return 0;
  size_t words = 0;
  bool inWord = false;
  for (size_t i = 0; i < length && text[i]; ++i) {
    const bool separator = std::isspace(static_cast<unsigned char>(text[i]));
    if (!separator && !inWord) ++words;
    inWord = !separator;
  }
  if (words == 0) return 0;
  const size_t minutes = (words + wordsPerMinute - 1U) / wordsPerMinute;
  return static_cast<uint8_t>(minutes > 99U ? 99U : minutes);
}

inline Record fromItem(const uint8_t sourceIndex, const RssItem& item, const uint8_t readingMinutes = 0) {
  Record record{};
  record.sourceIndex = sourceIndex;
  record.readingMinutes = readingMinutes;
  std::memcpy(record.title, item.title, sizeof(record.title));
  std::memcpy(record.link, item.link, sizeof(record.link));
  std::memcpy(record.published, item.published, sizeof(record.published));
  record.title[sizeof(record.title) - 1] = '\0';
  record.link[sizeof(record.link) - 1] = '\0';
  record.published[sizeof(record.published) - 1] = '\0';
  return record;
}

}  // namespace RssArticleMetadata
