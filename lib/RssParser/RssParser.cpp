#include "RssParser.h"

#include <Logging.h>
#include <XmlParserUtils.h>

#include <cctype>
#include <cstring>
#include <utility>

namespace {
constexpr size_t XML_CHUNK_SIZE = 1024;

bool startsWith(const char* text, const char* prefix) {
  return text && prefix && strncmp(text, prefix, strlen(prefix)) == 0;
}

bool consumeEntity(const char*& src, char*& dst) {
  struct Entity {
    const char* text;
    const char* replacement;
  };
  static constexpr Entity ENTITIES[] = {
      {"&nbsp;", " "},       {"&#160;", " "},      {"&amp;", "&"},       {"&quot;", "\""},
      {"&apos;", "'"},       {"&#39;", "'"},       {"&lt;", "<"},        {"&gt;", ">"},
      {"&ndash;", "-"},      {"&mdash;", "-"},     {"&hellip;", "..."},   {"&laquo;", "\""},
      {"&raquo;", "\""},    {"&rsquo;", "'"},      {"&lsquo;", "'"},      {"&ldquo;", "\""},
      {"&rdquo;", "\""},    {"&eacute;", "é"},   {"&egrave;", "è"},   {"&ecirc;", "ê"},
      {"&agrave;", "à"},      {"&acirc;", "â"},     {"&ugrave;", "ù"},     {"&ucirc;", "û"},
      {"&ccedil;", "ç"},     {"&ocirc;", "ô"},     {"&icirc;", "î"},     {"&iuml;", "ï"},
      {"&Eacute;", "É"},     {"&Agrave;", "À"},     {"&Ccedil;", "Ç"},
  };
  for (const auto& entity : ENTITIES) {
    if (startsWith(src, entity.text)) {
      const size_t len = strlen(entity.replacement);
      memcpy(dst, entity.replacement, len);
      dst += len;
      src += strlen(entity.text);
      return true;
    }
  }

  if (startsWith(src, "&#")) {
    const char* p = src + 2;
    bool hex = false;
    if (*p == 'x' || *p == 'X') {
      hex = true;
      ++p;
    }
    uint32_t value = 0;
    bool any = false;
    while (*p && *p != ';') {
      const unsigned char c = static_cast<unsigned char>(*p);
      uint8_t digit = 0;
      if (c >= '0' && c <= '9') digit = static_cast<uint8_t>(c - '0');
      else if (hex && c >= 'a' && c <= 'f') digit = static_cast<uint8_t>(10 + c - 'a');
      else if (hex && c >= 'A' && c <= 'F') digit = static_cast<uint8_t>(10 + c - 'A');
      else return false;
      any = true;
      value = value * (hex ? 16u : 10u) + digit;
      if (value > 0x10FFFFu) return false;
      ++p;
    }
    if (!any || *p != ';') return false;

    if (value == 0xA0) value = ' ';
    if (value <= 0x7F) {
      *dst++ = static_cast<char>(value);
    } else if (value <= 0x7FF) {
      *dst++ = static_cast<char>(0xC0 | (value >> 6));
      *dst++ = static_cast<char>(0x80 | (value & 0x3F));
    } else if (value <= 0xFFFF) {
      *dst++ = static_cast<char>(0xE0 | (value >> 12));
      *dst++ = static_cast<char>(0x80 | ((value >> 6) & 0x3F));
      *dst++ = static_cast<char>(0x80 | (value & 0x3F));
    } else {
      *dst++ = static_cast<char>(0xF0 | (value >> 18));
      *dst++ = static_cast<char>(0x80 | ((value >> 12) & 0x3F));
      *dst++ = static_cast<char>(0x80 | ((value >> 6) & 0x3F));
      *dst++ = static_cast<char>(0x80 | (value & 0x3F));
    }
    src = p + 1;
    return true;
  }
  return false;
}
}  // namespace

RssParser::RssParser(RssItem* items, const size_t itemCapacity) : items(items), itemCapacity(itemCapacity) {
  if (!items || itemCapacity == 0) {
    errorOccurred = true;
    errorReason = RssParserError::NO_ITEM_BUFFER;
    LOG_ERR("RSS", "No RSS item buffer supplied");
  }
  resetXmlParser();
}

RssParser::~RssParser() { destroyXmlParser(parser); }

size_t RssParser::write(const uint8_t c) { return write(&c, 1); }

size_t RssParser::write(const uint8_t* data, const size_t length) {
  if (errorOccurred || !parser) return 0;
  if (!data && length > 0) {
    errorOccurred = true;
    errorReason = RssParserError::INVALID_INPUT;
    return 0;
  }

  const char* current = reinterpret_cast<const char*>(data);
  size_t remaining = length;
  while (remaining > 0) {
    const size_t chunk = remaining < XML_CHUNK_SIZE ? remaining : XML_CHUNK_SIZE;
    void* const buffer = XML_GetBuffer(parser, static_cast<int>(chunk));
    if (!buffer) {
      errorOccurred = true;
      errorReason = RssParserError::BUFFER_MEMORY;
      LOG_ERR("RSS", "Could not allocate Expat input buffer");
      destroyXmlParser(parser);
      return 0;
    }
    memcpy(buffer, current, chunk);
    if (XML_ParseBuffer(parser, static_cast<int>(chunk), XML_FALSE) == XML_STATUS_ERROR) {
      errorOccurred = true;
      errorReason = RssParserError::XML_PARSE;
      LOG_ERR("RSS", "XML parse error at line %lu: %s", static_cast<unsigned long>(XML_GetCurrentLineNumber(parser)),
              XML_ErrorString(XML_GetErrorCode(parser)));
      destroyXmlParser(parser);
      return 0;
    }
    current += chunk;
    remaining -= chunk;
  }
  return length;
}

void RssParser::flush() {
  if (!parser || errorOccurred) return;
  if (XML_Parse(parser, nullptr, 0, XML_TRUE) != XML_STATUS_OK) {
    errorOccurred = true;
    errorReason = RssParserError::XML_PARSE;
    LOG_ERR("RSS", "XML finalization failed: %s", XML_ErrorString(XML_GetErrorCode(parser)));
    destroyXmlParser(parser);
  }
}

void RssParser::clear() {
  itemCount = 0;
  truncated = false;
  resetCurrentItem();
  inItem = false;
  atomEntry = false;
  inTitle = inLinkText = inSummary = inPublished = false;
  errorOccurred = !items || itemCapacity == 0;
  errorReason = errorOccurred ? RssParserError::NO_ITEM_BUFFER : RssParserError::NONE;
  resetXmlParser();
}

bool RssParser::resetXmlParser() {
  if (parser) {
    if (XML_ParserReset(parser, nullptr) != XML_TRUE) destroyXmlParser(parser);
  }
  if (!parser) {
    parser = XML_ParserCreate(nullptr);
    if (!parser) {
      errorOccurred = true;
      errorReason = RssParserError::PARSER_MEMORY;
      LOG_ERR("RSS", "Could not allocate Expat parser");
      return false;
    }
  }
  XML_SetUserData(parser, this);
  XML_SetElementHandler(parser, startElement, endElement);
  XML_SetCharacterDataHandler(parser, characterData);
  return true;
}

void RssParser::resetCurrentItem() {
  currentItem = RssItem{};
  titleLength = 0;
  linkLength = 0;
  summaryLength = 0;
  publishedLength = 0;
  activeSummaryPriority = 0;
  selectedSummaryPriority = 0;
}

void RssParser::commitCurrentItem() {
  cleanTextInPlace(currentItem.title);
  cleanTextInPlace(currentItem.summary);
  cleanTextInPlace(currentItem.published);
  cleanTextInPlace(currentItem.link);

  if (currentItem.title[0] == '\0') return;
  if (itemCount >= itemCapacity) {
    truncated = true;
    return;
  }
  items[itemCount++] = currentItem;
}

const char* RssParser::localName(const XML_Char* name) {
  if (!name) return "";
  const char* const colon = strrchr(name, ':');
  return colon ? colon + 1 : name;
}

bool RssParser::localNameEquals(const XML_Char* name, const char* expected) {
  return strcmp(localName(name), expected) == 0;
}

const char* RssParser::findAttribute(const XML_Char** atts, const char* name) {
  if (!atts) return nullptr;
  for (int i = 0; atts[i]; i += 2) {
    if (strcmp(atts[i], name) == 0) return atts[i + 1];
  }
  return nullptr;
}

void RssParser::assignBounded(char* target, const size_t capacity, size_t& length, const char* value) {
  length = 0;
  target[0] = '\0';
  if (!value || capacity == 0) return;
  const size_t copyLength = strnlen(value, capacity);
  memcpy(target, value, copyLength);
  target[copyLength] = '\0';
  length = copyLength;
}

void RssParser::appendBounded(char* target, const size_t capacity, size_t& length, const char* value,
                              const size_t valueLength) {
  if (!value || capacity == 0 || length >= capacity) return;
  const size_t available = capacity - length;
  const size_t copyLength = valueLength < available ? valueLength : available;
  memcpy(target + length, value, copyLength);
  length += copyLength;
  target[length] = '\0';
}

void RssParser::cleanTextInPlace(char* text) {
  if (!text || text[0] == '\0') return;

  const char* src = text;
  char* dst = text;
  bool inTag = false;
  bool pendingSpace = false;

  while (*src) {
    if (*src == '<') {
      inTag = true;
      pendingSpace = dst != text;
      ++src;
      continue;
    }
    if (inTag) {
      if (*src == '>') inTag = false;
      ++src;
      continue;
    }
    if (*src == '&') {
      if (pendingSpace && dst != text && dst[-1] != ' ') {
        *dst++ = ' ';
        pendingSpace = false;
      }
      if (consumeEntity(src, dst)) continue;
    }

    const unsigned char c = static_cast<unsigned char>(*src);
    if (isspace(c)) {
      pendingSpace = dst != text;
      ++src;
      continue;
    }
    if (c < 0x20 && c != '\t' && c != '\n' && c != '\r') {
      ++src;
      continue;
    }
    if (pendingSpace && dst != text && dst[-1] != ' ') *dst++ = ' ';
    pendingSpace = false;
    *dst++ = *src++;
  }
  while (dst > text && dst[-1] == ' ') --dst;
  *dst = '\0';

  // A few feeds double-escape HTML entities (e.g. &amp;eacute;). A second
  // cleaning pass resolves those without reintroducing markup.
  if (strstr(text, "&amp;") || strstr(text, "&#")) {
    src = text;
    dst = text;
    while (*src) {
      if (*src == '&' && consumeEntity(src, dst)) continue;
      *dst++ = *src++;
    }
    *dst = '\0';
  }
}

void XMLCALL RssParser::startElement(void* userData, const XML_Char* name, const XML_Char** atts) {
  auto* self = static_cast<RssParser*>(userData);

  if (localNameEquals(name, "item") || localNameEquals(name, "entry")) {
    self->inItem = true;
    self->atomEntry = localNameEquals(name, "entry");
    self->inTitle = self->inLinkText = self->inSummary = self->inPublished = false;
    self->resetCurrentItem();
    return;
  }
  if (!self->inItem) return;

  if (localNameEquals(name, "title")) {
    self->inTitle = true;
    return;
  }

  if (localNameEquals(name, "link")) {
    const char* href = findAttribute(atts, "href");
    if (href) {
      const char* rel = findAttribute(atts, "rel");
      if (self->currentItem.link[0] == '\0' || !rel || strcmp(rel, "alternate") == 0) {
        assignBounded(self->currentItem.link, RSS_LINK_CAPACITY, self->linkLength, href);
      }
    } else if (!self->atomEntry) {
      self->inLinkText = true;
    }
    return;
  }

  uint8_t priority = 0;
  if (localNameEquals(name, "description")) priority = 1;
  else if (localNameEquals(name, "summary")) priority = 2;
  else if (localNameEquals(name, "content") || localNameEquals(name, "encoded")) priority = 3;
  if (priority > 0) {
    self->activeSummaryPriority = priority;
    if (priority > self->selectedSummaryPriority) {
      self->selectedSummaryPriority = priority;
      self->summaryLength = 0;
      self->currentItem.summary[0] = '\0';
      self->inSummary = true;
    } else {
      self->inSummary = priority == self->selectedSummaryPriority;
    }
    return;
  }

  if (localNameEquals(name, "pubDate") || localNameEquals(name, "published") || localNameEquals(name, "updated") ||
      localNameEquals(name, "date")) {
    if (self->currentItem.published[0] == '\0') self->inPublished = true;
  }
}

void XMLCALL RssParser::endElement(void* userData, const XML_Char* name) {
  auto* self = static_cast<RssParser*>(userData);

  if (localNameEquals(name, "item") || localNameEquals(name, "entry")) {
    self->commitCurrentItem();
    self->inItem = false;
    self->atomEntry = false;
    self->inTitle = self->inLinkText = self->inSummary = self->inPublished = false;
    return;
  }
  if (!self->inItem) return;

  if (localNameEquals(name, "title")) {
    self->inTitle = false;
  } else if (localNameEquals(name, "link")) {
    self->inLinkText = false;
  } else if (localNameEquals(name, "description") || localNameEquals(name, "summary") || localNameEquals(name, "content") ||
             localNameEquals(name, "encoded")) {
    self->inSummary = false;
    self->activeSummaryPriority = 0;
  } else if (localNameEquals(name, "pubDate") || localNameEquals(name, "published") ||
             localNameEquals(name, "updated") || localNameEquals(name, "date")) {
    self->inPublished = false;
  }
}

void XMLCALL RssParser::characterData(void* userData, const XML_Char* data, const int len) {
  auto* self = static_cast<RssParser*>(userData);
  if (!self->inItem || !data || len <= 0) return;
  const size_t length = static_cast<size_t>(len);
  if (self->inTitle) {
    appendBounded(self->currentItem.title, RSS_TITLE_CAPACITY, self->titleLength, data, length);
  } else if (self->inLinkText) {
    appendBounded(self->currentItem.link, RSS_LINK_CAPACITY, self->linkLength, data, length);
  } else if (self->inSummary && self->activeSummaryPriority == self->selectedSummaryPriority) {
    appendBounded(self->currentItem.summary, RSS_SUMMARY_CAPACITY, self->summaryLength, data, length);
  } else if (self->inPublished) {
    appendBounded(self->currentItem.published, RSS_PUBLISHED_CAPACITY, self->publishedLength, data, length);
  }
}
