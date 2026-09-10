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

// Uses ESP-IDF's perform() request path, which previously received Figaro
// responses correctly on X4 Pro, while streaming body chunks directly into the
// RSS article buffer. Success requires HTTP 200 and at least one complete
// <article>...</article>. If the transport times out only after that point, the
// received page is still handed to the editorial-root extractor. Redirects stay
// restricted to HTTPS Figaro hosts and AUTH never falls back to anonymous mode.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
