from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))


def replace_between(path: str, start_marker: str, end_marker: str, replacement: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise SystemExit(f"{label}: section markers missing")
    p.write_text(text[:start] + replacement + text[end:])


# Top-level exits: return to Home. Internal Back navigation stays unchanged.
replace_once(
    "src/activities/home/MinesweeperActivity.cpp",
    """void MinesweeperActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
    return;
  }
""",
    """void MinesweeperActivity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    onGoHome();
    return;
  }
""",
    "Minesweeper top-level Home exit",
)

replace_once(
    "src/activities/home/Game2048Activity.cpp",
    """void Game2048Activity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    finish();
    return;
  }
""",
    """void Game2048Activity::loopMenu() {
  const Rect header = headerRect(renderer, mappedInput);
  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||
      mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    mappedInput.suppressNextBackRelease();
    onGoHome();
    return;
  }
""",
    "2048 top-level Home exit",
)

replace_once(
    "src/activities/home/NotesActivityCore.inc",
    """    if (pointInRect(backRect, tx, ty)) {
      finish();
      return;
    }
""",
    """    if (pointInRect(backRect, tx, ty)) {
      onGoHome();
      return;
    }
""",
    "Notes touch Home exit",
)
replace_once(
    "src/activities/home/NotesActivityCore.inc",
    """  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
    finish();
  }
}

void NotesActivity::render""",
    """  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {
    onGoHome();
  }
}

void NotesActivity::render""",
    "Notes hardware Home exit",
)

# Scope RSS exit edits strictly to RssNewsActivity::loop().
rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()
loop_start = rss.find("void RssNewsActivity::loop() {\n")
loop_end = rss.find("\nbool RssNewsActivity::preventAutoSleep()", loop_start)
if loop_start < 0 or loop_end < 0:
    raise SystemExit("RSS loop section missing")
loop = rss[loop_start:loop_end]
if loop.count("finish();") != 2:
    raise SystemExit(f"RSS loop expected 2 top-level finish calls, found {loop.count('finish();')}")
loop = loop.replace("finish();", "onGoHome();")
rss = rss[:loop_start] + loop + rss[loop_end:]
old = """    // Keep the post-WiFi reboot that defragments the ESP network heap, but
    // resume with the Home application menu open on RSS instead of plain Home.
    silentRestartAfterNetworkToRssMenu();
"""
new = """    // Keep the post-WiFi reboot that defragments the ESP network heap and
    // resume at the normal Home screen, like native applications.
    silentRestartAfterNetwork();
"""
if rss.count(old) != 1:
    raise SystemExit("RSS post-network restart anchor mismatch")
rss_path.write_text(rss.replace(old, new, 1))

# Remove our now-obsolete RSS host bridge from CrossInk core.
replace_once(
    "src/activities/ActivityManager.h",
    "enum class HomeMenuItem { NONE, FILE_BROWSER, RECENTS, OPDS_BROWSER, FILE_TRANSFER, SETTINGS_MENU, RSS_NEWS };\n",
    "enum class HomeMenuItem { NONE, FILE_BROWSER, RECENTS, OPDS_BROWSER, FILE_TRANSFER, SETTINGS_MENU };\n",
    "remove RSS HomeMenuItem bridge",
)
replace_once(
    "src/activities/home/HomeActivity.cpp",
    """    case HomeMenuItem::SETTINGS_MENU:
      return HomeMenuAction::Settings;
    case HomeMenuItem::RSS_NEWS:
      return HomeMenuAction::RssNews;
    case HomeMenuItem::NONE:
""",
    """    case HomeMenuItem::SETTINGS_MENU:
      return HomeMenuAction::Settings;
    case HomeMenuItem::NONE:
""",
    "remove RSS initial selection mapping",
)
replace_once(
    "src/activities/home/HomeActivity.cpp",
    """    if (menuIndex >= 0) {
      selectorIndex = getHomeMenuSelectionOffset(recentBooks) + menuIndex;
    }

    // Minimal/Dashboard Home normally hides its application list. A network
    // reboot cannot preserve the previous Home instance on the activity stack,
    // so explicitly reopen that list and restore the RSS selection.
    if (usesMinimalHomeInteraction()) {
      const auto minimalItems = buildMinimalMenuItems(hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings);
      const int minimalIndex = findMenuActionIndex(minimalItems, homeActionForInitialMenuItem(initialMenuItem));
      if (minimalIndex >= 0) {
        minimalMenuOpen = true;
        minimalMenuIndex = minimalIndex;
      }
    }
  }
""",
    """    if (menuIndex >= 0) {
      selectorIndex = getHomeMenuSelectionOffset(recentBooks) + menuIndex;
    }
  }
""",
    "remove RSS minimal-menu restore",
)
replace_once(
    "src/SilentRestart.h",
    "void silentRestartAfterNetwork();\nvoid silentRestartAfterNetworkToRssMenu();\nvoid silentRestartToReaderAfterNetwork(bool cleanImageBaseOnEntry = false);\n",
    "void silentRestartAfterNetwork();\nvoid silentRestartToReaderAfterNetwork(bool cleanImageBaseOnEntry = false);\n",
    "remove RSS restart declaration",
)
replace_once(
    "src/main.cpp",
    "constexpr uint32_t SILENT_REBOOT_READER_CLEAN_IMAGE_BASE = 1U << 0;\nconstexpr uint32_t SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY = 1U << 1;\nconstexpr uint32_t SILENT_REBOOT_HOME_RSS_MENU = 1U << 2;\n",
    "constexpr uint32_t SILENT_REBOOT_READER_CLEAN_IMAGE_BASE = 1U << 0;\nconstexpr uint32_t SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY = 1U << 1;\n",
    "remove RSS reboot payload bit",
)
replace_once(
    "src/main.cpp",
    """void silentRestartAfterNetwork() {
  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY, "target=home after network");
}

void silentRestartAfterNetworkToRssMenu() {
  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY | SILENT_REBOOT_HOME_RSS_MENU,
                      "target=RSS menu after network");
}

void restartToHomeAfterStorageHandoff() {
""",
    """void silentRestartAfterNetwork() {
  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY, "target=home after network");
}

void restartToHomeAfterStorageHandoff() {
""",
    "remove RSS restart implementation",
)
replace_once(
    "src/main.cpp",
    """  } else if (resume == BootResume::Silent) {
    // target == home (or reader with no open book): land on home — don't fall
    // through to the sleep-wake "resume reader" logic, which fires on stale
    // openEpubPath + lastSleepFromReader from a prior session. RSS can request
    // its application-menu selection after the network-defragmentation reboot.
    const HomeMenuItem resumeMenuItem =
        (snapshotPayload & SILENT_REBOOT_HOME_RSS_MENU) != 0 ? HomeMenuItem::RSS_NEWS : HomeMenuItem::NONE;
    activityManager.goHome(resumeMenuItem, true);
""",
    """  } else if (resume == BootResume::Silent) {
    // target == home (or reader with no open book): land on home — don't fall
    // through to the sleep-wake "resume reader" logic, which fires on stale
    // openEpubPath + lastSleepFromReader from a prior session.
    activityManager.goHome(HomeMenuItem::NONE, true);
""",
    "remove RSS silent-resume routing",
)

# RSS buffers: preserve hard ceilings, allocate only what feeds.txt asks for.
header_path = Path("src/activities/home/RssNewsActivity.h")
header = header_path.read_text()
header = header.replace(
    """  // Keep the existing eight-feed memory ceiling: each source may preserve up
  // to 100 offline articles and RssItem includes a large cached body. The SD
  // configuration can contain fewer sources without increasing PSRAM usage.
""",
    """  // Hard safety ceilings stay fixed, but runtime buffers are sized from the
  // active feeds.txt limits so small configurations do not reserve the full
  // eight-feed / 100-item PSRAM envelope.
""",
    1,
)
old = "  size_t articleCount = 0;\n  size_t articleLineOffset = 0;\n"
new = "  size_t articleCount = 0;\n  size_t articleCapacity = MAX_ARTICLES;\n  size_t feedItemCapacity = FEED_ITEM_CAPACITY;\n  size_t articleLineOffset = 0;\n"
if header.count(old) != 1:
    raise SystemExit("RSS capacity fields anchor mismatch")
header_path.write_text(header.replace(old, new, 1))

rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()
ensure_start = rss.find("bool RssNewsActivity::ensureBuffers() {\n")
ensure_end = rss.find("\nvoid RssNewsActivity::loadSources() {\n", ensure_start)
if ensure_start < 0 or ensure_end < 0:
    raise SystemExit("RSS ensureBuffers section missing")
ensure_impl = """bool RssNewsActivity::ensureBuffers() {
  size_t requestedArticleCapacity = 0;
  size_t requestedFeedCapacity = 1;
  for (size_t i = 0; i < sourceCount; ++i) {
    requestedArticleCapacity += std::clamp<size_t>(sources[i].historyLimit, 1, ITEMS_PER_SOURCE);
    requestedFeedCapacity = std::max(
        requestedFeedCapacity, std::clamp<size_t>(sources[i].syncLimit, 1, FEED_ITEM_CAPACITY));
  }
  articleCapacity = std::clamp<size_t>(requestedArticleCapacity, 1, MAX_ARTICLES);
  feedItemCapacity = std::clamp<size_t>(requestedFeedCapacity, 1, FEED_ITEM_CAPACITY);
  LOG_DBG("RSS", "Runtime capacities: articles=%zu/%zu feed=%zu/%zu", articleCapacity, MAX_ARTICLES,
          feedItemCapacity, FEED_ITEM_CAPACITY);

  if (!articleStorage) {
    articleStorage = allocateRssBuffer(sizeof(CachedArticle) * articleCapacity);
    if (!articleStorage) {
      LOG_ERR("RSS", "OOM allocating article cache (%zu records)", articleCapacity);
      return false;
    }
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
    std::memset(articles, 0, sizeof(CachedArticle) * articleCapacity);
  } else if (!articles) {
    articles = reinterpret_cast<CachedArticle*>(articleStorage.get());
  }

  if (!feedStorage) {
    feedStorage = allocateRssBuffer(sizeof(RssItem) * feedItemCapacity);
    if (!feedStorage) {
      LOG_ERR("RSS", "OOM allocating feed scratch (%zu records)", feedItemCapacity);
      return false;
    }
    feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
    std::memset(feedItems, 0, sizeof(RssItem) * feedItemCapacity);
  } else if (!feedItems) {
    feedItems = reinterpret_cast<RssItem*>(feedStorage.get());
  }

  if (!listItemStorage) {
    listItemStorage = allocateRssBuffer(sizeof(fui::ListItem) * (articleCapacity + 1));
    if (!listItemStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list items");
      return false;
    }
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
    std::memset(listItems, 0, sizeof(fui::ListItem) * (articleCapacity + 1));
  } else if (!listItems) {
    listItems = reinterpret_cast<fui::ListItem*>(listItemStorage.get());
  }

  if (!listMetaStorage) {
    listMetaStorage = allocateRssBuffer(articleCapacity * LIST_META_CAPACITY);
    if (!listMetaStorage) {
      LOG_ERR("RSS", "OOM allocating RSS list metadata");
      return false;
    }
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
    std::memset(listMetaText, 0, articleCapacity * LIST_META_CAPACITY);
  } else if (!listMetaText) {
    listMetaText = reinterpret_cast<char*>(listMetaStorage.get());
  }

  if (!displayOrderStorage) {
    displayOrderStorage = allocateRssBuffer(sizeof(uint16_t) * articleCapacity);
    if (!displayOrderStorage) {
      LOG_ERR("RSS", "OOM allocating RSS sort index");
      return false;
    }
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
    std::memset(displayOrder, 0, sizeof(uint16_t) * articleCapacity);
  } else if (!displayOrder) {
    displayOrder = reinterpret_cast<uint16_t*>(displayOrderStorage.get());
  }

  return true;
}
"""
rss = rss[:ensure_start] + ensure_impl + rss[ensure_end:]

# Hash the actual capacity-affecting feed configuration too.
hash_start = rss.find("uint32_t RssNewsActivity::sourceConfigHash() const {\n")
hash_end = rss.find("\nbool RssNewsActivity::loadCache() {\n", hash_start)
if hash_start < 0 or hash_end < 0:
    raise SystemExit("RSS sourceConfigHash section missing")
hash_impl = """uint32_t RssNewsActivity::sourceConfigHash() const {
  uint32_t hash = UINT32_C(2166136261);
  const auto mix = [&hash](const char c) {
    hash ^= static_cast<uint8_t>(c);
    hash *= UINT32_C(16777619);
  };
  const auto mixLimit = [&mix](const uint16_t value) {
    mix(static_cast<char>(value & 0xffU));
    mix(static_cast<char>((value >> 8U) & 0xffU));
  };
  for (size_t i = 0; i < sourceCount; ++i) {
    for (const char c : sources[i].name) mix(c);
    mix('|');
    for (const char c : sources[i].url) mix(c);
    mix('|');
    mixLimit(sources[i].syncLimit);
    mix('|');
    mixLimit(sources[i].historyLimit);
    mix('|');
    for (const char c : sources[i].dropRules) mix(c);
    mix('|');
    for (const char c : sources[i].dropStartRules) mix(c);
    mix('|');
    for (const char c : sources[i].stopRules) mix(c);
    mix('\\n');
  }
  return hash;
}
"""
rss = rss[:hash_start] + hash_impl + rss[hash_end:]

old = """    LOG_DBG("RSS", "Purged article bodies for obsolete feed configuration");
    return false;
  }

  for (uint16_t i = 0; i < header.count; ++i) {
"""
new = """    LOG_DBG("RSS", "Purged article bodies for obsolete feed configuration");
    return false;
  }

  if (header.count > articleCapacity) {
    LOG_ERR("RSS", "RSS cache exceeds configured capacity (%u > %zu)",
            static_cast<unsigned>(header.count), articleCapacity);
    file.close();
    Storage.remove(CACHE_PATH);
    return false;
  }

  for (uint16_t i = 0; i < header.count; ++i) {
"""
if rss.count(old) != 1:
    raise SystemExit("RSS load capacity guard anchor mismatch")
rss = rss.replace(old, new, 1)

old = """  const auto keepHistoryItem = [requiresCachedBody](const RssItem& item) {
    if (!requiresCachedBody) return true;
    const std::string path = RssArticleCache::bodyPath(item);
    return Storage.exists(path.c_str());
  };
"""
new = """  const auto keepHistoryItem = [requiresCachedBody](const RssItem& item) {
    return !requiresCachedBody || RssArticleCache::hasCurrentBody(item);
  };
"""
if rss.count(old) != 1:
    raise SystemExit("RSS history body validity anchor mismatch")
rss = rss.replace(old, new, 1)
old = "  const size_t addCount = std::min(mergedCount, MAX_ARTICLES - articleCount);\n"
new = """  const size_t addCount = articleCount < articleCapacity
                              ? std::min(mergedCount, articleCapacity - articleCount)
                              : 0;
"""
if rss.count(old) != 1:
    raise SystemExit("RSS merge capacity anchor mismatch")
rss = rss.replace(old, new, 1)
old = "  std::memset(feedItems, 0, sizeof(RssItem) * FEED_ITEM_CAPACITY);\n\n  const size_t syncLimit = std::clamp<size_t>(sources[sourceIndex].syncLimit, 1, FEED_ITEM_CAPACITY);\n"
new = "  std::memset(feedItems, 0, sizeof(RssItem) * feedItemCapacity);\n\n  const size_t syncLimit = std::clamp<size_t>(sources[sourceIndex].syncLimit, 1, feedItemCapacity);\n"
if rss.count(old) != 1:
    raise SystemExit("RSS feed capacity anchor mismatch")
rss = rss.replace(old, new, 1)

# Keep simulator bounded by the same runtime capacity.
old = """  for (uint8_t sourceIndex = 0; sourceIndex < sourceCount; ++sourceIndex) {
    for (size_t sample = 0; sample < 3; ++sample) {
      CachedArticle& article = articles[articleCount++];
"""
new = """  for (uint8_t sourceIndex = 0; sourceIndex < sourceCount && articleCount < articleCapacity; ++sourceIndex) {
    for (size_t sample = 0; sample < 3 && articleCount < articleCapacity; ++sample) {
      CachedArticle& article = articles[articleCount++];
"""
if rss.count(old) != 1:
    raise SystemExit("RSS simulator capacity anchor mismatch")
rss_path.write_text(rss.replace(old, new, 1))

# One definition of a valid cached body.
replace_once(
    "src/activities/home/RssArticleCache.h",
    """std::string bodyPath(const RssItem& item);

// Removes the dedicated offline body for an article. Missing files count as
""",
    """std::string bodyPath(const RssItem& item);

// True only when the dedicated body matches the current cache format and size.
bool hasCurrentBody(const RssItem& item);

// Removes the dedicated offline body for an article. Missing files count as
""",
    "declare current-body probe",
)
cache_cpp = Path("src/activities/home/RssArticleCache.cpp")
text = cache_cpp.read_text()
if text.count('constexpr char BODY_MAGIC[] = "XRSS10\\n";') != 1:
    raise SystemExit("XRSS10 marker anchor mismatch")
text = text.replace('constexpr char BODY_MAGIC[] = "XRSS10\\n";', 'constexpr char BODY_MAGIC[] = "XRSS11\\n";', 1)
old = """  return name;
}

bool remove(const RssItem& item) {
"""
new = """  return name;
}

bool hasCurrentBody(const RssItem& item) { return bodyCacheIsCurrent(bodyPath(item)); }

bool remove(const RssItem& item) {
"""
if text.count(old) != 1:
    raise SystemExit("current-body implementation anchor mismatch")
cache_cpp.write_text(text.replace(old, new, 1))

# XRSS11 guarantees share cleanup happened on write; no compatibility pass on every read.
replace_once(
    "src/activities/home/RssArticleCachePolicy.inc",
    """      if (outText.size() == expected) {
        if (!outText.empty()) {
          const size_t cleaned = stripFigaroShareControls(&outText[0], outText.size(), item.link);
          outText.resize(cleaned);
        }
        return CacheResult::READY;
      }
""",
    """      if (outText.size() == expected) return CacheResult::READY;
""",
    "remove load-time Figaro compatibility cleaner",
)

# Update host tests for the new body generation and validity probe.
replace_once(
    "tests/rss/test_article_cache.cpp",
    """  const auto cachedCalls = H::publicCalls;
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == cachedCalls, "valid cache reused");

  reset();
  testFiles[RC::bodyPath(item)] = "XRSS9\\nAncien corps sans marqueurs de liens";
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 1, "XRSS9 pre-link-markup body invalidated");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS10\\n", 0) == 0, "XRSS10 body cache version");
""",
    """  const auto cachedCalls = H::publicCalls;
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == cachedCalls, "valid cache reused");
  check(RC::hasCurrentBody(item), "current body probe accepts XRSS11 cache");

  reset();
  testFiles[RC::bodyPath(item)] = "XRSS10\\nAncien corps nettoye par compatibilite";
  check(!RC::hasCurrentBody(item), "XRSS10 rejected by current body probe");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 1, "XRSS10 body invalidated and refetched");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS11\\n", 0) == 0, "XRSS11 body cache version");
  check(RC::hasCurrentBody(item), "refetched XRSS11 body is current");
""",
    "update RSS cache-generation tests",
)

# Final structural assertions.
checks = {
    "Minesweeper Home exit": "onGoHome();" in Path("src/activities/home/MinesweeperActivity.cpp").read_text(),
    "2048 Home exit": "onGoHome();" in Path("src/activities/home/Game2048Activity.cpp").read_text(),
    "Notes Home exit": Path("src/activities/home/NotesActivityCore.inc").read_text().count("onGoHome();") >= 2,
    "RSS Home exit": Path("src/activities/home/RssNewsActivity.cpp").read_text().count("onGoHome();") >= 2,
    "RSS bridge enum removed": "RSS_NEWS" not in Path("src/activities/ActivityManager.h").read_text(),
    "RSS special restart removed": "silentRestartAfterNetworkToRssMenu" not in Path("src/main.cpp").read_text(),
    "XRSS11 active": 'BODY_MAGIC[] = "XRSS11\\n"' in Path("src/activities/home/RssArticleCache.cpp").read_text(),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("candidate validation failed: " + ", ".join(failed))

print("Applied native Home exits and RSS runtime/cache optimizations.")
