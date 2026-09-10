#pragma once

#include <cstddef>
#include <cstdint>

// Temporary RSS-local instrumentation. No request/response headers, article
// text, URL paths, queries or cookies are written to the SD report.
namespace RssFetchDiagnostics {
constexpr char PATH[] = "/RSS/rss_diagnostic.tsv";
constexpr size_t MAX_REPORT_BYTES = 128U * 1024U;

struct Record {
  const char* transport = "cache";
  const char* phase = "unknown";
  uint32_t startedMs = 0;
  uint32_t openMs = 0;
  uint32_t headersMs = 0;
  uint32_t bodyMs = 0;
  uint32_t articleMs = 0;
  int result = 0;
  int64_t detail = 0;
  int httpStatus = -1;
  int64_t expected = -1;
  size_t received = 0;
  size_t stored = 0;
  size_t extracted = 0;
  size_t cleaned = 0;
  bool truncated = false;
  bool articleClosed = false;
  bool encoded = false;
  int socketError = 0;
  int tlsError = 0;
  int tlsFlags = 0;
};

uint32_t now();
// One report per manual refresh, replacing the previous diagnostic report only.
void begin();
void end();
// Called at attempt completion, never for individual data chunks. An SD error
// disables this report without changing the fetch/cache result.
void write(const char* url, const Record& record);
}  // namespace RssFetchDiagnostics
