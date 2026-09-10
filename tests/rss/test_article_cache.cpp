// Compile the generated production cache, not a separate implementation.
// Run after the workflow's RSS integration steps; network/SD are host doubles.
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
  return HttpDownloader::deliver(data,cancel);
}
}
namespace RC = RssArticleCache;
namespace H = HttpDownloader;
int checks=0;
void check(bool ok, const std::string& message) {
  ++checks;
  if (!ok) { std::cerr<<"FAIL: "<<message<<'\n'; std::exit(1); }
}
const std::string prose = "Le texte utile de ce document contient plusieurs phrases pour verifier que le contenu "
                          "reste disponible dans son integralite. Les sections suivantes decrivent les details "
                          "du sujet sans navigation ni liens vers des pages annexes. ";
const std::string page = "<article><p>"+prose+"</p><p>FIN_UTILE</p></article>";
std::string extract(const std::string& html, bool* ok=nullptr) {
  std::vector<char> buffer(RC::MAX_TEXT_BYTES+1);
  size_t length=0;
  const bool result=RC::extractReadableText(html.data(),html.size(),buffer.data(),length);
  if (ok) *ok=result;
  return std::string(buffer.data(),length);
}
void reset() {
  check(testOpenFiles==0,"no SD file left open");
  testFiles.clear(); testLogs.clear(); H::replies.clear();
  H::publicCalls=H::authCalls=0; testAuth=false; testOom=false;
  testWriteFail=testSyncFail=testRenameFail=testReadFail=false; testWrites=0;
}
RssItem makeItem() {
  RssItem item;
  std::strcpy(item.link,"https://example.test/article");
  std::strcpy(item.title,"Titre de test");
  std::strcpy(item.summary,"<p>Le resume du flux reste disponible.</p><p>[Lire la suite]</p>");
  return item;
}
RC::CacheResult fetch(const RssItem& item, const H::CancelCallback& cancel={}) {
  return RC::ensureCached(item,"Test","","","[Lire la suite]",cancel);
}
RC::CacheResult load(const RssItem& item,std::string& out) {
  return RC::load(item,"Test","","","[Lire la suite]",out);
}
void htmlTests() {
  const std::vector<std::string> keep = {
    "class=container-with-sidebar", "class='article-content article-content--has-sidebar good-deal'",
    "class=article-body data-url='https://example.test/codes-promo'", "data-paywall='false'",
    "data-class='sidebar' class=article-content", "title='class=sidebar' class=article-body",
    "id=article-content--has-sidebar", "class='sponsorship-report'", "class='shared-content'",
    "class='no-sidebar'", "class='with-sidebar'", "class='has-sidebar'",
    "data-info='1 > 0; sidebar promo' class='article-content'", "CLASS='container-with-sidebar'",
    "class='article-content' data-x=sidebar", "class=article-content aria-label='share newsletter'",
    "class='article-content' style='--sidebar-width: 12px'", "class=article-content hidden-data",
  };
  for (const auto& attrs:keep) {
    const auto result=extract("<article><div "+attrs+"><p>"+prose+"</p></div><p>FIN_UTILE</p></article>");
    check(result.find(prose.substr(0,50))!=std::string::npos,"preserve "+attrs);
    check(result.find("FIN_UTILE")!=std::string::npos,"preserve tail "+attrs);
  }
  const std::vector<std::string> drop = {
    "class=sidebar", "class='x sidebar y'", "id=sidebar", "class=sidebar__content",
    "class=sidebar--right", "id=sidebar-2", "class=ad-container", "id=adslot_42",
    "class='share'", "class='newsletter'", "class='comments'", "class='related-posts'",
    "id='optidigital-adslot-Billboard_1'", "id='div-gpt-ad-123'", "CLASS='SIDEBAR'",
    "class=sidebar-content-container", "class=newsletter-form", "class=newsletter-form__faq",
    "class=promo-container", "class=article-footer", "class=article-comments",
    "disabled class = 'sidebar'", "class='\tsidebar\n'", "title='>' class=sidebar",
  };
  for (const auto& attrs:drop) {
    const auto result=extract("<article><p>"+prose+"</p><div "+attrs+"><div>PARASITE</div></div><p>FIN_UTILE</p></article>");
    check(result.find("PARASITE")==std::string::npos,"drop "+attrs);
    check(result.find("FIN_UTILE")!=std::string::npos,"resume after "+attrs);
  }
  auto result=extract("<article><p>"+prose+"</p><article><p>ENCART</p></article><p>FIN_EXTERNE</p></article>");
  check(result.find("FIN_EXTERNE")!=std::string::npos,"balanced outer article");
  result=extract("<script>var x='<article>FAUX</article>';</script>"+page);
  check(result.find("FIN_UTILE")!=std::string::npos && result.find("FAUX")==std::string::npos,"ignore fake root in script");
  result=extract("<!-- <article>FAUX</article> -->"+page);
  check(result.find("FIN_UTILE")!=std::string::npos,"ignore fake root in comment");
  result=extract("<article><p>"+prose+"</p><script>var x='<div></article>';</script><p>FIN_UTILE</p></article>");
  check(result.find("FIN_UTILE")!=std::string::npos,"raw script not structural HTML");
  result=extract("<article><p>"+prose+"</p><div class=sidebar><script>var x='<div>';</script>PARASITE</div><p>FIN_UTILE</p></article>");
  check(result.find("FIN_UTILE")!=std::string::npos && result.find("PARASITE")==std::string::npos,"script inside skipped subtree");
  result=extract("<article><p>"+prose+"<!-- x -->TEXTE_APRES_COMMENTAIRE</p></article>");
  check(result.find("TEXTE_APRES_COMMENTAIRE")!=std::string::npos,"text after comment");
  result=extract("<main><p>"+prose+"</p></main>");
  check(result.find(prose.substr(0,50))!=std::string::npos,"main fallback");
  result=extract("<body><p>"+prose+"</p></body>");
  check(result.find(prose.substr(0,50))!=std::string::npos,"body fallback");
  result=extract("<article><div class=container-with-sidebar><div class='article-content article-content--has-sidebar good-deal'><p>"+prose+"</p></div></div></article>");
  check(result.find(prose.substr(0,50))!=std::string::npos,"Frandroid nested layout regression");
  bool ok=true;
  extract("<article><p>"+std::string(RC::MAX_TEXT_BYTES+100,'x')+"</p></article>",&ok);
  check(!ok,"text capacity is not a successful extraction");
  std::mt19937 rng(1234);
  const std::string alphabet="<>/='\"!- abcdef\t\n&;";
  for (int i=0;i<500;++i) {
    std::string html;
    for (int j=0;j<200;++j) html+=alphabet[rng()%alphabet.size()];
    extract(html);
  }
  const std::string boundary="<article><div data-x='a > b' class='container-with-sidebar'><p>"+prose+"</p></div></article>";
  for (size_t n=0;n<=boundary.size();++n) extract(boundary.substr(0,n));
}
void cacheTests() {
  auto item=makeItem();
  std::string out;
  reset();
  check(fetch(item)==RC::CacheResult::FALLBACK_READY,"public network failure -> summary");
  check(testFiles.empty() && testWrites==0,"summary not persisted");
  check(load(item,out)==RC::CacheResult::FALLBACK_READY,"summary explicit load result");
  check(out=="Le resume du flux reste disponible.","summary sanitized with stop rules");
  check(testWrites==0,"summary reading does not write SD");
  const auto firstCalls=H::publicCalls;
  H::replies.push_back({page});
  check(fetch(item)==RC::CacheResult::READY,"next manual refresh obtains body");
  check(H::publicCalls==firstCalls+1,"retry not blocked by previous summary");
  check(load(item,out)==RC::CacheResult::READY && out.find("FIN_UTILE")!=std::string::npos,"body returned after retry");
  const auto cachedCalls=H::publicCalls;
  check(fetch(item)==RC::CacheResult::READY && H::publicCalls==cachedCalls,"valid body not redownloaded");
  reset();
  testFiles[RC::bodyPath(item)]="XRSS4\nAncien resume ambigu";
  H::replies.push_back({page});
  check(fetch(item)==RC::CacheResult::READY && H::publicCalls==1,"old cache invalidated");
  check(testFiles[RC::bodyPath(item)].rfind("XRSS5\n",0)==0,"new body cache version");
  reset();
  testFiles[RC::bodyPath(item)]="XRSS4\nAncien resume ambigu";
  check(load(item,out)==RC::CacheResult::FALLBACK_READY && out.find("Ancien")==std::string::npos,"stale cache never displayed as body");
  reset();
  H::replies.push_back({"<article>trop court</article>"});
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"extraction failure not cached");
  reset();
  H::replies.push_back({page});
  check(RC::ensureCached(item,"Test", "Le texte utile;FIN_UTILE", "", "", {})==RC::CacheResult::FALLBACK_READY,
        "over-cleaned body not cached");
  check(testFiles.empty(),"no file after cleaner failure");
  reset();
  testOom=true;
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"OOM leaves summary retriable");
  reset();
  testAuth=true; std::strcpy(item.link,"https://www.lefigaro.fr/test");
  check(fetch(item)==RC::CacheResult::FAILED && H::authCalls==1 && H::publicCalls==0,"AUTH failure never public fetch");
  check(load(item,out)==RC::CacheResult::FAILED && out.empty(),"AUTH failure never public summary display");
  check(testFiles.empty(),"AUTH failure no file");
  H::replies.push_back({page});
  check(fetch(item)==RC::CacheResult::READY && H::publicCalls==0,"AUTH retry can succeed");
  reset(); item=makeItem();
  H::replies.push_back({page}); testWriteFail=true;
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"SD write failure no partial cache");
  reset(); H::replies.push_back({page}); testSyncFail=true;
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"SD sync failure cleans temporary");
  reset(); H::replies.push_back({page}); testRenameFail=true;
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"SD rename failure cleans temporary");
  reset();
  check(fetch(item,[]{return true;})==RC::CacheResult::CANCELLED && H::publicCalls==0,"cancellation before I/O");
  reset(); H::replies.push_back({page});
  int polls=0;
  check(fetch(item,[&]{return ++polls>=3;})==RC::CacheResult::CANCELLED && testFiles.empty(),"cancellation during download");
  reset();
  H::replies.push_back({std::string(RC::MAX_HTML_BYTES+1,'x')});
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"oversized HTML is not cached truncated");
  reset();
  H::replies.push_back({"<article><p>"+std::string(RC::MAX_TEXT_BYTES+1,'x')+"</p></article>"});
  check(fetch(item)==RC::CacheResult::FALLBACK_READY && testFiles.empty(),"oversized text is not cached truncated");
  reset();
  std::strncpy(item.summary,prose.c_str(),sizeof(item.summary)-1);
  H::replies.push_back({page});
  check(fetch(item)==RC::CacheResult::READY,"article identical first paragraph to feed summary");
  check(load(item,out)==RC::CacheResult::READY && out.find(prose.substr(0,50))!=std::string::npos,"keep chapeau actually displayed only in body");
  reset();
  testFiles[RC::bodyPath(item)]="XRSS5\n";
  H::replies.push_back({page});
  check(fetch(item)==RC::CacheResult::READY && H::publicCalls==1,"empty marked body retried");
  reset();
  testFiles[RC::bodyPath(item)]="XRSS5\n"+prose;
  testReadFail=true;
  check(load(item,out)==RC::CacheResult::FALLBACK_READY,"read failure does not masquerade as loaded body");
  reset();
}
std::string readFile(const char* path) {
  std::ifstream stream(path,std::ios::binary);
  check(bool(stream),std::string("read fixture ")+path);
  return std::string(std::istreambuf_iterator<char>(stream),{});
}
int main(int argc,char** argv) {
  htmlTests(); cacheTests();
  if (argc>=3) {
    auto item=makeItem();
    const auto html=readFile(argv[1]);
    std::strcpy(item.link,"https://www.frandroid.com/bons-plans/3229397_test");
    std::string title=argc>=4?readFile(argv[3]):"";
    std::strncpy(item.title,title.c_str(),sizeof(item.title)-1);
    std::string drop,dropStart,stop;
    const auto feeds=readFile(argv[2]);
    const auto pos=feeds.find("\nFrandroid|");
    check(pos!=std::string::npos,"Frandroid config present");
    const auto line=feeds.substr(pos+1,feeds.find('\n',pos+1)-pos-1);
    const std::pair<const char*,std::string*> fields[] = {{"drop=", &drop}, {"dropstart=", &dropStart}, {"stop=", &stop}};
    for (const auto& field:fields) {
      const auto p=line.find(std::string("|")+field.first);
      if(p!=std::string::npos) { const auto start=p+1+std::strlen(field.first); *field.second=line.substr(start,line.find('|',start)-start); }
    }
    bool ok=false;
    const auto raw=extract(html,&ok);
    check(ok,"real HTML extracts");
    H::replies.push_back({html});
    check(RC::ensureCached(item,"Frandroid",drop.c_str(),dropStart.c_str(),stop.c_str(),{})==RC::CacheResult::READY,"real HTML cached as body");
    std::string text;
    check(RC::load(item,"Frandroid",drop.c_str(),dropStart.c_str(),stop.c_str(),text)==RC::CacheResult::READY,"real body loads");
    std::ofstream("frandroid-fixed.txt",std::ios::binary)<<text;
    std::ofstream("frandroid-extracted.txt",std::ios::binary)<<raw;
    std::cout<<"FRANDROID html="<<html.size()<<" extracted="<<raw.size()<<" cleaned="<<text.size()<<'\n';
  }
  check(testOpenFiles==0,"final no open files");
  std::cout<<"PASS "<<checks<<" checks; 500 randomized HTML inputs plus every prefix of a quoted-attribute fixture\n";
}
