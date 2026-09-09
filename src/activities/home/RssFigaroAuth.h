#pragma once

#include <cstdint>
#include <string>

#include "network/HttpDownloader.h"

namespace RssFigaroAuth {

// Returns true only for HTTPS Figaro article URLs when /RSS/figaro_auth.txt
// exists. The file content is never logged.
bool isConfiguredFor(const std::string& url);

// Hashes the validated cookie value for cache namespacing. Returns 0 when no
// usable Figaro session is available for this URL.
uint64_t cacheKeyFor(const std::string& url);

// Releases the RSS-local HTTP/TLS session. Call before/after a refresh so the
// connection can be reused across Figaro articles without retaining TLS heap
// while the user reads offline.
void resetSession();

// Streams one authenticated Figaro request through the RSS-local ESP-IDF
// client. The connection is reused when the response tail is small; if a full
// <article> ends far before the HTTP body, the useless tail is cut and that
// connection is discarded. Redirects remain restricted to HTTPS Figaro hosts.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
