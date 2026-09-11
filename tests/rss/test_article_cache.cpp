// Compile the generated production cache, not a separate implementation.
// Run after the workflow RSS integration steps; network/SD are host doubles.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <vector>
#include "../../src/activities/home/RssArticleCache.cpp"

inline bool testAuth = false;
namespace RssFigaroAuth {
bool isConfiguredFor(const std::string& url) { return testAuth && url.find("lefigaro.fr") != std::string::npos; }
uint64_t cacheKeyFor(const std::string& url) { return isConfiguredFor(url) ? 123456789ULL : 0; }
void resetSession() {}
HttpDownloader::DownloadError streamUrl(const std::string&, const HttpDownloader::DataCallback& data,
                                        const HttpDownloader::CancelCallback& cancel) {
  ++HttpDownloader::authCalls;
  return HttpDownloader::deliver(data, cancel);
}
}
namespace RC = RssArticleCache;
namespace H = HttpDownloader;
int checks = 0;
void check(bool ok, const std::string& message) {
  ++checks;
  if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
const std::string prose = "Le texte utile de ce document contient plusieurs phrases pour verifier que le contenu "
                          "reste disponible dans son integralite. Les sections suivantes decrivent les details "
                          "du sujet sans navigation ni liens vers des pages annexes. ";
const std::string page = "<article><p>" + prose + "</p><p>FIN_UTILE</p></article>";
std::string extract(const std::string& html, bool* ok = nullptr) {
  std::vector<char> buffer(RC::MAX_TEXT_BYTES + 1);
  size_t length = 0;
  const bool result = RC::extractReadableText(html.data(), html.size(), buffer.data(), length);
  if (ok) *ok = result;
  return std::string(buffer.data(), length);
}
void reset() {
  check(testOpenFiles == 0, "no SD file left open");
  testFiles.clear(); testLogs.clear(); H::replies.clear();
  H::publicCalls = H::authCalls = 0; testAuth = false; testOom = false;
  testWriteFail = testSyncFail = testRenameFail = testReadFail = false; testWrites = 0;
}
RssItem makeItem() {
  RssItem item;
  std::strcpy(item.link, "https://example.test/article");
  std::strcpy(item.title, "Titre de test");
  std::strcpy(item.summary, "<p>Le resume du flux reste disponible.</p><p>[Lire la suite]</p>");
  return item;
}
RC::CacheResult fetch(const RssItem& item, const H::CancelCallback& cancel = {}) {
  return RC::ensureCached(item, "Test", "", "", "[Lire la suite]", cancel);
}
RC::CacheResult load(const RssItem& item, std::string& out) {
  return RC::load(item, "Test", "", "", "[Lire la suite]", out);
}

void htmlTests() {
  const std::vector<std::string> keep = {
      "class=container-with-sidebar", "class='article-content article-content--has-sidebar good-deal'",
      "class=article-body data-url='https://example.test/codes-promo'", "data-paywall='false'",
      "data-class='sidebar' class=article-content", "class='has-sidebar'", "class='no-sidebar'"};
  for (const auto& attrs : keep) {
    const auto text = extract("<article><div " + attrs + "><p>" + prose + "</p></div><p>FIN_UTILE</p></article>");
    check(text.find("FIN_UTILE") != std::string::npos, "preserve layout " + attrs);
  }
  const std::vector<std::string> drop = {
      "class=sidebar", "id=sidebar", "class=sidebar__content", "class=ad-container",
      "id=adslot_42", "class=share", "class=newsletter", "class=related-posts"};
  for (const auto& attrs : drop) {
    const auto text = extract("<article><p>" + prose + "</p><div " + attrs + ">PARASITE</div><p>FIN_UTILE</p></article>");
    check(text.find("PARASITE") == std::string::npos && text.find("FIN_UTILE") != std::string::npos,
          "drop noise " + attrs);
  }
  auto text = extract("<script>var x='<article>FAUX</article>';</script>" + page);
  check(text.find("FIN_UTILE") != std::string::npos && text.find("FAUX") == std::string::npos, "ignore script root");
  text = extract("<!-- <article>FAUX</article> -->" + page);
  check(text.find("FIN_UTILE") != std::string::npos, "ignore comment root");
  text = extract("<article><div class=container-with-sidebar><div class='article-content article-content--has-sidebar good-deal'><p>" + prose + prose + prose + "</p><p>FRANDROID_BODY</p></div></div></article>");
  check(text.find("FRANDROID_BODY") != std::string::npos, "Frandroid layout regression");

  const std::string longBody = prose + prose + prose + prose;
  text = extract("<body><article><p>" + std::string(224, 'c') + "</p></article><article><p>" + longBody + "</p><p>SCIENCE_BODY</p></article></body>");
  check(text.find("SCIENCE_BODY") != std::string::npos && text.find(std::string(32, 'c')) == std::string::npos,
        "strong article beats Science teaser");
  text = extract("<body><main><article><p>" + std::string(90, 'x') + "</p></article><article><p>" +
                 std::string(380, 'y') + "</p></article><section><p>" + longBody +
                 "</p><p>FUTURA_BODY</p></section></main></body>");
  check(text.find("FUTURA_BODY") != std::string::npos, "main beats Futura teaser articles");
  text = extract("<main><p>" + longBody + "</p><p>MAIN_BODY</p></main>");
  check(text.find("MAIN_BODY") != std::string::npos, "main fallback");

  text = extract("<article><p>" + longBody + "</p><p>caf&eacute; d&#233;j&agrave; gar&ccedil;on c&oelig;ur l&rsquo;Europe &#x20AC;</p></article>");
  check(text.find("café déjà garçon cœur l’Europe €") != std::string::npos,
        "French named/numeric entities decode to UTF-8");
  text = extract("<article><p>" + longBody + "</p><p>Énergie, déjà, français, cœur — été.</p></article>");
  check(text.find("Énergie, déjà, français, cœur — été.") != std::string::npos,
        "direct UTF-8 survives extraction");
  text = extract("<article><p>" + longBody + "</p><p>Conserver &NotARealEntity; intact.</p></article>");
  check(text.find("&NotARealEntity;") != std::string::npos, "unknown entity is not silently deleted");

  bool ok = true;
  extract("<article><p>" + std::string(RC::MAX_TEXT_BYTES + 100, 'x') + "</p></article>", &ok);
  check(!ok, "text capacity is not successful extraction");
  std::mt19937 rng(1234);
  const std::string alphabet = "<>/='\"!- abcdef\t\n&;";
  for (int i = 0; i < 500; ++i) {
    std::string html;
    for (int j = 0; j < 200; ++j) html += alphabet[rng() % alphabet.size()];
    extract(html);
  }
}

void figaroCleanupTests() {
  const std::string editorial = "Le premier paragraphe editorial doit rester intact après le nettoyage. " + prose;
  std::string flattened =
      "Offrir l'article Vous avez encore 7 articles à offrir ce mois-ci. Vous pourrez à nouveau offrir 10 articles le mois prochain. "
      "Le contenu n'a pas pu être chargé. Veuillez rafraîchir la page. "
      "Nouvelle fonctionnalité Avec votre compte, vous pouvez désormais sauvegarder des articles pour les lire plus tard sur tous vos appareils. "
      "Pour sauvegarder un article vous devez être connecté, vous pourrez ainsi les consulter sur tous vos appareils. Créer un compte Se connecter " + editorial;
  std::vector<char> buffer(flattened.begin(), flattened.end());
  buffer.push_back('\0');
  const size_t cleaned = RC::stripFigaroUiPreamble(buffer.data(), flattened.size(), "https://www.lefigaro.fr/test");
  const std::string out(buffer.data(), cleaned);
  check(out.find("Offrir l'article") == std::string::npos, "Figaro flattened gift UI removed");
  check(out.find("Le contenu n'a pas pu être chargé") == std::string::npos, "Figaro load-error UI removed");
  check(out.find("Sauvegarder") == std::string::npos, "Figaro save UI removed");
  check(out.find(editorial) == 0, "Figaro editorial suffix preserved exactly");

  std::string normal = "Une phrase normale sur le fait d'offrir quelque chose. " + prose;
  std::vector<char> normalBuffer(normal.begin(), normal.end());
  normalBuffer.push_back('\0');
  const size_t normalLength = RC::stripFigaroUiPreamble(normalBuffer.data(), normal.size(), "https://www.lefigaro.fr/test");
  check(normalLength == normal.size() && std::string(normalBuffer.data(), normalLength) == normal,
        "Figaro prose is not removed without multiple UI markers");
}

void cacheTests() {
  auto item = makeItem();
  std::string out;
  reset();
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "network failure -> summary");
  check(testFiles.empty() && testWrites == 0, "summary not persisted");
  check(load(item, out) == RC::CacheResult::FALLBACK_READY && out == "Le resume du flux reste disponible.",
        "summary explicit fallback");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY, "manual retry obtains body");
  check(load(item, out) == RC::CacheResult::READY && out.find("FIN_UTILE") != std::string::npos, "body loads");
  const auto cachedCalls = H::publicCalls;
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == cachedCalls, "valid cache reused");

  reset();
  testFiles[RC::bodyPath(item)] = "XRSS7\nAncien corps Figaro avec preambule UI";
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 1, "XRSS7 pre-cleanup body invalidated");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS8\n", 0) == 0, "XRSS8 body cache version");

  reset();
  H::replies.push_back({"<article>trop court</article>"});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles.empty(), "short extraction not cached");
  reset();
  H::replies.push_back({std::string(RC::MAX_HTML_BYTES + 1, 'x')});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles.empty(), "oversized HTML rejected");
  reset();
  testOom = true;
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles.empty(), "OOM retriable");

  reset();
  testAuth = true;
  std::strcpy(item.link, "https://www.lefigaro.fr/test");
  check(fetch(item) == RC::CacheResult::FAILED && H::authCalls == 1 && H::publicCalls == 0,
        "AUTH failure never public fetch");
  check(load(item, out) == RC::CacheResult::FAILED && out.empty(), "AUTH failure no summary");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 0, "AUTH retry succeeds");

  reset(); item = makeItem(); H::replies.push_back({page}); testWriteFail = true;
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles.empty(), "write failure cleans cache");
  reset(); H::replies.push_back({page});
  int polls = 0;
  check(fetch(item, [&]{ return ++polls >= 3; }) == RC::CacheResult::CANCELLED && testFiles.empty(),
        "cancellation during fetch");
}

std::string readFile(const char* path) {
  std::ifstream stream(path, std::ios::binary);
  check(bool(stream), std::string("read fixture ") + path);
  return std::string(std::istreambuf_iterator<char>(stream), {});
}
int main(int argc, char** argv) {
  htmlTests(); figaroCleanupTests(); cacheTests();
  if (argc >= 3) {
    auto item = makeItem();
    const auto html = readFile(argv[1]);
    std::strcpy(item.link, "https://www.frandroid.com/bons-plans/3229397_test");
    std::string drop, dropStart, stop;
    const auto feeds = readFile(argv[2]);
    const auto pos = feeds.find("\nFrandroid|");
    check(pos != std::string::npos, "Frandroid config present");
    const auto line = feeds.substr(pos + 1, feeds.find('\n', pos + 1) - pos - 1);
    const std::pair<const char*, std::string*> fields[] = {{"drop=", &drop}, {"dropstart=", &dropStart}, {"stop=", &stop}};
    for (const auto& field : fields) {
      const auto p = line.find(std::string("|") + field.first);
      if (p != std::string::npos) {
        const auto start = p + 1 + std::strlen(field.first);
        *field.second = line.substr(start, line.find('|', start) - start);
      }
    }
    H::replies.push_back({html});
    check(RC::ensureCached(item, "Frandroid", drop.c_str(), dropStart.c_str(), stop.c_str(), {}) == RC::CacheResult::READY,
          "real Frandroid HTML cached");
    std::string body;
    check(RC::load(item, "Frandroid", drop.c_str(), dropStart.c_str(), stop.c_str(), body) == RC::CacheResult::READY,
          "real Frandroid body loads");
  }
  check(testOpenFiles == 0, "final no open files");
  std::cout << "PASS " << checks << " checks plus 500 randomized HTML inputs\n";
}