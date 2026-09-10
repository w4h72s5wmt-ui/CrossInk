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

// Releases the RSS-local authentication state. Call before/after a refresh.
void resetSession();

// X4 Pro-only authenticated Figaro transport. It uses the already-linked
// wolfSSL stack directly inside the RSS app, validates the DigiCert chain and
// the requested Figaro hostname before sending the cookie, then streams an
// HTTP/1.1 response. Redirects remain restricted to HTTPS Figaro hosts and AUTH
// never falls back to an anonymous request.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
