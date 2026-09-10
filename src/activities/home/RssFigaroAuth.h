#pragma once

#include <cstdint>
#include <string>

#include "network/HttpDownloader.h"

namespace RssFigaroAuth {

// Returns true for HTTPS Figaro URLs with /RSS/figaro_auth.txt present (or a
// cookie loaded for this refresh). Invalid files must fail, not enable public
// fallback. The file content is never logged.
bool isConfiguredFor(const std::string& url);

// Cookie-scoped, versioned AUTH cache key, distinct from public/older transport
// caches. Returns 0 only when AUTH is not configured for this URL.
uint64_t cacheKeyFor(const std::string& url);

// Releases the RSS-local HTTP/TLS session and cookie. Call before/after a
// refresh. A fully consumed response may reuse its connection.
void resetSession();

// Uses ESP-IDF's perform() request path, which is the Figaro transport validated
// on X4 Pro, while consuming the body through HTTP events. Success requires a
// closing </article>; page data after it is discarded and its connection closed
// rather than waiting for an optional response tail. Redirects remain restricted
// to HTTPS Figaro hosts and AUTH never falls back to an anonymous request.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
