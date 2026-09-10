#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>

#include <cstdio>
#include <cstring>

namespace RssFetchDiagnostics {
namespace {
FsFile report;
bool active = false;
size_t written = 0;

void append(const char* data, const size_t length) {
  if (!active) return;
  if (length > MAX_REPORT_BYTES - written ||
      report.write(reinterpret_cast<const uint8_t*>(data), length) != length || !report.sync()) {
    report.close();
    active = false;
    return;
  }
  written += length;
}

void hostFor(const char* url, char* out, const size_t capacity) {
  if (capacity == 0) return;
  out[0] = '\0';
  if (!url) return;
  const char* scheme = std::strstr(url, "://");
  if (!scheme) return;
  const char* begin = scheme + 3;
  const char* end = begin + std::strcspn(begin, "/?#");
  // A malformed authority must not expose URL credentials or control bytes.
  for (const char* p = begin; p < end; ++p) {
    const unsigned char c = static_cast<unsigned char>(*p);
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '.' || c == '-' || c == ':')) return;
  }
  size_t length = static_cast<size_t>(end - begin);
  if (length >= capacity) length = capacity - 1;
  std::memcpy(out, begin, length);
  out[length] = '\0';
}

uint64_t urlId(const char* url) {
  uint64_t value = 14695981039346656037ULL;
  if (url) {
    while (*url) {
      value ^= static_cast<uint8_t>(*url++);
      value *= 1099511628211ULL;
    }
  }
  return value;
}
}  // namespace

uint32_t now() { return millis(); }

void begin() {
  end();
  written = 0;
  Storage.ensureDirectoryExists("/RSS");
  if (!Storage.openFileForWrite("RSS", PATH, report)) {
    LOG_ERR("RSS", "Cannot open RSS diagnostic report");
    return;
  }
  active = true;
  static constexpr char HEADER[] =
      "# RSS diagnostic v1; one manual refresh; timings in ms; sizes in bytes.\n"
      "# No cookies, header values, article text or URL paths/queries. url_id is a correlation hash.\n"
      "# HTTP=-1: unavailable through the existing public downloader, or no status received yet.\n"
      "# result=DownloadError; detail=underlying ESP-IDF/read code for figaro-auth.\n"
      "host\turl_id\ttransport\tphase\tresult\tdetail\thttp\texpected\treceived\tstored\textracted\tcleaned"
      "\ttruncated\tarticle_closed\tencoded\ttotal_ms\topen_ms\theaders_ms\tbody_ms\tarticle_ms\terrno\ttls_error\ttls_flags\n";
  append(HEADER, sizeof(HEADER) - 1);
}

void end() {
  if (active) {
    static constexpr char END[] = "# end\n";
    append(END, sizeof(END) - 1);
    report.close();
    active = false;
  }
}

void write(const char* url, const Record& r) {
  if (!active) return;
  const uint32_t elapsed = now() - r.startedMs;
  char host[80];
  hostFor(url, host, sizeof(host));
  char line[512];
  const int length = std::snprintf(
      line, sizeof(line),
      "%s\t%016llx\t%s\t%s\t%d\t%lld\t%d\t%lld\t%zu\t%zu\t%zu\t%zu\t%d\t%d\t%d"
      "\t%lu\t%lu\t%lu\t%lu\t%lu\t%d\t%d\t%d\n",
      host, static_cast<unsigned long long>(urlId(url)), r.transport, r.phase, r.result,
      static_cast<long long>(r.detail), r.httpStatus, static_cast<long long>(r.expected),
      r.received, r.stored, r.extracted, r.cleaned, static_cast<int>(r.truncated),
      static_cast<int>(r.articleClosed), static_cast<int>(r.encoded), static_cast<unsigned long>(elapsed),
      static_cast<unsigned long>(r.openMs), static_cast<unsigned long>(r.headersMs),
      static_cast<unsigned long>(r.bodyMs), static_cast<unsigned long>(r.articleMs),
      r.socketError, r.tlsError, r.tlsFlags);
  if (length > 0 && static_cast<size_t>(length) < sizeof(line)) append(line, static_cast<size_t>(length));
}
}  // namespace RssFetchDiagnostics
