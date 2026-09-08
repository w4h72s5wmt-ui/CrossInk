from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()

header = replace_once(
    header,
    "  static constexpr size_t FEED_CONFIG_MAX_BYTES = 4096;\n",
    "  static constexpr size_t FEED_CONFIG_MAX_BYTES = 4096;\n  static constexpr size_t LIST_META_CAPACITY = 64;\n",
    "RSS list metadata capacity",
)

header = replace_once(
    header,
    """  HeapByteBuffer feedStorage;
  HeapByteBuffer listItemStorage;
  HeapByteBuffer displayOrderStorage;
""",
    """  HeapByteBuffer feedStorage;
  HeapByteBuffer listItemStorage;
  HeapByteBuffer listMetaStorage;
  HeapByteBuffer displayOrderStorage;
""",
    "RSS list metadata PSRAM storage",
)

header = replace_once(
    header,
    """  RssItem* feedItems = nullptr;
  freeink::ui::ListItem* listItems = nullptr;
  uint16_t* displayOrder = nullptr;
""",
    """  RssItem* feedItems = nullptr;
  freeink::ui::ListItem* listItems = nullptr;
  char* listMetaText = nullptr;
  uint16_t* displayOrder = nullptr;
""",
    "RSS list metadata pointer",
)

header_path.write_text(header)


cpp_path = Path("src/activities/home/RssNewsActivity.cpp")
cpp = cpp_path.read_text()

# Compact RSS/Atom dates to a stable French-style DD/MM/YYYY display. We keep
# the original published string untouched for sorting and cache persistence.
date_helper = r'''bool formatPublishedDate(const char* value, char* out, const size_t outSize) {
  if (!out || outSize == 0) return false;
  out[0] = '\0';
  if (!value || !value[0]) return false;

  int year = 0;
  int month = 0;
  int day = 0;
  if (std::sscanf(value, "%4d-%2d-%2d", &year, &month, &day) == 3) {
    if (year >= 1970 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      std::snprintf(out, outSize, "%02d/%02d/%04d", day, month, year);
      return true;
    }
  }

  char monthText[4] = {};
  int matched = std::sscanf(value, "%*3s, %2d %3s %4d", &day, monthText, &year);
  if (matched < 3) matched = std::sscanf(value, "%2d %3s %4d", &day, monthText, &year);
  if (matched >= 3) {
    month = monthNumber(monthText);
    if (year >= 1970 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      std::snprintf(out, outSize, "%02d/%02d/%04d", day, month, year);
      return true;
    }
  }
  return false;
}

'''
cpp = replace_once(
    cpp,
    "Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {\n",
    date_helper + "Rect sortTouchRect(const GfxRenderer& renderer, const MappedInputManager& input) {\n",
    "RSS compact published date helper",
)

cpp = replace_once(
    cpp,
    """  displayOrder = nullptr;
  listItems = nullptr;
  feedItems = nullptr;
  articles = nullptr;
  displayOrderStorage.reset();
  listItemStorage.reset();
  feedStorage.reset();
  articleStorage.reset();
""",
    """  displayOrder = nullptr;
  listMetaText = nullptr;
  listItems = nullptr;
  feedItems = nullptr;
  articles = nullptr;
  displayOrderStorage.reset();
  listMetaStorage.reset();
  listItemStorage.reset();
  feedStorage.reset();
  articleStorage.reset();
""",
    "RSS release list metadata storage",
)

# Anchor the insertion to the list-item allocation block. The generated RSS
# source has more than one displayOrderStorage check, so matching that line on
# its own is intentionally avoided.
cpp = replace_once(
    cpp,
    """  } else if (!listItems) {
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
  }

  if (!displayOrderStorage) {
""",
    """  } else if (!listItems) {
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
  }

  if (!listMetaStorage) {
    listMetaStorage = allocateRssBuffer(MAX_ARTICLES * LIST_META_CAPACITY);
    if (!listMetaStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list metadata");
      return false;
    }
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
    std::memset(listMetaText, 0, MAX_ARTICLES * LIST_META_CAPACITY);
  } else if (!listMetaText) {
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
  }

  if (!displayOrderStorage) {
""",
    "RSS allocate list metadata in PSRAM",
)

# News list hierarchy: full-width title, then one compact metadata line. The
# source no longer consumes the right-hand value column and the raw RFC/ISO date
# is never rendered directly.
cpp = replace_once(
    cpp,
    """    item.label = article.item.title;
    item.subtitle = article.item.published[0] ? article.item.published : nullptr;
    item.value = sources[article.sourceIndex].name.c_str();
    item.actionValue = static_cast<int16_t>(i + 1);
""",
    r'''    item.label = article.item.title;
    char* meta = listMetaText + i * LIST_META_CAPACITY;
    char dateText[16] = {};
    if (formatPublishedDate(article.item.published, dateText, sizeof(dateText))) {
      std::snprintf(meta, LIST_META_CAPACITY, "%s - %s", sources[article.sourceIndex].name.c_str(), dateText);
    } else {
      std::snprintf(meta, LIST_META_CAPACITY, "%s", sources[article.sourceIndex].name.c_str());
    }
    item.subtitle = meta;
    item.value = nullptr;
    item.actionValue = static_cast<int16_t>(i + 1);
''',
    "RSS clean list row hierarchy",
)

cpp = replace_once(
    cpp,
    """  listItems[0].label = tr(STR_UPDATE);
  listItems[0].value = "RSS";
  listItems[0].actionValue = 0;
""",
    """  listItems[0].label = tr(STR_UPDATE);
  listItems[0].subtitle = nullptr;
  listItems[0].value = nullptr;
  listItems[0].actionValue = 0;
""",
    "RSS clean refresh row",
)

cpp = replace_once(
    cpp,
    """  props.valueInset = 8;
  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);
  visibleRows = rows > 0 ? rows : 1;
""",
    """  props.valueInset = 0;
  const auto rows = configureUiList(props, screen.theme(), screen.body(), UiListRowType::WithSubtitle);
  // Strong title / quiet metadata. Keep one title line for deterministic row
  // height and button navigation; removing the value column gives it the full
  // usable width instead of squeezing it between source/date decorations.
  props.labelText.bold = true;
  props.labelText.maxLines = 1;
  props.subtitleText.maxLines = 1;
  props.balanceWrappedLabelWithValue = false;
  visibleRows = rows > 0 ? rows : 1;
""",
    "RSS list typography hierarchy",
)

# Article header: title uses the same title font it was wrapped with, and source
# + compact date share one metadata line instead of consuming two rows.
cpp = replace_once(
    cpp,
    """  fui::TextStyle titleStyle = theme.bodyText;
  fui::TextStyle bodyStyle = theme.bodyText;
  fui::TextStyle metaStyle = theme.smallText;
""",
    """  fui::TextStyle titleStyle = theme.titleText;
  titleStyle.bold = true;
  fui::TextStyle bodyStyle = theme.bodyText;
  fui::TextStyle metaStyle = theme.smallText;
""",
    "RSS article title typography",
)

cpp = replace_once(
    cpp,
    """  screen.spacer(theme.spaceSm);
  if (screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceSm), sources[article.sourceIndex].name.c_str(), metaStyle);
  }
  if (article.item.published[0] && screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceMd), article.item.published, metaStyle);
  }
""",
    r'''  screen.spacer(theme.spaceXs);
  char articleDate[16] = {};
  char metaLine[96] = {};
  if (formatPublishedDate(article.item.published, articleDate, sizeof(articleDate))) {
    std::snprintf(metaLine, sizeof(metaLine), "%s - %s", sources[article.sourceIndex].name.c_str(), articleDate);
  } else {
    std::snprintf(metaLine, sizeof(metaLine), "%s", sources[article.sourceIndex].name.c_str());
  }
  if (screen.body().height >= metaHeight) {
    screen.target().text(screen.takeTop(metaHeight, theme.spaceSm), metaLine, metaStyle);
  }
  if (screen.body().height >= 1) {
    const fui::Rect divider = screen.takeTop(1, theme.spaceMd);
    screen.target().fill(divider, fui::Paint::solid(fui::Color::Black));
  }
''',
    "RSS compact article metadata line",
)

cpp = replace_once(
    cpp,
    "articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 4);",
    "articleTitleLines = renderer.wrappedText(scale.titleFontId, article.item.title, maxWidth, 3);",
    "RSS cap article title to three lines",
)

if "item.subtitle = article.item.published" in cpp:
    raise RuntimeError("RSS list still renders raw published timestamps")
if "item.value = sources[article.sourceIndex].name.c_str()" in cpp:
    raise RuntimeError("RSS list source still squeezes the title value column")
if "fui::TextStyle titleStyle = theme.titleText;" not in cpp:
    raise RuntimeError("RSS article title hierarchy missing")
if "formatPublishedDate(article.item.published" not in cpp:
    raise RuntimeError("RSS compact date formatting missing")
if "listMetaStorage = allocateRssBuffer(MAX_ARTICLES * LIST_META_CAPACITY);" not in cpp:
    raise RuntimeError("RSS compact metadata PSRAM allocation missing")

cpp_path.write_text(cpp)
print("Applied cleaner RSS list hierarchy, compact dates, and article header formatting.")
