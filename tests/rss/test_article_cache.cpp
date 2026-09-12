// Compile the generated production cache, not a separate implementation.
// Run after the workflow RSS integration steps; network/SD are host doubles.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <vector>
#include "../../src/activities/home/RssArticleCache.cpp"
#include "../../src/activities/home/RssArticleMetadata.h"

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
  return RC::load(item, out);
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

  text = extract("<article><p>" + longBody + "</p><p>Consultez <a href='https://example.test/tres-longue-adresse?tracking=1'>ce dossier complet</a> pour la suite.</p></article>");
  check(text.find("ce dossier complet") != std::string::npos && text.find("https://example.test") == std::string::npos,
        "anchor label preserved while href is discarded");
  text = extract("<article><p>" + longBody + "</p><p>Source <a href='https://example.test/page'>https://example.test/page?tracking=1</a> fin.</p></article>");
  check(text.find("https://example.test/page") == std::string::npos && text.find("Source") != std::string::npos &&
            text.find("fin.") != std::string::npos,
        "URL used as anchor label is removed");


  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/page'>https://example.test/page</a>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos, "removed visible URL keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/page'>https://example.test/page</a>.Apres.</p></article>");
  check(text.find("Avant. Apres.") != std::string::npos, "removed visible URL moves separator after punctuation");
  text = extract("<article><p>" + longBody + "</p><p>Avant<div class='share'>PARASITE</div>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos && text.find("PARASITE") == std::string::npos,
        "removed noise container keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<div class='share'>PARASITE</div>.Apres.</p></article>");
  check(text.find("Avant. Apres.") != std::string::npos, "removed noise container preserves punctuation spacing");
  text = extract("<article><p>" + longBody + "</p><p>Avant<script>parasite()</script>Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos, "removed raw script keeps a word boundary");
  text = extract("<article><p>" + longBody + "</p><p>Avant<!-- parasite -->Apres.</p></article>");
  check(text.find("Avant Apres.") != std::string::npos, "removed HTML comment keeps a word boundary");


  text = extract("<article><p>" + longBody +
                 "</p><p>bilan médical.<img src='apple.jpg'>© Apple suite.</p></article>");
  check(text.find("bilan médical. © Apple suite.") != std::string::npos,
        "discarded image keeps caption boundary after punctuation");

  const std::string futuraCardTitle =
      "À quel âge commence-t-on vraiment à vieillir ? Une étude de Stanford nous donne la réponse";
  text = extract("<article><p>" + longBody +
                 "</p><p>© Apple<a href='https://example.test/card'>" + futuraCardTitle +
                 "</a>44 ans, 60 ans : deux moments clés.</p></article>");
  check(text.find(std::string("© Apple ") + "\xEE\x80\x80" + futuraCardTitle) != std::string::npos &&
            text.find(futuraCardTitle + std::string("\xEE\x80\x81") + " 44 ans, 60 ans") != std::string::npos,
        "long Futura-style card link keeps boundaries on both sides");

  text = extract("<article><p>" + longBody + "</p><p>Avant<a href='https://example.test/card'>" +
                 futuraCardTitle + "</a>.Suite.</p></article>");
  check(text.find(futuraCardTitle + std::string("\xEE\x80\x81") + ". Suite.") != std::string::npos,
        "long card link keeps punctuation attached then separates following prose");

  text = extract("<article><p>" + longBody +
                 "</p><p>l'<a href='https://example.test/apple'>Apple</a> reste un lien inline.</p></article>");
  check(text.find(std::string("l'") + "\xEE\x80\x80" + "Apple" + "\xEE\x80\x81" +
                  " reste un lien inline.") != std::string::npos,
        "short inline anchor keeps apostrophe grammar unchanged");

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


  std::string sharedMiddle = "Avant -Lien copie- Mail- X- MessengerApres";
  std::vector<char> sharedMiddleBuffer(sharedMiddle.begin(), sharedMiddle.end());
  sharedMiddleBuffer.push_back('\0');
  const size_t sharedMiddleLength = RC::stripFigaroShareControls(
      sharedMiddleBuffer.data(), sharedMiddle.size(), "https://www.lefigaro.fr/test");
  const std::string sharedMiddleOut(sharedMiddleBuffer.data(), sharedMiddleLength);
  check(sharedMiddleOut == "Avant Apres", "Figaro mid-article share controls removed without losing prose");


  std::string sharedPunctuation = "Avant -Lien copie- Mail- X- Messenger.Apres";
  std::vector<char> sharedPunctuationBuffer(sharedPunctuation.begin(), sharedPunctuation.end());
  sharedPunctuationBuffer.push_back('\0');
  const size_t sharedPunctuationLength = RC::stripFigaroShareControls(
      sharedPunctuationBuffer.data(), sharedPunctuation.size(), "https://www.lefigaro.fr/test");
  check(std::string(sharedPunctuationBuffer.data(), sharedPunctuationLength) == "Avant. Apres",
        "Figaro share removal keeps punctuation readable");

  std::string sharedTwice =
      "Debut -Lien copié- Mail- X- MessengerMilieu -Lien copie- Mail- X- MessengerFin";
  std::vector<char> sharedTwiceBuffer(sharedTwice.begin(), sharedTwice.end());
  sharedTwiceBuffer.push_back('\0');
  const size_t sharedTwiceLength = RC::stripFigaroShareControls(
      sharedTwiceBuffer.data(), sharedTwice.size(), "https://www.lefigaro.fr/test");
  const std::string sharedTwiceOut(sharedTwiceBuffer.data(), sharedTwiceLength);
  check(sharedTwiceOut == "Debut Milieu Fin", "Figaro multiple share controls removed");
}

void metadataTests() {
  auto item = makeItem();
  std::strcpy(item.published, "2026-09-12T12:00:00Z");
  const auto record = RssArticleMetadata::fromItem(3, item, 7);
  check(sizeof(RssItem) == 4684, "production-sized RssItem host model");
  check(sizeof(record) == 589, "lightweight RSS history record is 589 bytes with read time");
  check(record.sourceIndex == 3 && record.readingMinutes == 7 && std::strcmp(record.title, item.title) == 0 &&
            std::strcmp(record.link, item.link) == 0 && std::strcmp(record.published, item.published) == 0,
        "history record keeps source/read-time/title/link/date");
  check(RssArticleMetadata::same(record, item), "history identity matches source RssItem");
  auto changed = item;
  std::strcpy(changed.summary, "un autre resume ne change pas l'identite");
  check(RssArticleMetadata::same(record, changed), "summary is not part of history identity");

  const std::string words220 = [] {
    std::string text;
    for (int i = 0; i < 220; ++i) text += i ? " mot" : "mot";
    return text;
  }();
  check(RssArticleMetadata::readingMinutesForText(words220.c_str(), words220.size()) == 1,
        "220 words rounds to one minute");
  const std::string words221 = words220 + " mot";
  check(RssArticleMetadata::readingMinutesForText(words221.c_str(), words221.size()) == 2,
        "221 words rounds up to two minutes");
  check(RssArticleMetadata::readingMinutesForText("", 0) == 0, "empty text has no reading estimate");
  std::string huge;
  huge.reserve(220 * 101 * 2);
  for (int i = 0; i < 220 * 101; ++i) huge += i ? " x" : "x";
  check(RssArticleMetadata::readingMinutesForText(huge.c_str(), huge.size()) == 99,
        "reading estimate is capped at 99 minutes");
}

void cacheTests() {
  {
    char fallback[] = "Avant https://example.test/page Apres";
    const size_t cleaned = RC::removeFallbackUrls(fallback, std::strlen(fallback));
    check(std::string(fallback, cleaned) == "Avant Apres", "fallback URL removal keeps word boundary");
  }
  {
    char fallback[] = "Avant https://example.test/page .Apres";
    const size_t cleaned = RC::removeFallbackUrls(fallback, std::strlen(fallback));
    check(std::string(fallback, cleaned) == "Avant. Apres", "fallback URL removal fixes punctuation seam");
  }
  auto item = makeItem();
  std::string out;
  reset();
  const std::string path = RC::bodyPath(item);
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "network failure -> persisted summary fallback");
  check(testFiles[path].rfind("XRSSF3\n", 0) == 0, "fallback has current SD marker");
  check(RC::hasReadableBody(item) && !RC::hasCurrentBody(item), "fallback readable but not a full body");
  check(load(item, out) == RC::CacheResult::FALLBACK_READY && out == "Le resume du flux reste disponible.",
        "persisted summary fallback loads without RssItem history summary");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY, "manual retry replaces fallback with full body");
  check(testFiles[path].rfind("XRSS13\n", 0) == 0, "full body keeps XRSS12 marker");
  check(load(item, out) == RC::CacheResult::READY && out.find("FIN_UTILE") != std::string::npos, "body loads");
  const auto cachedCalls = H::publicCalls;
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == cachedCalls, "valid full cache reused");
  check(RC::hasCurrentBody(item) && RC::hasReadableBody(item), "full body probes current/readable");

  reset();
  testFiles[RC::bodyPath(item)] = "XRSS12\nAncien corps de developpement";
  check(!RC::hasCurrentBody(item) && !RC::hasReadableBody(item), "previous body generation rejected");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 1, "obsolete body invalidated and refetched");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS13\n", 0) == 0, "refetched current full body version");

  reset();
  H::replies.push_back({"<article>trop court</article>"});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && RC::hasReadableBody(item),
        "short extraction persists retriable fallback");
  reset();
  H::replies.push_back({std::string(RC::MAX_HTML_BYTES + 1, 'x')});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && RC::hasReadableBody(item),
        "oversized HTML persists retriable fallback");
  reset();
  testOom = true;
  check(fetch(item) == RC::CacheResult::FAILED && testFiles.empty(), "OOM without existing fallback drops metadata safely");

  reset();
  check(fetch(item) == RC::CacheResult::FALLBACK_READY, "seed fallback before failed replacement");
  const std::string fallbackBefore = testFiles[RC::bodyPath(item)];
  testWriteFail = true;
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::FALLBACK_READY && testFiles[RC::bodyPath(item)] == fallbackBefore,
        "failed full-body write preserves existing fallback");

  reset();
  testAuth = true;
  std::strcpy(item.link, "https://www.lefigaro.fr/test");
  check(fetch(item) == RC::CacheResult::FAILED && H::authCalls == 1 && H::publicCalls == 0,
        "AUTH failure never public fetch or summary fallback");
  check(load(item, out) == RC::CacheResult::FAILED && out.empty(), "AUTH failure no summary");
  H::replies.push_back({page});
  check(fetch(item) == RC::CacheResult::READY && H::publicCalls == 0, "AUTH retry succeeds");

  reset(); item = makeItem(); H::replies.push_back({page}); testWriteFail = true;
  check(fetch(item) == RC::CacheResult::FAILED && testFiles.empty(), "body/fallback write failure is not retained");
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
  htmlTests(); figaroCleanupTests(); metadataTests(); cacheTests();
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
    check(RC::load(item, body) == RC::CacheResult::READY,
          "real Frandroid body loads");
  }
  check(testOpenFiles == 0, "final no open files");
  std::cout << "PASS " << checks << " checks plus 500 randomized HTML inputs\n";
}