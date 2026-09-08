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

  struct CachedArticle {
    uint8_t sourceIndex = 0;
    RssItem item{};
  };

  struct Source {
    const char* name;
    const char* url;
  };

  // X4 Pro only: keep a generous offline archive. The feed parser is bounded
  // to 100 current items/source while the SD cache preserves older unique
  // entries until that source reaches the same 100-item history limit.
  static constexpr size_t SOURCE_COUNT = 8;
  static constexpr size_t ITEMS_PER_SOURCE = 100;
  static constexpr size_t MAX_ARTICLES = SOURCE_COUNT * ITEMS_PER_SOURCE;
  static constexpr size_t FEED_ITEM_CAPACITY = ITEMS_PER_SOURCE;
  static constexpr uint32_t CACHE_MAGIC = 0x52535332;  // RSS2
  static constexpr uint16_t CACHE_VERSION = 2;
  static constexpr char CACHE_PATH[] = "/.crosspoint/rss_news.bin";
  static constexpr char CACHE_TMP_PATH[] = "/.crosspoint/rss_news.tmp";

  using UiApp = freeink::ui::FreeInkApp<32, 4>;

  static constexpr std::array<Source, SOURCE_COUNT> SOURCES = {{
      {"Le Figaro", "https://rss.lefigaro.fr/lefigaro/laune"},
      {"iGeneration", "https://www.igen.fr/rss"},
      {"iPhoneSoft", "https://feeds.feedburner.com/IphoneSoft"},
      {"Jeuxvideo.com", "https://www.jeuxvideo.com/rss/rss.xml"},
      {"Numerama", "https://www.numerama.com/feed/"},
      {"Frandroid", "https://www.frandroid.com/feed"},
      {"Science & Vie", "https://www.science-et-vie.com/feed"},
      {"Futura", "https://www.futura-sciences.com/rss/actualites.xml"},
  }};

  ButtonNavigator buttonNavigator;
  State state = State::LIST;
  ScreenTransitionRefresh screenTransitionRefresh;
  HeapByteBuffer articleStorage;
  HeapByteBuffer feedStorage;
  HeapByteBuffer listItemStorage;
  CachedArticle* articles = nullptr;
  RssItem* feedItems = nullptr;
  freeink::ui::ListItem* listItems = nullptr;
  size_t articleCount = 0;
  int selectorIndex = 0;
  int topIndex = 0;
  int visibleRows = 1;
  bool usedNetwork = false;
  bool refreshHadError = false;
  bool goHomeAfterRefreshCancel = false;
  std::string statusMessage;
  std::vector<std::string> articleTitleLines;
  std::vector<std::string> articleSummaryLines;

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
  bool loadCache();
  bool saveCache() const;
  void mergeSourceArticles(uint8_t sourceIndex, RssItem* items, size_t count);
  void activateSelected();
  void openArticle(size_t articleIndex);
  void closeArticle();

  void requestManualRefresh();
  void launchWifiSelection();
  void onWifiSelectionComplete(bool connected);
  void refreshFeeds();
  bool fetchSource(uint8_t sourceIndex, size_t& outCount, bool& cancelled);
  void seedSimulatorArticles();
  bool preventAutoSleep() override;
};
