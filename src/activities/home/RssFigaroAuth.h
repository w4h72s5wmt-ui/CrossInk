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

// Streams one authenticated Figaro request through ESP-IDF. Redirects are
// followed only while they stay on HTTPS lefigaro.fr / *.lefigaro.fr.
HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel);

}  // namespace RssFigaroAuth
