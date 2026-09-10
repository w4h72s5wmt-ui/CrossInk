// RSS-local HTML extraction. Included inside RssArticleCache's private namespace.
// All parsing uses bounded views into the existing HTML buffer: no DOM or heap.

bool htmlSpace(const char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f';
}

bool htmlEquals(const char* data, const size_t length, const char* literal) {
  const size_t n = std::strlen(literal);
  if (length != n) return false;
  for (size_t i = 0; i < n; ++i) {
    if (!asciiEqual(data[i], literal[i])) return false;
  }
  return true;
}

// HTML '>' inside a quoted attribute does not terminate the tag.
size_t htmlTagEnd(const char* html, const size_t length, const size_t start) {
  char quote = 0;
  for (size_t i = start + 1; i < length; ++i) {
    const char c = html[i];
    if (quote) {
      if (c == quote) quote = 0;
    } else if (c == '\'' || c == '"') {
      quote = c;
    } else if (c == '>') {
      return i;
    }
  }
  return std::string::npos;
}

bool noiseIdentity(const char* token, const size_t length) {
  // Whole component names, not arbitrary substrings such as "has-sidebar" or
  // "container-with-sidebar". Ambiguous paywall/promo/content modifiers are
  // deliberately not interpreted as instructions to discard an entire body.
  static constexpr const char* NAMES[] = {
      "ad", "ads", "advert", "advertisement", "advertising", "publicite",
      "ad-container", "ad_container", "ad-slot", "adslot", "native-ad",
      "outbrain", "taboola", "sidebar", "sidebar-content-container", "breadcrumb", "breadcrumbs",
      "social", "share", "sharing", "share-buttons", "social-share",
      "newsletter", "newsletter-box", "newsletter-form", "newsletter-signup", "newsletter-container",
      "promo-container", "promo-box", "promo-banner", "article-footer", "article-comments",
      "cookie-banner", "cookie-consent",
      "consent-banner", "comments", "comment-list", "comment-form",
      "related", "related-posts", "related-articles", "recommendations",
      "most-read", "mostread", "read-more", "readmore", "also-read",
  };
  for (const char* name : NAMES) {
    const size_t n = std::strlen(name);
    if (length < n || !htmlEquals(token, n, name)) continue;
    if (length == n) return true;
    // BEM elements/modifiers and numbered component IDs, not suffix matches.
    if (length > n + 2 && ((token[n] == '_' && token[n + 1] == '_') ||
                          (token[n] == '-' && token[n + 1] == '-'))) return true;
    if (length > n + 1 && (token[n] == '-' || token[n] == '_')) {
      bool numeric = true;
      for (size_t i = n + 1; i < length; ++i) numeric &= token[i] >= '0' && token[i] <= '9';
      if (numeric) return true;
    }
  }
  static constexpr const char* PREFIXES[] = {"optidigital-adslot-", "div-gpt-ad-"};
  for (const char* prefix : PREFIXES) {
    const size_t n = std::strlen(prefix);
    if (length > n && htmlEquals(token, n, prefix)) return true;
  }
  return false;
}

bool isNoiseContainer(const char* name, const char* html, const size_t start, const size_t end) {
  if (isAlwaysSkippedTag(name)) return true;
  if (!tagEquals(name, "div") && !tagEquals(name, "section") && !tagEquals(name, "ul") &&
      !tagEquals(name, "ol") && !tagEquals(name, "article")) return false;

  size_t pos = start + 1;
  while (pos < end && !htmlSpace(html[pos]) && html[pos] != '/') ++pos; // tag name
  while (pos < end) {
    while (pos < end && (htmlSpace(html[pos]) || html[pos] == '/')) ++pos;
    const size_t key = pos;
    while (pos < end && !htmlSpace(html[pos]) && html[pos] != '=' && html[pos] != '/') ++pos;
    const size_t keyLength = pos - key;
    if (keyLength == 0) { ++pos; continue; }
    while (pos < end && htmlSpace(html[pos])) ++pos;
    if (pos == end || html[pos] != '=') continue; // boolean attribute
    ++pos;
    while (pos < end && htmlSpace(html[pos])) ++pos;
    char quote = 0;
    if (pos < end && (html[pos] == '\'' || html[pos] == '"')) quote = html[pos++];
    const size_t value = pos;
    while (pos < end && (quote ? html[pos] != quote : !htmlSpace(html[pos]))) ++pos;
    const size_t valueEnd = pos;
    if (quote && pos < end) ++pos;
    const bool classes = htmlEquals(html + key, keyLength, "class");
    const bool id = htmlEquals(html + key, keyLength, "id");
    if (!classes && !id) continue; // never inspect URLs, data-*, titles, style...
    if (id) {
      if (noiseIdentity(html + value, valueEnd - value)) return true;
    } else {
      size_t token = value;
      while (token < valueEnd) {
        while (token < valueEnd && htmlSpace(html[token])) ++token;
        size_t next = token;
        while (next < valueEnd && !htmlSpace(html[next])) ++next;
        if (noiseIdentity(html + token, next - token)) return true;
        token = next;
      }
    }
  }
  return false;
}

struct HtmlTag {
  size_t start = 0;
  size_t end = 0;
  char name[24] = {};
  bool closing = false;
  bool selfClosing = false;
};

bool nextHtmlTag(const char* html, const size_t length, size_t& pos, HtmlTag& tag) {
  while (pos < length) {
    if (html[pos] != '<') { ++pos; continue; }
    if (startsWithInsensitive(html, length, pos, "<!--")) {
      const size_t end = findInsensitive(html, length, "-->", pos + 4);
      pos = end == std::string::npos ? length : end + 3;
      continue;
    }
    tag.start = pos;
    tag.end = htmlTagEnd(html, length, pos);
    if (tag.end == std::string::npos) { pos = length; return false; }
    pos = tag.end + 1;
    if (parseTagName(html, tag.start, tag.end, tag.name, sizeof(tag.name),
                     tag.closing, tag.selfClosing) > 0) return true;
  }
  return false;
}

bool htmlRawText(const char* name) {
  return tagEquals(name, "script") || tagEquals(name, "style") || tagEquals(name, "textarea") ||
         tagEquals(name, "title");
}

// Raw-text elements may contain '<div>' or '</article>' in JS/CSS strings.
// Only their own real closing tag is meaningful to the HTML parser.
size_t skipHtmlRaw(const char* html, const size_t length, const HtmlTag& open) {
  char marker[28];
  std::snprintf(marker, sizeof(marker), "</%s", open.name);
  size_t pos = open.end + 1;
  while ((pos = findInsensitive(html, length, marker, pos)) != std::string::npos) {
    const size_t after = pos + std::strlen(marker);
    if (after < length && (htmlSpace(html[after]) || html[after] == '>' || html[after] == '/')) {
      const size_t end = htmlTagEnd(html, length, pos);
      return end == std::string::npos ? length : end + 1;
    }
    ++pos;
  }
  return length;
}

size_t htmlElementEnd(const char* html, const size_t length, const HtmlTag& open, size_t& after) {
  size_t pos = open.end + 1;
  size_t depth = 1;
  HtmlTag tag;
  while (nextHtmlTag(html, length, pos, tag)) {
    if (!tag.closing && htmlRawText(tag.name)) {
      pos = skipHtmlRaw(html, length, tag);
      continue;
    }
    if (!tagEquals(tag.name, open.name)) continue;
    if (tag.closing) {
      if (--depth == 0) { after = pos; return tag.start; }
    } else if (!tag.selfClosing) {
      ++depth;
    }
  }
  after = length;
  return length;
}

// Cheap visibility score used only to choose the page's editorial root. It
// reuses the bounded parser and skips the same noise/raw subtrees as extraction,
// but never allocates or decodes text. This prevents teaser <article> cards from
// winning simply because they appear before the real story.
size_t readableCandidateScore(const char* html, const size_t begin, const size_t end) {
  size_t score = 0;
  size_t pos = begin;
  while (pos < end) {
    if (html[pos] == '<') {
      if (startsWithInsensitive(html, end, pos, "<!--")) {
        const size_t close = findInsensitive(html, end, "-->", pos + 4);
        pos = close == std::string::npos ? end : close + 3;
        continue;
      }
      HtmlTag tag;
      tag.start = pos;
      tag.end = htmlTagEnd(html, end, pos);
      if (tag.end == std::string::npos) break;
      const size_t next = tag.end + 1;
      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {
        pos = next;
        continue;
      }
      if (!tag.closing && htmlRawText(tag.name)) {
        pos = skipHtmlRaw(html, end, tag);
        continue;
      }
      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        continue;
      }
      pos = next;
      continue;
    }
    if (html[pos] == '&') {
      // One entity is roughly one visible character. Skip a short valid-looking
      // entity so long encoded strings do not inflate a teaser's score.
      const size_t limit = std::min(end, pos + 12);
      size_t next = pos + 1;
      while (next < limit && html[next] != ';' && html[next] != '<' && html[next] != '&' &&
             !htmlSpace(html[next])) ++next;
      pos = next < limit && html[next] == ';' ? next + 1 : pos + 1;
      ++score;
    } else {
      const unsigned char c = static_cast<unsigned char>(html[pos++]);
      if (c >= 0x20 && !htmlSpace(static_cast<char>(c))) ++score;
    }
    if (score >= MAX_TEXT_BYTES * 2U) return score;
  }
  return score;
}

void readableHtmlRange(const char* html, const size_t length, size_t& begin, size_t& end) {
  begin = 0;
  end = length;
  static constexpr size_t STRONG_ARTICLE_SCORE = 512;

  HtmlTag firstMain, firstBody, bestArticle, tag;
  bool haveMain = false;
  bool haveBody = false;
  bool haveArticle = false;
  size_t bestArticleEnd = 0;
  size_t bestArticleScore = 0;
  size_t pos = 0;
  while (nextHtmlTag(html, length, pos, tag)) {
    if (tag.closing) continue;
    if (htmlRawText(tag.name)) { pos = skipHtmlRaw(html, length, tag); continue; }
    if (!haveMain && tagEquals(tag.name, "main")) { firstMain = tag; haveMain = true; }
    if (!haveBody && tagEquals(tag.name, "body")) { firstBody = tag; haveBody = true; }
    if (!tagEquals(tag.name, "article") || tag.selfClosing ||
        isNoiseContainer(tag.name, html, tag.start, tag.end)) continue;

    size_t after = length;
    const size_t candidateEnd = htmlElementEnd(html, length, tag, after);
    if (candidateEnd <= tag.end + 1) continue;
    const size_t score = readableCandidateScore(html, tag.end + 1, candidateEnd);
    if (!haveArticle || score > bestArticleScore) {
      bestArticle = tag;
      bestArticleEnd = candidateEnd;
      bestArticleScore = score;
      haveArticle = true;
    }
  }

  // A sizeable <article> is the safest root. Science & Vie/Futura pages also
  // contain short teaser <article> cards before the story; those stay below the
  // strong threshold and let <main> compete instead of being cached as a body.
  if (haveArticle && bestArticleScore >= STRONG_ARTICLE_SCORE) {
    begin = bestArticle.end + 1;
    end = bestArticleEnd;
    return;
  }

  if (haveMain && !firstMain.selfClosing) {
    size_t after = length;
    const size_t mainEnd = htmlElementEnd(html, length, firstMain, after);
    if (mainEnd > firstMain.end + 1) {
      const size_t mainScore = readableCandidateScore(html, firstMain.end + 1, mainEnd);
      if (mainScore >= STRONG_ARTICLE_SCORE && (!haveArticle || mainScore > bestArticleScore)) {
        begin = firstMain.end + 1;
        end = mainEnd;
        return;
      }
    }
  }

  if (haveArticle && bestArticleScore >= MIN_EXTRACTED_TEXT) {
    begin = bestArticle.end + 1;
    end = bestArticleEnd;
    return;
  }

  if (haveMain && !firstMain.selfClosing) {
    size_t after = length;
    const size_t mainEnd = htmlElementEnd(html, length, firstMain, after);
    if (mainEnd > firstMain.end + 1) {
      begin = firstMain.end + 1;
      end = mainEnd;
      return;
    }
  }

  if (haveBody && !firstBody.selfClosing) {
    size_t after = length;
    const size_t bodyEnd = htmlElementEnd(html, length, firstBody, after);
    begin = firstBody.end + 1;
    end = bodyEnd > begin ? bodyEnd : length;
  }
}

bool extractReadableText(const char* html, const size_t htmlLength, char* text, size_t& textLength) {
  textLength = 0;
  if (!html || !text || htmlLength == 0) return false;
  size_t begin, end;
  readableHtmlRange(html, htmlLength, begin, end);
  size_t pos = begin;
  while (pos < end && textLength < MAX_TEXT_BYTES) {
    if (html[pos] == '<') {
      if (startsWithInsensitive(html, end, pos, "<!--")) {
        const size_t close = findInsensitive(html, end, "-->", pos + 4);
        pos = close == std::string::npos ? end : close + 3;
        continue;
      }
      HtmlTag tag;
      tag.start = pos;
      tag.end = htmlTagEnd(html, end, pos);
      if (tag.end == std::string::npos) break;
      const size_t next = tag.end + 1;
      if (parseTagName(html, pos, tag.end, tag.name, sizeof(tag.name), tag.closing, tag.selfClosing) == 0) {
        pos = next;
        continue;
      }
      if (!tag.closing && htmlRawText(tag.name)) {
        pos = skipHtmlRaw(html, end, tag);
        continue;
      }
      if (!tag.closing && isNoiseContainer(tag.name, html, tag.start, tag.end)) {
        if (tag.selfClosing) pos = next;
        else htmlElementEnd(html, end, tag, pos);
        continue;
      }
      if (tagEquals(tag.name, "br") || tagEquals(tag.name, "tr") || tagEquals(tag.name, "dt") || tagEquals(tag.name, "dd")) {
        appendLineBreak(text, textLength);
      } else if (tagEquals(tag.name, "li")) {
        appendLineBreak(text, textLength);
        if (!tag.closing) { appendChar(text, textLength, '-'); appendChar(text, textLength, ' '); }
      } else if (tagEquals(tag.name, "td") || tagEquals(tag.name, "th")) {
        appendSpace(text, textLength);
      } else if (isParagraphTag(tag.name)) {
        appendParagraphBreak(text, textLength);
      }
      pos = next;
      continue;
    }
    if (html[pos] == '&') { pos = decodeEntity(html, end, pos, text, textLength); continue; }
    const unsigned char c = static_cast<unsigned char>(html[pos++]);
    if (htmlSpace(static_cast<char>(c))) appendSpace(text, textLength);
    else if (c >= 0x20) appendChar(text, textLength, static_cast<char>(c));
  }
  const bool atCapacity = textLength >= MAX_TEXT_BYTES;
  while (textLength > 0 && (text[textLength - 1] == ' ' || text[textLength - 1] == '\n')) --textLength;
  text[textLength] = '\0';
  return !atCapacity && textLength >= MIN_EXTRACTED_TEXT;
}
