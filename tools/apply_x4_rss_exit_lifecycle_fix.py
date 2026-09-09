from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# 1) RSS: release shared font/decompressor caches and pop back to the Home/app menu on normal Back.
rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()

rss = replace_once(
    rss,
    '#include <GfxRenderer.h>\n',
    '#include <FontCacheManager.h>\n#include <GfxRenderer.h>\n',
    "RSS FontCacheManager include",
)

rss = replace_once(
    rss,
    '''void RssNewsActivity::onExit() {\n  Activity::onExit();\n  uiReady = false;\n''',
    '''void RssNewsActivity::onExit() {\n  // Match the EPUB reader's proven low-memory cleanup path. RSS article text\n  // can lazily create FontDecompressor's built-in compressed-font hot-group\n  // buffer during the first app.render(). That grow-only cache is global and\n  // otherwise survives the RSS activity, splitting the largest PSRAM arena.\n  // releaseSdFontCaches() is intentionally broader than its historical name:\n  // it also clears FontDecompressor before releasing rebuildable SD-font caches.\n  if (auto* fcm = renderer.getFontCacheManager()) {\n    fcm->releaseSdFontCaches();\n  }\n  sdFontSystem.releaseRegistry();\n\n  Activity::onExit();\n  uiReady = false;\n''',
    "RSS exit global font/decompressor cleanup",
)

rss = replace_once(
    rss,
    '''    silentRestartAfterNetwork();\n''',
    '''    // Keep the post-WiFi reboot that defragments the ESP network heap, but\n    // resume with the Home application menu open on RSS instead of plain Home.\n    silentRestartAfterNetworkToRssMenu();\n''',
    "RSS post-network restart target",
)

rss = replace_once(
    rss,
    '''  if (TouchHeaderBackButton::wasTapped(mappedInput, renderer)) {\n    state == State::ARTICLE ? closeArticle() : onGoHome();\n    return;\n  }\n''',
    '''  if (TouchHeaderBackButton::wasTapped(mappedInput, renderer)) {\n    if (state == State::ARTICLE) {\n      closeArticle();\n    } else {\n      mappedInput.suppressNextBackRelease();\n      finish();\n    }\n    return;\n  }\n''',
    "RSS touch Back pop",
)

rss = replace_once(
    rss,
    '''  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {\n    onGoHome();\n    return;\n  }\n''',
    '''  if (mappedInput.wasReleased(MappedInputManager::Button::Back)) {\n    finish();\n    return;\n  }\n''',
    "RSS button Back pop",
)

rss_path.write_text(rss)


# 2) Add an explicit Home-menu target usable after the mandatory network reboot.
am_path = Path("src/activities/ActivityManager.h")
am = am_path.read_text()
am = replace_once(
    am,
    '''enum class HomeMenuItem { NONE, FILE_BROWSER, RECENTS, OPDS_BROWSER, FILE_TRANSFER, SETTINGS_MENU };\n''',
    '''enum class HomeMenuItem { NONE, FILE_BROWSER, RECENTS, OPDS_BROWSER, FILE_TRANSFER, SETTINGS_MENU, RSS_NEWS };\n''',
    "Home RSS menu target enum",
)
am_path.write_text(am)

home_path = Path("src/activities/home/HomeActivity.cpp")
home = home_path.read_text()
home = replace_once(
    home,
    '''    case HomeMenuItem::SETTINGS_MENU:\n      return HomeMenuAction::Settings;\n    case HomeMenuItem::NONE:\n''',
    '''    case HomeMenuItem::SETTINGS_MENU:\n      return HomeMenuAction::Settings;\n    case HomeMenuItem::RSS_NEWS:\n      return HomeMenuAction::RssNews;\n    case HomeMenuItem::NONE:\n''',
    "Home RSS initial selection mapping",
)

home = replace_once(
    home,
    '''    if (menuIndex >= 0) {\n      selectorIndex = getHomeMenuSelectionOffset(recentBooks) + menuIndex;\n    }\n  }\n''',
    '''    if (menuIndex >= 0) {\n      selectorIndex = getHomeMenuSelectionOffset(recentBooks) + menuIndex;\n    }\n\n    // Minimal/Dashboard Home normally hides its application list. A network\n    // reboot cannot preserve the previous Home instance on the activity stack,\n    // so explicitly reopen that list and restore the RSS selection.\n    if (usesMinimalHomeInteraction()) {\n      const auto minimalItems = buildMinimalMenuItems(hasOpdsServers, hasReadingStats, hasBookmarks, hasClippings);\n      const int minimalIndex = findMenuActionIndex(minimalItems, homeActionForInitialMenuItem(initialMenuItem));\n      if (minimalIndex >= 0) {\n        minimalMenuOpen = true;\n        minimalMenuIndex = minimalIndex;\n      }\n    }\n  }\n''',
    "Home minimal menu restore",
)
home_path.write_text(home)


# 3) Silent restart API: preserve network heap defragmentation but request RSS menu on boot.
silent_path = Path("src/SilentRestart.h")
silent = silent_path.read_text()
silent = replace_once(
    silent,
    '''void silentRestartAfterNetwork();\nvoid silentRestartToReaderAfterNetwork(bool cleanImageBaseOnEntry = false);\n''',
    '''void silentRestartAfterNetwork();\nvoid silentRestartAfterNetworkToRssMenu();\nvoid silentRestartToReaderAfterNetwork(bool cleanImageBaseOnEntry = false);\n''',
    "Silent restart RSS menu declaration",
)
silent_path.write_text(silent)

main_path = Path("src/main.cpp")
main = main_path.read_text()
main = replace_once(
    main,
    '''constexpr uint32_t SILENT_REBOOT_READER_CLEAN_IMAGE_BASE = 1U << 0;\nconstexpr uint32_t SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY = 1U << 1;\n''',
    '''constexpr uint32_t SILENT_REBOOT_READER_CLEAN_IMAGE_BASE = 1U << 0;\nconstexpr uint32_t SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY = 1U << 1;\nconstexpr uint32_t SILENT_REBOOT_HOME_RSS_MENU = 1U << 2;\n''',
    "Silent restart RSS menu payload bit",
)

main = replace_once(
    main,
    '''void silentRestartAfterNetwork() {\n  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY, "target=home after network");\n}\n\nvoid restartToHomeAfterStorageHandoff() {\n''',
    '''void silentRestartAfterNetwork() {\n  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY, "target=home after network");\n}\n\nvoid silentRestartAfterNetworkToRssMenu() {\n  silentRestartToHome(SILENT_REBOOT_FOLLOW_LIGHT_WAKE_POLICY | SILENT_REBOOT_HOME_RSS_MENU,\n                      "target=RSS menu after network");\n}\n\nvoid restartToHomeAfterStorageHandoff() {\n''',
    "Silent restart RSS menu implementation",
)

main = replace_once(
    main,
    '''  } else if (resume == BootResume::Silent) {\n    // target == home (or reader with no open book): land on home — don't fall\n    // through to the sleep-wake "resume reader" logic, which fires on stale\n    // openEpubPath + lastSleepFromReader from a prior session.\n    activityManager.goHome(HomeMenuItem::NONE, true);\n''',
    '''  } else if (resume == BootResume::Silent) {\n    // target == home (or reader with no open book): land on home — don't fall\n    // through to the sleep-wake "resume reader" logic, which fires on stale\n    // openEpubPath + lastSleepFromReader from a prior session. RSS can request\n    // its application-menu selection after the network-defragmentation reboot.\n    const HomeMenuItem resumeMenuItem =\n        (snapshotPayload & SILENT_REBOOT_HOME_RSS_MENU) != 0 ? HomeMenuItem::RSS_NEWS : HomeMenuItem::NONE;\n    activityManager.goHome(resumeMenuItem, true);\n''',
    "Silent resume RSS menu routing",
)
main_path.write_text(main)


# Assertions keep this overlay readable and fail CI if upstream structure changes.
checks = {
    "RSS FontCacheManager include": "#include <FontCacheManager.h>",
    "RSS global font/decompressor cleanup": "fcm->releaseSdFontCaches();",
    "RSS normal pop": "finish();",
    "RSS network menu reboot": "silentRestartAfterNetworkToRssMenu();",
    "RSS Home enum": "RSS_NEWS",
    "RSS reboot payload": "SILENT_REBOOT_HOME_RSS_MENU",
}
combined = "\n".join((rss, am, home, silent, main))
for label, needle in checks.items():
    if needle not in combined:
        raise RuntimeError(f"{label}: verification failed")

print("Applied RSS exit lifecycle fix (global font/decompressor cleanup + app-menu return + post-WiFi menu restore).")
