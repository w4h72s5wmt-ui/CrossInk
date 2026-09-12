// Exercise the actual diagnostic writer alongside the generated RSS cache.
#include <Arduino.h>
#include <cstdlib>
#include <iostream>
#include "../../src/activities/home/RssArticleCache.cpp"

namespace H = HttpDownloader;
namespace RC = RssArticleCache;
namespace RssFigaroAuth {
bool isConfiguredFor(const std::string&) { return false; }
uint64_t cacheKeyFor(const std::string&) { return 0; }
void resetSession() {}
H::DownloadError streamUrl(const std::string&, const H::DataCallback& data, const H::CancelCallback& cancel) {
  ++H::authCalls;
  return H::deliver(data, cancel);
}
}
int checks = 0;
void check(bool ok, const std::string& message) {
  ++checks;
  if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
void reset() {
  check(testOpenFiles == 0, "no open files");
  testFiles.clear(); testLogs.clear(); H::replies.clear();
  H::publicCalls = H::authCalls = 0; testOom = false;
  testWriteFail = testSyncFail = testRenameFail = testReadFail = false;
  testWrites = 0;
}
const std::string page = "<article><p>" + std::string(240, 'x') + "</p></article>";
RssItem makeItem() {
  RssItem item;
  std::strcpy(item.link, "https://example.test/article");
  std::strcpy(item.title, "Titre");
  std::strcpy(item.summary, "Resume disponible");
  return item;
}
RC::CacheResult fetch(const RssItem& item) {
  return RC::ensureCached(item, "Test", "", "", "", {});
}
namespace D = RssFetchDiagnostics;

int main() {
  reset();
  D::Record record;
  record.transport = "figaro-auth";
  record.phase = "body-idle";
  record.startedMs = UINT32_MAX - 5;
  record.result = H::HTTP_ERROR;
  record.received = 1234;
  record.openMs = 17;
  record.headersMs = 23;
  record.bodyMs = 15000;
  record.tlsError = -42;
  testMillis = 5;
  D::write("https://www.lefigaro.fr/private?token=HIDDEN_QUERY", record);
  check(testWrites == 0, "diagnostics inactive outside refresh");
  testFiles["/RSS/figaro_auth.txt"] = "SECRET_COOKIE";
  testFiles["/.crosspoint/preserved.txt"] = "unchanged";
  D::begin();
  D::write("https://www.lefigaro.fr/PRIVATE_PATH?token=HIDDEN_QUERY#HIDDEN_FRAGMENT", record);
  D::write("https://PRIVATE_USER:PRIVATE_PASS@www.lefigaro.fr/path", record);
  D::end();
  auto text = testFiles[D::PATH];
  for (const char* secret : {"PRIVATE_PATH", "HIDDEN_QUERY", "HIDDEN_FRAGMENT", "PRIVATE_USER", "PRIVATE_PASS", "SECRET_COOKIE"}) {
    check(text.find(secret) == std::string::npos, std::string("no private value: ") + secret);
  }
  check(text.find("www.lefigaro.fr\t") != std::string::npos, "host retained");
  check(text.find("\tbody-idle\t") != std::string::npos, "failure stage retained");
  check(text.find("\t1234\t") != std::string::npos, "byte count retained");
  check(text.find("\t11\t17\t23\t15000\t") != std::string::npos, "wrap-safe elapsed and stage times");
  check(text.ends_with("# end\n"), "report closed normally");
  check(testFiles["/RSS/figaro_auth.txt"] == "SECRET_COOKIE" &&
        testFiles["/.crosspoint/preserved.txt"] == "unchanged", "report touches no app data");
  D::begin();
  for (size_t i = 0; i < 3000; ++i) D::write("https://www.lefigaro.fr/test", record);
  D::end();
  check(testFiles[D::PATH].size() <= D::MAX_REPORT_BYTES, "bounded report size");
  check(testOpenFiles == 0, "file closed at report cap");
  D::begin();
  D::end();
  check(testFiles[D::PATH].find("body-idle") == std::string::npos, "new refresh replaces old report");
  reset();
  D::begin();
  testSyncFail = true;
  D::write("https://example.test/x", record);
  testSyncFail = false;
  check(testOpenFiles == 0, "report closes after SD error");
  auto item = makeItem();
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY, "disabled diagnostic cannot block cache success");
  D::end();
  reset();
  D::begin();
  H::replies.push_back({std::string(RC::MAX_HTML_BYTES + 1, 'x')});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "capacity policy unchanged");
  D::end();
  check(testFiles[D::PATH].find("\thtml-capacity\t") != std::string::npos, "HTML capacity reason logged");
  check(RC::hasReadableBody(item) && !RC::hasCurrentBody(item), "capacity failure persists retriable fallback");
  reset();
  D::begin();
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY, "body fetch with reporting");
  D::end();
  check(testFiles[D::PATH].find("\tbody-ready\t") != std::string::npos, "successful extraction recorded");
  reset();
  std::cout << "RSS diagnostic checks passed; total checks=" << checks << '\n';
}
