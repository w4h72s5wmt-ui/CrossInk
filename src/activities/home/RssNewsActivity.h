#pragma once

#include <FreeInkApp.h>
#include <FreeInkUIGfxRenderer.h>
#include <Memory.h>
#include <RssParser.h>

#include <array>
#include <atomic>
#include <string>
#include <vector>

#include "activities/Activity.h"
#include "activities/ScreenTransitionRefresh.h"
#include "RssArticleMetadata.h"
#include "util/ButtonNavigator.h"

class RssNewsActivity final : public Activity {
 public:
  explicit RssNewsActivity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  enum class State : uint8_t { LIST, ARTICLE, WIFI_SELECTION, REFRESHING };
  enum class SortMode : uint8_t { DATE_DESC, SOURCE };

  using CachedArticle = RssArticleMetadata::Record;

  struct Source {
    std::string name;
    std::string url;
    uint16_t syncLimit = 30;
    uint16_t historyLimit = 100;
    std::string dropRules;
    std::string dropStartRules;
    std::string stopRules;
  };

  struct DefaultSource {
    const char* name;
    const char* url;
    uint16_t syncLimit;
    uint16_t historyLimit;
  };

  // Hard safety ceilings stay fixed, but runtime buffers are sized from the
  // active feeds.txt limits so small configurations do not reserve the full
  // eight-feed / 100-item PSRAM envelope.
  static constexpr size_t MAX_SOURCES = 8;
  static constexpr size_t DEFAULT_SOURCE_COUNT = 6;
  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr uint16_t DEFAULT_SYNC_LIMIT = 30;
  static constexpr uint16_t DEFAULT_HISTORY_LIMIT = 100;
  static constexpr size_t MAX_ARTICLES = MAX_SOURCES * ITEMS_PER_SOURCE;
  static constexpr size_t FEED_ITEM_CAPACITY = ITEMS_PER_SOURCE;
  static constexpr size_t FEED_CONFIG_MAX_BYTES = 4096;
  static constexpr size_t LIST_META_CAPACITY = 64;
  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2
  // V5 stores lightweight history metadata; old development caches are
  // intentionally invalidated rather than migrated.
  static constexpr uint16_t CACHE_VERSION = 5;
  static constexpr char CACHE_PATH[] = "/.crosspoint/rss_news.bin";
  static constexpr char CACHE_TMP_PATH[] = "/.crosspoint/rss_news.tmp";
  static constexpr char FEEDS_DIR[] = "/RSS";
  static constexpr char FEEDS_PATH[] = "/RSS/feeds.txt";

  using UiApp = freeink::ui::FreeInkApp<32, 4>;

  static constexpr std::array<DefaultSource, DEFAULT_SOURCE_COUNT> DEFAULT_SOURCES = {{
      {"iGeneration", "https://www.igen.fr/rss", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Frandroid", "https://www.frandroid.com/feed", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Science & Vie", "https://www.science-et-vie.com/feed", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml", DEFAULT_SYNC_LIMIT, DEFAULT_HISTORY_LIMIT},
  }};

  ButtonNavigator buttonNavigator;
  State state = State::LIST;
  SortMode sortMode = SortMode::DATE_DESC;
  ScreenTransitionRefresh screenTransitionRefresh;
  HeapByteBuffer articleStorage;
  HeapByteBuffer feedStorage;
  HeapByteBuffer listItemStorage;
  HeapByteBuffer listMetaStorage;
  HeapByteBuffer displayOrderStorage;
  CachedArticle* articles = nullptr;
  RssItem* feedItems = nullptr;
  freeink::ui::ListItem* listItems = nullptr;
  char* listMetaText = nullptr;
  uint16_t* displayOrder = nullptr;
  size_t articleCount = 0;
  size_t articleCapacity = MAX_ARTICLES;
  size_t feedItemCapacity = FEED_ITEM_CAPACITY;
  size_t articleLineOffset = 0;
  size_t articlePageLines = 8;
  size_t openArticleIndex = MAX_ARTICLES;
  int selectorIndex = 0;
  int topIndex = 0;
  int visibleRows = 1;
  bool usedNetwork = false;
  bool refreshHadError = false;
  bool goHomeAfterRefreshCancel = false;
  std::string statusMessage;
  std::vector<std::string> articleTitleLines;
  std::vector<std::string> articleSummaryLines;
  std::array<Source, MAX_SOURCES> sources{};
  size_t sourceCount = 0;

  freeink::ui::GfxRendererTarget uiTarget;
  UiApp app;
  std::atomic<bool> uiReady{false};

  static void rootScreen(UiApp::ScreenType& screen, void* user);
  static void onRowEvent(const freeink::ui::ActionEvent& event, void* user);

  void screenHeader(UiApp::ScreenType& screen);
  void buildListScreen(UiApp::ScreenType& screen);
  void buildArticleScreen(UiApp::ScreenType& screen);
  void buildStatusScreen(UiApp::ScreenType& screen);

  bool ensureBuffers();
  bool ensureFeedBuffer();
  void releaseFeedBuffer();
  void loadSources();
  bool ensureFeedConfigFile();
  uint32_t sourceConfigHash() const;
  bool loadCache();
  bool saveCache() const;
  bool mergeSourceArticles(uint8_t sourceIndex, RssItem* items, size_t count);
  void rebuildDisplayOrder();
  void toggleSortMode();
  size_t articleIndexForDisplayRow(size_t displayRow) const;
  void activateSelected();
  void openArticle(size_t articleIndex);
  void closeArticle();
  void scrollArticle(int deltaLines);

  void requestManualRefresh();
  void launchWifiSelection();
  void onWifiSelectionComplete(bool connected);
  void refreshFeeds();
  bool fetchSource(uint8_t sourceIndex, size_t& outCount, bool& cancelled);
  void seedSimulatorArticles();
  bool preventAutoSleep() override;
};
