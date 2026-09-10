#pragma once

#include <cstdint>
#include <string>

#include "network/HttpDownloader.h"

namespace RssFigaroAuth {

// Returns true for HTTPS Figaro URLs with /RSS/figaro_auth.txt present (or a
// cookie loaded for this refresh). Invalid files must fail, not enable public
// fallback. The file content is never logged.
bool isConfiguredFor(const std::string& url);

// Cookie-scoped, versioned AUTH cache key, distinct from public/pre-stream
// caches. Returns 0 only when AUTH is not configured for this URL.
uint64_t cacheKeyFor(const std::string& url);

// Releases the RSS-local HTTP/TLS session and cookie. Call before/after a
// refresh; a fully drained persistent connection can serve the next article.
void resetSession();

// Explicit chunk reads with an inactivity timeout, not an overall deadline.
// Success requires a closing </article>. Large/unknown response tails are
// discarded with their socket; small tails may be drained for keep-alive.
// Redirects remain restricted to HTTPS Figaro hosts. No anonymous fallback.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
