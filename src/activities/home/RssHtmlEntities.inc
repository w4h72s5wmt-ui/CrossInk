// RSS-local HTML entity decoder. Included inside RssArticleCache's private namespace.
// Keep UTF-8 end-to-end: publishers frequently encode French accents and punctuation
// as named or numeric HTML entities even when the page itself is UTF-8.

bool appendUtf8Codepoint(char* out, size_t& outLength, uint32_t cp) {
  if (cp == 0x00A0) {
    appendSpace(out, outLength);
    return true;
  }
  if (cp == 0 || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return false;

  uint8_t bytes[4];
  size_t count = 0;
  if (cp <= 0x7F) {
    bytes[count++] = static_cast<uint8_t>(cp);
  } else if (cp <= 0x7FF) {
    bytes[count++] = static_cast<uint8_t>(0xC0U | (cp >> 6));
    bytes[count++] = static_cast<uint8_t>(0x80U | (cp & 0x3FU));
  } else if (cp <= 0xFFFF) {
    bytes[count++] = static_cast<uint8_t>(0xE0U | (cp >> 12));
    bytes[count++] = static_cast<uint8_t>(0x80U | ((cp >> 6) & 0x3FU));
    bytes[count++] = static_cast<uint8_t>(0x80U | (cp & 0x3FU));
  } else {
    bytes[count++] = static_cast<uint8_t>(0xF0U | (cp >> 18));
    bytes[count++] = static_cast<uint8_t>(0x80U | ((cp >> 12) & 0x3FU));
    bytes[count++] = static_cast<uint8_t>(0x80U | ((cp >> 6) & 0x3FU));
    bytes[count++] = static_cast<uint8_t>(0x80U | (cp & 0x3FU));
  }

  if (outLength + count > MAX_TEXT_BYTES) {
    outLength = MAX_TEXT_BYTES;
    return false;
  }
  for (size_t i = 0; i < count; ++i) out[outLength++] = static_cast<char>(bytes[i]);
  return true;
}

struct NamedHtmlEntity {
  const char* name;
  uint32_t codepoint;
};

uint32_t namedHtmlEntityCodepoint(const std::string& entity) {
  static constexpr NamedHtmlEntity ENTITIES[] = {
      {"amp", '&'}, {"lt", '<'}, {"gt", '>'}, {"quot", '"'}, {"apos", '\''},
      {"nbsp", 0x00A0}, {"iexcl", 0x00A1}, {"cent", 0x00A2}, {"pound", 0x00A3},
      {"yen", 0x00A5}, {"sect", 0x00A7}, {"copy", 0x00A9}, {"laquo", 0x00AB},
      {"reg", 0x00AE}, {"deg", 0x00B0}, {"plusmn", 0x00B1}, {"micro", 0x00B5},
      {"para", 0x00B6}, {"middot", 0x00B7}, {"raquo", 0x00BB},
      {"Agrave", 0x00C0}, {"Aacute", 0x00C1}, {"Acirc", 0x00C2}, {"Atilde", 0x00C3},
      {"Auml", 0x00C4}, {"Aring", 0x00C5}, {"AElig", 0x00C6}, {"Ccedil", 0x00C7},
      {"Egrave", 0x00C8}, {"Eacute", 0x00C9}, {"Ecirc", 0x00CA}, {"Euml", 0x00CB},
      {"Igrave", 0x00CC}, {"Iacute", 0x00CD}, {"Icirc", 0x00CE}, {"Iuml", 0x00CF},
      {"Ntilde", 0x00D1}, {"Ograve", 0x00D2}, {"Oacute", 0x00D3}, {"Ocirc", 0x00D4},
      {"Otilde", 0x00D5}, {"Ouml", 0x00D6}, {"Oslash", 0x00D8},
      {"Ugrave", 0x00D9}, {"Uacute", 0x00DA}, {"Ucirc", 0x00DB}, {"Uuml", 0x00DC},
      {"Yacute", 0x00DD}, {"szlig", 0x00DF},
      {"agrave", 0x00E0}, {"aacute", 0x00E1}, {"acirc", 0x00E2}, {"atilde", 0x00E3},
      {"auml", 0x00E4}, {"aring", 0x00E5}, {"aelig", 0x00E6}, {"ccedil", 0x00E7},
      {"egrave", 0x00E8}, {"eacute", 0x00E9}, {"ecirc", 0x00EA}, {"euml", 0x00EB},
      {"igrave", 0x00EC}, {"iacute", 0x00ED}, {"icirc", 0x00EE}, {"iuml", 0x00EF},
      {"ntilde", 0x00F1}, {"ograve", 0x00F2}, {"oacute", 0x00F3}, {"ocirc", 0x00F4},
      {"otilde", 0x00F5}, {"ouml", 0x00F6}, {"oslash", 0x00F8},
      {"ugrave", 0x00F9}, {"uacute", 0x00FA}, {"ucirc", 0x00FB}, {"uuml", 0x00FC},
      {"yacute", 0x00FD}, {"yuml", 0x00FF}, {"OElig", 0x0152}, {"oelig", 0x0153},
      {"Scaron", 0x0160}, {"scaron", 0x0161}, {"Yuml", 0x0178},
      {"ndash", 0x2013}, {"mdash", 0x2014}, {"lsquo", 0x2018}, {"rsquo", 0x2019},
      {"sbquo", 0x201A}, {"ldquo", 0x201C}, {"rdquo", 0x201D}, {"bdquo", 0x201E},
      {"bull", 0x2022}, {"hellip", 0x2026}, {"permil", 0x2030}, {"lsaquo", 0x2039},
      {"rsaquo", 0x203A}, {"euro", 0x20AC}, {"trade", 0x2122},
  };
  for (const auto& candidate : ENTITIES) {
    if (entity == candidate.name) return candidate.codepoint;
  }
  return 0;
}

size_t decodeEntityUtf8(const char* data, const size_t length, const size_t pos, char* out, size_t& outLength) {
  const size_t semicolon = [&]() {
    const size_t maxEnd = std::min(length, pos + 32);
    for (size_t i = pos + 1; i < maxEnd; ++i) {
      if (data[i] == ';') return i;
      if (data[i] == '<' || data[i] == '&' || htmlSpace(data[i])) break;
    }
    return std::string::npos;
  }();
  if (semicolon == std::string::npos) {
    appendChar(out, outLength, '&');
    return pos + 1;
  }

  const std::string entity(data + pos + 1, semicolon - pos - 1);
  bool decoded = false;
  if (!entity.empty() && entity[0] == '#') {
    const bool hex = entity.size() > 2 && (entity[1] == 'x' || entity[1] == 'X');
    const char* digits = entity.c_str() + (hex ? 2 : 1);
    char* end = nullptr;
    const unsigned long value = std::strtoul(digits, &end, hex ? 16 : 10);
    if (digits != end && end && *end == '\0' && value <= 0x10FFFFUL) {
      decoded = appendUtf8Codepoint(out, outLength, static_cast<uint32_t>(value));
    }
  } else {
    const uint32_t codepoint = namedHtmlEntityCodepoint(entity);
    if (codepoint != 0) decoded = appendUtf8Codepoint(out, outLength, codepoint);
  }

  if (!decoded && outLength < MAX_TEXT_BYTES) {
    const size_t bytes = semicolon - pos + 1;
    if (outLength + bytes > MAX_TEXT_BYTES) {
      outLength = MAX_TEXT_BYTES;
    } else {
      std::memcpy(out + outLength, data + pos, bytes);
      outLength += bytes;
    }
  }
  return semicolon + 1;
}
