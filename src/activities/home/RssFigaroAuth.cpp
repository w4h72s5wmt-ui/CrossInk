#include "RssFigaroAuth.h"

#include <HalStorage.h>
#include <WiFi.h>
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
constexpr int HTTP_TIMEOUT_MS = 60000;
constexpr uint8_t MAX_REDIRECTS = 5;

struct ParsedUrl {
  bool https = false;
  std::string host;
  std::string path;
  uint16_t port = 80;
};

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

esp_err_t captureLocationHeader(esp_http_client_event_t* event) {
  auto* location = static_cast<std::string*>(event->user_data);
  if (location && event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value &&
      strcasecmp(event->header_key, "Location") == 0) {
    location->assign(event->header_value);
  }
  return ESP_OK;
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

uint64_t fnv1a64(const std::string& text) {
  uint64_t hash = 14695981039346656037ULL;
  for (const unsigned char c : text) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool cancelRequested(const HttpDownloader::CancelCallback& shouldCancel) {
  return shouldCancel && shouldCancel();
}

bool isRedirect(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  if (!isAllowedUrl(url)) return false;
  std::string cookie;
  return readCookie(cookie);
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isAllowedUrl(url)) return 0;
  std::string cookie;
  if (!readCookie(cookie)) return 0;
  return fnv1a64(cookie);
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel) {
  if (!onData || !isAllowedUrl(url)) return HttpDownloader::HTTP_ERROR;

  std::string cookie;
  if (!readCookie(cookie)) return HttpDownloader::HTTP_ERROR;
  std::string currentUrl = url;

  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (cancelRequested(shouldCancel)) return HttpDownloader::ABORTED;
    if (!isAllowedUrl(currentUrl)) return HttpDownloader::HTTP_ERROR;

    std::string redirectLocation;
    esp_http_client_config_t config = {};
    config.url = currentUrl.c_str();
    config.buffer_size = RX_BUFFER_SIZE;
    config.buffer_size_tx = TX_BUFFER_SIZE;
    config.timeout_ms = HTTP_TIMEOUT_MS;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.keep_alive_enable = false;
    config.event_handler = captureLocationHeader;
    config.user_data = &redirectLocation;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return HttpDownloader::HTTP_ERROR;
    esp_http_client_set_header(client, "User-Agent", "Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)");
    esp_http_client_set_header(client, "Accept", "text/html,application/xhtml+xml");
    esp_http_client_set_header(client, "Connection", "close");
    esp_http_client_set_header(client, "Cookie", cookie.c_str());

    esp_err_t error = esp_http_client_open(client, 0);
    if (error != ESP_OK) {
      esp_http_client_cleanup(client);
      return HttpDownloader::HTTP_ERROR;
    }
    const int64_t responseLength = esp_http_client_fetch_headers(client);
    const int status = esp_http_client_get_status_code(client);
    if (responseLength < 0) {
      esp_http_client_cleanup(client);
      return HttpDownloader::HTTP_ERROR;
    }

    if (isRedirect(status)) {
      esp_http_client_cleanup(client);
      if (redirectLocation.empty()) return HttpDownloader::HTTP_ERROR;
      const std::string nextUrl = buildRedirectUrl(currentUrl, redirectLocation);
      if (nextUrl.empty() || !isAllowedUrl(nextUrl)) return HttpDownloader::HTTP_ERROR;
      currentUrl = nextUrl;
      continue;
    }

    if (status != 200) {
      esp_http_client_cleanup(client);
      return HttpDownloader::HTTP_ERROR;
    }

    uint8_t buffer[RX_BUFFER_SIZE];
    while (true) {
      if (cancelRequested(shouldCancel)) {
        esp_http_client_cleanup(client);
        return HttpDownloader::ABORTED;
      }
      const int read = esp_http_client_read(client, reinterpret_cast<char*>(buffer), sizeof(buffer));
      if (read < 0) {
        esp_http_client_cleanup(client);
        return HttpDownloader::HTTP_ERROR;
      }
      if (read == 0) break;
      if (!onData(buffer, static_cast<size_t>(read))) {
        esp_http_client_cleanup(client);
        return HttpDownloader::FILE_ERROR;
      }
      delay(0);
    }

    const bool complete = esp_http_client_is_complete_data_received(client);
    esp_http_client_cleanup(client);
    return complete ? HttpDownloader::OK : HttpDownloader::HTTP_ERROR;
  }

  return HttpDownloader::HTTP_ERROR;
}

}  // namespace RssFigaroAuth
