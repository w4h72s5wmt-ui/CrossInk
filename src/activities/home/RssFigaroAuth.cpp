#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>
#include <SecureHttpClient.h>
#include <strings.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <string>

namespace RssFigaroAuth {
namespace {
constexpr char AUTH_PATH[] = "/RSS/figaro_auth.txt";
constexpr size_t MAX_AUTH_BYTES = 4096;
constexpr uint32_t HTTP_TIMEOUT_MS = 30000;
constexpr uint8_t MAX_REDIRECTS = 5;

struct ParsedUrl {
  std::string host;
  std::string path;
};

struct Session {
  std::string cookie;
  bool cookieLoaded = false;
  bool noResponseThisRefresh = false;
};
Session session;

bool parseUrl(const std::string& url, ParsedUrl& out) {
  static constexpr char PREFIX[] = "https://";
  if (url.size() <= sizeof(PREFIX) - 1 || strncasecmp(url.c_str(), PREFIX, sizeof(PREFIX) - 1) != 0) return false;
  const size_t hostStart = sizeof(PREFIX) - 1;
  const size_t pathStart = url.find_first_of("/?#", hostStart);
  const std::string authority =
      url.substr(hostStart, pathStart == std::string::npos ? std::string::npos : pathStart - hostStart);
  if (authority.empty() || authority.find(':') != std::string::npos ||
      authority.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-") !=
          std::string::npos) {
    return false;
  }
  out.host = authority;
  out.path = pathStart == std::string::npos ? "/" : url.substr(pathStart);
  if (out.path.empty() || out.path.front() != '/') out.path.insert(out.path.begin(), '/');
  return true;
}

bool isFigaroHost(const std::string& host) {
  static constexpr char ROOT[] = "lefigaro.fr";
  if (strcasecmp(host.c_str(), ROOT) == 0) return true;
  const size_t hostLength = host.size();
  const size_t rootLength = sizeof(ROOT) - 1;
  return hostLength > rootLength && host[hostLength - rootLength - 1] == '.' &&
         strcasecmp(host.c_str() + hostLength - rootLength, ROOT) == 0;
}

bool isAllowedUrl(const std::string& url) {
  ParsedUrl parsed;
  return parseUrl(url, parsed) && isFigaroHost(parsed.host);
}

std::string redirectUrl(const std::string& baseUrl, const std::string& location) {
  if (location.rfind("https://", 0) == 0) return location;
  if (location.rfind("//", 0) == 0) return "https:" + location;

  ParsedUrl base;
  if (!parseUrl(baseUrl, base)) return {};
  if (!location.empty() && location.front() == '/') return "https://" + base.host + location;

  const size_t query = base.path.find_first_of("?#");
  if (query != std::string::npos) base.path.erase(query);
  if (!location.empty() && location.front() == '?') return "https://" + base.host + base.path + location;

  const size_t slash = base.path.rfind('/');
  return "https://" + base.host + (slash == std::string::npos ? "/" : base.path.substr(0, slash + 1)) + location;
}

bool readCookie(std::string& out) {
  out.clear();
  if (!Storage.exists(AUTH_PATH)) return false;

  FsFile file;
  if (!Storage.openFileForRead("RSS", AUTH_PATH, file)) return false;
  const size_t bytes = std::min(static_cast<size_t>(file.size()), MAX_AUTH_BYTES + 1);
  if (bytes == 0 || bytes > MAX_AUTH_BYTES) {
    file.close();
    return false;
  }

  out.resize(bytes);
  const int read = file.read(out.data(), bytes);
  file.close();
  if (read <= 0) {
    out.clear();
    return false;
  }

  out.resize(static_cast<size_t>(read));
  while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back()))) out.pop_back();

  size_t start = 0;
  while (start < out.size() && std::isspace(static_cast<unsigned char>(out[start]))) ++start;
  if (start) out.erase(0, start);

  static constexpr char COOKIE_PREFIX[] = "Cookie:";
  if (out.size() >= sizeof(COOKIE_PREFIX) - 1 &&
      strncasecmp(out.c_str(), COOKIE_PREFIX, sizeof(COOKIE_PREFIX) - 1) == 0) {
    out.erase(0, sizeof(COOKIE_PREFIX) - 1);
    while (!out.empty() && std::isspace(static_cast<unsigned char>(out.front()))) out.erase(out.begin());
  }

  if (out.empty()) return false;
  for (const unsigned char c : out) {
    if (c < 0x20 || c == 0x7f) {
      out.clear();
      return false;
    }
  }
  return true;
}

bool ensureCookie() {
  if (session.cookieLoaded) return !session.cookie.empty();
  session.cookieLoaded = true;
  return readCookie(session.cookie);
}

uint64_t fnv1a64(const std::string& text, uint64_t hash = 14695981039346656037ULL) {
  for (const unsigned char c : text) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool isRedirectStatus(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  // Preserve the historical cache key so changing transport does not invalidate
  // already-downloaded Figaro bodies.
  const uint64_t hash = fnv1a64(session.cookie, fnv1a64("Figaro AUTH wolfSSL RTC v8"));
  return hash ? hash : 1;
}

void resetSession() {
  std::string().swap(session.cookie);
  session.cookieLoaded = false;
  session.noResponseThisRefresh = false;
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel) {
  RssFetchDiagnostics::Record d;
  d.startedMs = millis();
  d.transport = "figaro-auth-securehttp-v160";
  d.phase = "configuration";

  const auto finish = [&](const HttpDownloader::DownloadError result) {
    d.result = static_cast<int>(result);
    RssFetchDiagnostics::write(url.c_str(), d);
    return result;
  };

  if (shouldCancel && shouldCancel()) return finish(HttpDownloader::ABORTED);
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) return finish(HttpDownloader::HTTP_ERROR);
  if (session.noResponseThisRefresh) {
    d.phase = "circuit-open";
    return finish(HttpDownloader::HTTP_ERROR);
  }

  std::string current = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (shouldCancel && shouldCancel()) return finish(HttpDownloader::ABORTED);

    ParsedUrl parsed;
    if (!parseUrl(current, parsed) || !isFigaroHost(parsed.host)) {
      d.phase = "redirect";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    freeink::SecureHttpClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);

    // Use the exact wolfSSL-backed client already used by CrossInk v1.6's
    // working RSS transport. The verified custom Figaro path is incompatible
    // with this SDK's wolfSSL feature set, while ESP HTTP connects but stalls
    // before receiving response headers from Figaro.
    http.setInsecure();
    if (!http.begin(current)) {
      d.phase = "client-init";
      d.detail = -1021;
      session.noResponseThisRefresh = true;
      return finish(HttpDownloader::HTTP_ERROR);
    }

    http.setUserAgent("Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)");
    http.addHeader("Accept", "text/html,application/xhtml+xml");
    http.addHeader("Accept-Encoding", "identity");
    http.addHeader("Connection", "close");
    http.addHeader("Cookie", session.cookie);

    d.phase = "request";
    const uint32_t requestStart = millis();
    const int status = http.GET(
        [&http, &onData, &d](const uint8_t* data, const size_t len) {
          const int responseStatus = http.getStatus();
          if (responseStatus != 200) return true;
          if (d.expected < 0 && http.hasContentLength()) {
            d.expected = static_cast<int64_t>(http.getContentLength());
          }
          d.received += len;
          if (!onData(data, len)) return false;
          d.stored += len;
          return true;
        },
        [&shouldCancel]() { return shouldCancel && shouldCancel(); });
    d.bodyMs += millis() - requestStart;

    if (http.aborted()) return finish(HttpDownloader::ABORTED);

    d.httpStatus = status;
    if (http.hasContentLength()) d.expected = static_cast<int64_t>(http.getContentLength());

    if (status < 0) {
      d.phase = "request";
      d.detail = status;
      session.noResponseThisRefresh = true;
      return finish(HttpDownloader::HTTP_ERROR);
    }

    if (isRedirectStatus(status)) {
      const std::string location = http.getHeader("location");
      const std::string next = redirectUrl(current, location);
      if (location.empty() || !isAllowedUrl(next)) {
        d.phase = "redirect";
        return finish(HttpDownloader::HTTP_ERROR);
      }
      current = next;
      continue;
    }

    if (status != 200) {
      d.phase = "http-status";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    if (http.callbackAborted()) {
      d.phase = "body-callback";
      d.detail = -1012;
      return finish(HttpDownloader::HTTP_ERROR);
    }

    if (!http.responseComplete()) {
      d.phase = "incomplete";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    d.phase = "body-ready";
    return finish(HttpDownloader::OK);
  }

  d.phase = "redirect-limit";
  return finish(HttpDownloader::HTTP_ERROR);
}

}  // namespace RssFigaroAuth
