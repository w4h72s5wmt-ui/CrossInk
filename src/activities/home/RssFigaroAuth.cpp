#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>
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

struct Session {
  std::string cookie;
  bool cookieLoaded = false;
  bool noResponseThisRefresh = false;
};

struct RequestContext {
  std::string* redirectLocation = nullptr;
  RssFetchDiagnostics::Record* diagnostic = nullptr;
};

Session session;

bool parseUrl(const std::string& url, ParsedUrl& out) {
  const size_t schemeEnd = url.find("://");
  if (schemeEnd == std::string::npos) return false;
  const std::string scheme = url.substr(0, schemeEnd);
  out.https = scheme == "https";
  if (!out.https && scheme != "http") return false;

  const size_t hostStart = schemeEnd + 3;
  const size_t pathStart = url.find_first_of("/?#", hostStart);
  const std::string hostPort =
      url.substr(hostStart, pathStart == std::string::npos ? std::string::npos : pathStart - hostStart);
  out.path = pathStart == std::string::npos ? "/" : url.substr(pathStart);
  if (out.path.front() != '/') out.path.insert(out.path.begin(), '/');
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

  return !out.host.empty() &&
         out.host.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-") ==
             std::string::npos;
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
  if (location.starts_with("//")) return "https:" + location;
  ParsedUrl base;
  if (!parseUrl(baseUrl, base)) return {};
  const std::string origin = "https://" + base.host;
  if (!location.empty() && location[0] == '/') return origin + location;
  const size_t query = base.path.find_first_of("?#");
  if (query != std::string::npos) base.path.erase(query);
  if (!location.empty() && location[0] == '?') return origin + base.path + location;
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

uint64_t fnv1a64(const std::string& text, uint64_t hash = 14695981039346656037ULL) {
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

esp_err_t onHttpEvent(esp_http_client_event_t* event) {
  if (!event) return ESP_OK;
  auto* context = static_cast<RequestContext*>(event->user_data);
  if (!context) return ESP_OK;
  if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value) {
    if (context->diagnostic && context->diagnostic->headersMs == 0) {
      context->diagnostic->headersMs = static_cast<uint32_t>(millis() - context->diagnostic->startedMs);
    }
    if (context->redirectLocation && strcasecmp(event->header_key, "Location") == 0) {
      context->redirectLocation->assign(event->header_value);
    }
  }
  return ESP_OK;
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  const uint64_t hash = fnv1a64(session.cookie, fnv1a64("Figaro AUTH close60 v4"));
  return hash != 0 ? hash : 1;
}

void resetSession() {
  std::string().swap(session.cookie);
  session.cookieLoaded = false;
  session.noResponseThisRefresh = false;
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel) {
  RssFetchDiagnostics::Record diagnostic;
  diagnostic.startedMs = millis();
  diagnostic.transport = "figaro-auth-close60";
  diagnostic.phase = "configuration";
  const auto finish = [&](const HttpDownloader::DownloadError result) {
    diagnostic.result = static_cast<int>(result);
    RssFetchDiagnostics::write(url.c_str(), diagnostic);
    return result;
  };

  if (cancelRequested(shouldCancel)) return finish(HttpDownloader::ABORTED);
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) return finish(HttpDownloader::HTTP_ERROR);
  if (session.noResponseThisRefresh) {
    diagnostic.phase = "circuit-open";
    return finish(HttpDownloader::HTTP_ERROR);
  }

  auto buffer = makePsramByteBufferNoThrow(RX_BUFFER_SIZE);
  if (!buffer) {
    diagnostic.phase = "buffer-allocation";
    return finish(HttpDownloader::HTTP_ERROR);
  }

  std::string currentUrl = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (cancelRequested(shouldCancel)) return finish(HttpDownloader::ABORTED);
    if (!isAllowedUrl(currentUrl)) return finish(HttpDownloader::HTTP_ERROR);

    std::string redirectLocation;
    RequestContext context{&redirectLocation, &diagnostic};
    esp_http_client_config_t config = {};
    config.url = currentUrl.c_str();
    config.buffer_size = RX_BUFFER_SIZE;
    config.buffer_size_tx = std::max(TX_BUFFER_SIZE, session.cookie.size() + sizeof("Cookie: \r\n"));
    config.timeout_ms = HTTP_TIMEOUT_MS;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.keep_alive_enable = false;
    config.event_handler = onHttpEvent;
    config.user_data = &context;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
      diagnostic.phase = "client-init";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    const auto cleanup = [&]() { esp_http_client_cleanup(client); };
    esp_http_client_set_header(client, "User-Agent", "Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)");
    esp_http_client_set_header(client, "Accept", "text/html,application/xhtml+xml");
    esp_http_client_set_header(client, "Connection", "close");
    esp_http_client_set_header(client, "Cookie", session.cookie.c_str());

    diagnostic.phase = "open";
    const uint32_t openStart = millis();
    const esp_err_t openError = esp_http_client_open(client, 0);
    diagnostic.openMs += static_cast<uint32_t>(millis() - openStart);
    diagnostic.detail = openError;
    if (openError != ESP_OK) {
      diagnostic.socketError = esp_http_client_get_errno(client);
      esp_http_client_get_and_clear_last_tls_error(client, &diagnostic.tlsError, &diagnostic.tlsFlags);
      cleanup();
      return finish(cancelRequested(shouldCancel) ? HttpDownloader::ABORTED : HttpDownloader::HTTP_ERROR);
    }

    diagnostic.phase = "headers";
    const uint32_t headerStart = millis();
    const int64_t responseLength = esp_http_client_fetch_headers(client);
    if (diagnostic.headersMs == 0) diagnostic.headersMs = static_cast<uint32_t>(millis() - headerStart);
    diagnostic.detail = responseLength;
    diagnostic.httpStatus = esp_http_client_get_status_code(client);
    diagnostic.expected = responseLength;
    if (responseLength < 0) {
      diagnostic.socketError = esp_http_client_get_errno(client);
      esp_http_client_get_and_clear_last_tls_error(client, &diagnostic.tlsError, &diagnostic.tlsFlags);
      if (diagnostic.httpStatus <= 0 && diagnostic.received == 0) session.noResponseThisRefresh = true;
      cleanup();
      return finish(HttpDownloader::HTTP_ERROR);
    }

    const int status = diagnostic.httpStatus;
    if (isRedirect(status)) {
      cleanup();
      const std::string nextUrl = buildRedirectUrl(currentUrl, redirectLocation);
      if (redirectLocation.empty() || !isAllowedUrl(nextUrl)) {
        diagnostic.phase = "redirect";
        return finish(HttpDownloader::HTTP_ERROR);
      }
      currentUrl = nextUrl;
      continue;
    }

    if (status != 200) {
      cleanup();
      diagnostic.phase = "http-status";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    diagnostic.phase = "body";
    const uint32_t bodyStart = millis();
    while (true) {
      if (cancelRequested(shouldCancel)) {
        cleanup();
        return finish(HttpDownloader::ABORTED);
      }
      const int read = esp_http_client_read(client, reinterpret_cast<char*>(buffer.get()), RX_BUFFER_SIZE);
      diagnostic.bodyMs = static_cast<uint32_t>(millis() - bodyStart);
      diagnostic.detail = read;
      if (read < 0) {
        diagnostic.socketError = esp_http_client_get_errno(client);
        esp_http_client_get_and_clear_last_tls_error(client, &diagnostic.tlsError, &diagnostic.tlsFlags);
        cleanup();
        return finish(HttpDownloader::HTTP_ERROR);
      }
      if (read == 0) break;
      const size_t length = static_cast<size_t>(read);
      diagnostic.received += length;
      if (!onData(buffer.get(), length)) {
        cleanup();
        diagnostic.phase = "receiver";
        return finish(cancelRequested(shouldCancel) ? HttpDownloader::ABORTED : HttpDownloader::FILE_ERROR);
      }
      diagnostic.stored += length;
      delay(0);
    }

    const bool complete = esp_http_client_is_complete_data_received(client);
    cleanup();
    diagnostic.phase = complete ? "response-end" : "incomplete-body";
    return finish(complete ? HttpDownloader::OK : HttpDownloader::HTTP_ERROR);
  }

  diagnostic.phase = "redirect-limit";
  return finish(HttpDownloader::HTTP_ERROR);
}

}  // namespace RssFigaroAuth
