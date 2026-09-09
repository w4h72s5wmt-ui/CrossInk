#include "RssFigaroAuth.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
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
constexpr size_t RX_BUFFER_SIZE = 4096;
constexpr size_t TX_BUFFER_SIZE = 1024;
constexpr int HTTP_TIMEOUT_MS = 15000;
constexpr uint8_t MAX_REDIRECTS = 5;
constexpr char ARTICLE_END[] = "</article>";

struct ParsedUrl {
  bool https = false;
  std::string host;
  std::string path;
  uint16_t port = 80;
};

struct Session {
  esp_http_client_handle_t client = nullptr;
  std::string cookie;
  bool cookieLoaded = false;
  std::string redirectLocation;
  const HttpDownloader::DataCallback* onData = nullptr;
  const HttpDownloader::CancelCallback* shouldCancel = nullptr;
  bool cancelled = false;
  bool earlyArticleEnd = false;
  char tail[sizeof(ARTICLE_END) - 1] = {};
  size_t tailLength = 0;
};

Session session;

bool parseUrl(const std::string& url, ParsedUrl& out) {
  const size_t schemeEnd = url.find("://");
  if (schemeEnd == std::string::npos) return false;
  const std::string scheme = url.substr(0, schemeEnd);
  out.https = scheme == "https";
  if (!out.https && scheme != "http") return false;

  const size_t hostStart = schemeEnd + 3;
  const size_t pathStart = url.find('/', hostStart);
  const std::string hostPort =
      url.substr(hostStart, pathStart == std::string::npos ? std::string::npos : pathStart - hostStart);
  out.path = pathStart == std::string::npos ? "/" : url.substr(pathStart);
  out.port = out.https ? 443 : 80;

  const size_t portSep = hostPort.rfind(':');
  if (portSep == std::string::npos) {
    out.host = hostPort;
  } else {
    out.host = hostPort.substr(0, portSep);
    const std::string portText = hostPort.substr(portSep + 1);
    if (portText.empty()) return false;
    uint32_t port = 0;
    for (const char c : portText) {
      if (c < '0' || c > '9') return false;
      port = port * 10U + static_cast<uint32_t>(c - '0');
      if (port > UINT16_MAX) return false;
    }
    if (port == 0) return false;
    out.port = static_cast<uint16_t>(port);
  }
  return !out.host.empty();
}

bool isFigaroHost(const std::string& host) {
  static constexpr char ROOT[] = "lefigaro.fr";
  if (strcasecmp(host.c_str(), ROOT) == 0) return true;
  const size_t hostLength = host.size();
  const size_t rootLength = sizeof(ROOT) - 1;
  if (hostLength <= rootLength || host[hostLength - rootLength - 1] != '.') return false;
  return strcasecmp(host.c_str() + hostLength - rootLength, ROOT) == 0;
}

bool isAllowedUrl(const std::string& url) {
  ParsedUrl parsed;
  return parseUrl(url, parsed) && parsed.https && parsed.port == 443 && isFigaroHost(parsed.host);
}

std::string buildRedirectUrl(const std::string& baseUrl, const std::string& location) {
  if (location.starts_with("https://") || location.starts_with("http://")) return location;
  ParsedUrl base;
  if (!parseUrl(baseUrl, base)) return {};
  std::string origin = base.https ? "https://" : "http://";
  origin += base.host;
  if ((base.https && base.port != 443) || (!base.https && base.port != 80)) {
    origin += ':';
    origin += std::to_string(base.port);
  }
  if (!location.empty() && location[0] == '/') return origin + location;
  const size_t slash = base.path.rfind('/');
  return origin + (slash == std::string::npos ? "/" : base.path.substr(0, slash + 1)) + location;
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
  if (start > 0) out.erase(0, start);

  static constexpr char PREFIX[] = "Cookie:";
  if (out.size() >= sizeof(PREFIX) - 1 && strncasecmp(out.c_str(), PREFIX, sizeof(PREFIX) - 1) == 0) {
    out.erase(0, sizeof(PREFIX) - 1);
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

uint64_t fnv1a64(const std::string& text) {
  uint64_t hash = 14695981039346656037ULL;
  for (const unsigned char c : text) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool cancelRequested() {
  if (!session.shouldCancel || !*session.shouldCancel) return false;
  if ((**session.shouldCancel)()) {
    session.cancelled = true;
    return true;
  }
  return false;
}

bool isRedirect(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

size_t findArticleEnd(const uint8_t* data, const size_t length) {
  if (!data || length == 0) return std::string::npos;
  constexpr size_t markerLength = sizeof(ARTICLE_END) - 1;
  char probe[markerLength * 2] = {};
  const size_t prefix = std::min(session.tailLength, markerLength - 1);
  std::memcpy(probe, session.tail + session.tailLength - prefix, prefix);
  const size_t copied = std::min(length, sizeof(probe) - prefix);
  std::memcpy(probe + prefix, data, copied);
  const size_t probeLength = prefix + copied;
  for (size_t i = 0; i + markerLength <= probeLength; ++i) {
    if (strncasecmp(probe + i, ARTICLE_END, markerLength) == 0) {
      if (i + markerLength <= prefix) return 0;
      return i + markerLength - prefix;
    }
  }
  return std::string::npos;
}

void rememberTail(const uint8_t* data, const size_t length) {
  constexpr size_t keep = sizeof(ARTICLE_END) - 2;
  session.tailLength = std::min(length, keep);
  if (session.tailLength > 0) std::memcpy(session.tail, data + length - session.tailLength, session.tailLength);
}

esp_err_t onHttpEvent(esp_http_client_event_t* event) {
  if (!event) return ESP_OK;
  if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value &&
      strcasecmp(event->header_key, "Location") == 0) {
    session.redirectLocation.assign(event->header_value);
    return ESP_OK;
  }
  if (event->event_id != HTTP_EVENT_ON_DATA || !event->data || event->data_len <= 0) return ESP_OK;
  if (cancelRequested()) return ESP_FAIL;
  if (!session.onData || !*session.onData) return ESP_FAIL;

  const auto* data = static_cast<const uint8_t*>(event->data);
  const size_t length = static_cast<size_t>(event->data_len);
  const size_t articleEnd = findArticleEnd(data, length);
  const size_t forwardLength = articleEnd == std::string::npos ? length : std::min(articleEnd, length);
  if (forwardLength > 0 && !(**session.onData)(data, forwardLength)) return ESP_FAIL;
  if (articleEnd != std::string::npos) {
    session.earlyArticleEnd = true;
    return ESP_FAIL;
  }
  rememberTail(data, length);
  return ESP_OK;
}

bool ensureClient(const std::string& url) {
  if (session.client) {
    return esp_http_client_set_url(session.client, url.c_str()) == ESP_OK;
  }

  esp_http_client_config_t config = {};
  config.url = url.c_str();
  config.buffer_size = RX_BUFFER_SIZE;
  config.buffer_size_tx = TX_BUFFER_SIZE;
  config.timeout_ms = HTTP_TIMEOUT_MS;
  config.crt_bundle_attach = esp_crt_bundle_attach;
  config.keep_alive_enable = true;
  config.disable_auto_redirect = true;
  config.event_handler = onHttpEvent;

  session.client = esp_http_client_init(&config);
  if (!session.client) return false;
  esp_http_client_set_header(session.client, "User-Agent", "Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)");
  esp_http_client_set_header(session.client, "Accept", "text/html,application/xhtml+xml");
  esp_http_client_set_header(session.client, "Connection", "keep-alive");
  return true;
}

void dropClient() {
  if (session.client) {
    esp_http_client_cleanup(session.client);
    session.client = nullptr;
  }
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  return isAllowedUrl(url) && ensureCookie();
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isAllowedUrl(url) || !ensureCookie()) return 0;
  return fnv1a64(session.cookie);
}

void resetSession() {
  dropClient();
  session.cookie.clear();
  session.cookieLoaded = false;
  session.redirectLocation.clear();
  session.onData = nullptr;
  session.shouldCancel = nullptr;
  session.cancelled = false;
  session.earlyArticleEnd = false;
  session.tailLength = 0;
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel) {
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) return HttpDownloader::HTTP_ERROR;

  std::string currentUrl = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (!isAllowedUrl(currentUrl)) return HttpDownloader::HTTP_ERROR;
    if (shouldCancel && shouldCancel()) return HttpDownloader::ABORTED;
    if (!ensureClient(currentUrl)) {
      dropClient();
      return HttpDownloader::HTTP_ERROR;
    }

    session.redirectLocation.clear();
    session.onData = &onData;
    session.shouldCancel = &shouldCancel;
    session.cancelled = false;
    session.earlyArticleEnd = false;
    session.tailLength = 0;
    esp_http_client_set_header(session.client, "Cookie", session.cookie.c_str());

    const esp_err_t result = esp_http_client_perform(session.client);
    const int status = esp_http_client_get_status_code(session.client);
    session.onData = nullptr;
    session.shouldCancel = nullptr;

    if (session.cancelled) {
      dropClient();
      return HttpDownloader::ABORTED;
    }
    if (session.earlyArticleEnd) {
      // The response body was intentionally cut after the complete <article>.
      // Drop this socket because unread HTTP bytes cannot be reused safely.
      dropClient();
      return status == 200 ? HttpDownloader::OK : HttpDownloader::HTTP_ERROR;
    }
    if (result != ESP_OK) {
      dropClient();
      return HttpDownloader::HTTP_ERROR;
    }

    if (isRedirect(status)) {
      if (session.redirectLocation.empty()) {
        dropClient();
        return HttpDownloader::HTTP_ERROR;
      }
      const std::string nextUrl = buildRedirectUrl(currentUrl, session.redirectLocation);
      if (nextUrl.empty() || !isAllowedUrl(nextUrl)) {
        dropClient();
        return HttpDownloader::HTTP_ERROR;
      }
      currentUrl = nextUrl;
      continue;
    }

    if (status != 200) return HttpDownloader::HTTP_ERROR;
    return HttpDownloader::OK;
  }

  dropClient();
  return HttpDownloader::HTTP_ERROR;
}

}  // namespace RssFigaroAuth
