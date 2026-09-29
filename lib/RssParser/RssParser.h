#pragma once

#include <Print.h>
#include <expat.h>

#include <cstddef>
#include <cstdint>

// X4 Pro RSS records are intentionally bounded so a malformed feed can never
// grow memory without limit. 4 KB of cleaned feed-provided body text per item
// still leaves ample room for hundreds of articles in the X4 Pro PSRAM/SD cache.
constexpr size_t RSS_TITLE_CAPACITY = 144;
constexpr size_t RSS_LINK_CAPACITY = 384;
constexpr size_t RSS_SUMMARY_CAPACITY = 4096;
constexpr size_t RSS_PUBLISHED_CAPACITY = 56;

struct RssItem {
  char title[RSS_TITLE_CAPACITY + 1] = {};
  char link[RSS_LINK_CAPACITY + 1] = {};
  char summary[RSS_SUMMARY_CAPACITY + 1] = {};
  char published[RSS_PUBLISHED_CAPACITY + 1] = {};
};

enum class RssParserError { NONE, NO_ITEM_BUFFER, INVALID_INPUT, PARSER_MEMORY, BUFFER_MEMORY, XML_PARSE };

/**
 * Streaming RSS/Atom parser backed by a caller-owned fixed item buffer.
 *
 * RSS feeds often expose the same article twice inside an item: a short
 * <description> and a longer <content:encoded>. The parser deliberately keeps
 * one best body candidate instead of concatenating those fields.
 */
class RssParser final : public Print {
 public:
  RssParser(RssItem* items, size_t itemCapacity);
  ~RssParser() override;

  RssParser(const RssParser&) = delete;
  RssParser& operator=(const RssParser&) = delete;

  size_t write(uint8_t c) override;
  size_t write(const uint8_t* data, size_t length) override;
  void flush() override;

  bool error() const { return errorOccurred; }
  explicit operator bool() const { return !error(); }
  RssParserError getErrorReason() const { return errorReason; }
  size_t getItemCount() const { return itemCount; }
  bool wasTruncated() const { return truncated; }
  void clear();

 private:
  static void XMLCALL startElement(void* userData, const XML_Char* name, const XML_Char** atts);
  static void XMLCALL endElement(void* userData, const XML_Char* name);
  static void XMLCALL characterData(void* userData, const XML_Char* data, int len);

  bool resetXmlParser();
  void resetCurrentItem();
  void commitCurrentItem();

  static const char* localName(const XML_Char* name);
  static bool localNameEquals(const XML_Char* name, const char* expected);
  static const char* findAttribute(const XML_Char** atts, const char* name);
  static void assignBounded(char* target, size_t capacity, size_t& length, const char* value);
  static void appendBounded(char* target, size_t capacity, size_t& length, const char* value, size_t valueLength);
  static void cleanTextInPlace(char* text);

  XML_Parser parser = nullptr;
  RssItem* items = nullptr;
  size_t itemCapacity = 0;
  size_t itemCount = 0;

  RssItem currentItem{};
  size_t titleLength = 0;
  size_t linkLength = 0;
  size_t summaryLength = 0;
  size_t publishedLength = 0;

  // Body priority: description=1, Atom summary=2, content/content:encoded=3.
  // Only the highest-priority field encountered for an item is retained.
  uint8_t activeSummaryPriority = 0;
  uint8_t selectedSummaryPriority = 0;

  bool inItem = false;
  bool atomEntry = false;
  bool inTitle = false;
  bool inLinkText = false;
  bool inSummary = false;
  bool inPublished = false;
  bool errorOccurred = false;
  RssParserError errorReason = RssParserError::NONE;
  bool truncated = false;
};
