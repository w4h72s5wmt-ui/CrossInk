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
constexpr size_t READ_CHUNK_SIZE = 1024;
constexpr int CONNECT_TIMEOUT_MS = 15000;
constexpr int READ_POLL_MS = 1000;
constexpr uint32_t IDLE_TIMEOUT_MS = 15000;
constexpr uint8_t MAX_REDIRECTS = 5;
constexpr size_t KEEPALIVE_TAIL_LIMIT = 64U * 1024U;
constexpr char ARTICLE_START[] = "<article";
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
  bool encodedResponse = false;
  uint32_t lastProgressMs = 0;
};

struct ArticleBoundary {
  bool seen = false;
  bool closed = false;
  char tail[sizeof(ARTICLE_END) - 1] = {};
  size_t tailLength = 0;

  char byteAt(const uint8_t* data, const size_t index) const {
    return index < tailLength ? tail[index] : static_cast<char>(data[index - tailLength]);
  }

  size_t find(const uint8_t* data, const size_t length, const char* marker, const size_t start = 0) const {
    const size_t markerLength = std::strlen(marker);
    const size_t combinedLength = tailLength + length;
    for (size_t i = start; i + markerLength <= combinedLength; ++i) {
      size_t j = 0;
      while (j < markerLength &&
             std::tolower(static_cast<unsigned char>(byteAt(data, i + j))) == marker[j]) ++j;
      if (j == markerLength) return i + markerLength;
    }
    return std::string::npos;
  }

  // Returns the useful prefix of this chunk, including a split closing tag.
  size_t consume(const uint8_t* data, const size_t length) {
    if (closed) return 0;
    size_t start = 0;
    if (!seen) {
      start = find(data, length, ARTICLE_START);
      if (start != std::string::npos) seen = true;
    }
    if (seen) {
      const size_t end = find(data, length, ARTICLE_END, start);
      if (end != std::string::npos) {
        closed = true;
        return end > tailLength ? end - tailLength : 0;
      }
    }

    const size_t keep = sizeof(tail);
    if (length >= keep) {
      tailLength = keep;
      std::memcpy(tail, data + length - keep, keep);
    } else {
      const size_t oldKeep = std::min(tailLength, keep - length);
      if (oldKeep > 0) std::memmove(tail, tail + tailLength - oldKeep, oldKeep);
      std::memcpy(tail + oldKeep, data, length);
      tailLength = oldKeep + length;
    }
    return length;
  }
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
  // Do not let userinfo or URL delimiters disguise a non-Figaro host.
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
  if (read != static_cast<int>(bytes)) {
    out.clear();
    return false;
  }

  while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back()))) out.pop_back();
  size_t start = 0;
  while (start < out.size() && std::isspace(static_cast<unsigned char>(out[start]))) ++start;
  if (start > 0) out.erase(0, start);
  if (start > 0) {} 

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

bool isRedirect(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

esp_err_t onHttpEvent(esp_http_client_event_t* event) {
  if (!event) return ESP_OK;
  if (event->event_id == HTTP_EVENT_ON_HEADER || event->event_id == HTTP_EVENT_ON_DATA) {
    session.lastProgressMs = millis();
  }
  if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value) {
    if (strcasecmp(event->header_key, "Location") == 0) session.redirectLocation.assign(event->header_value);
    if (strcasecmp(event->header_key, "Content-Encoding") == 0 &&
        strcasecmp(event->header_value, "identity") != 0) session.encodedResponse = true;
  }
  // fetch_headers may already receive body bytes. ESP-IDF buffers them for
  // read(); forwarding ON_DATA here would duplicate them or leak redirect HTML.
  return ESP_OK;
}

void dropClient() {
  if (session.client) {
    esp_http_client_cleanup(session.client);
    session.client = nullptr;
  }
}

bool ensureClient(const std::string& url) {
  if (session.client) return esp_http_client_set_url(session.client, url.c_str()) == ESP_OK;

  esp_http_client_config_t config = {};
  config.url = url.c_str();
  config.buffer_size = RX_BUFFER_SIZE;
  // A cookie is one header; it must fit even when it exceeds the usual 1 KiB.
  config.buffer_size_tx = std::max(TX_BUFFER_SIZE, session.cookie.size() + sizeof("Cookie: \r\n"));
  config.timeout_ms = CONNECT_TIMEOUT_MS;
  config.crt_bundle_attach = esp_crt_bundle_attach;
  config.keep_alive_enable = true;
  config.disable_auto_redirect = true;
  config.event_handler = onHttpEvent;

  session.client = esp_http_client_init(&config);
  if (!session.client) return false;
  return esp_http_client_set_header(session.client, "User-Agent", "Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)") == ESP_OK &&
         esp_http_client_set_header(session.client, "Accept", "text/html,application/xhtml+xml") == ESP_OK &&
         esp_http_client_set_header(session.client, "Accept-Encoding", "identity") == ESP_OK &&
         esp_http_client_set_header(session.client, "Connection", "keep-alive") == ESP_OK;
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  // A present but invalid auth file is an AUTH failure, never anonymous mode.
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  // Ignore pre-stream caches, which may contain an anonymous rescue body.
  const uint64_t hash = fnv1a64(session.cookie, fnv1a64("Figaro AUTH stream v2"));
  return hash != 0 ? hash : 1;
}

void resetSession() {
  dropClient();
  std::string().swap(session.cookie);
  session.cookieLoaded = false;
  std::string().swap(session.redirectLocation);
  session.encodedResponse = false;
  session.lastProgressMs = 0;
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData,
                                        const HttpDownloader::CancelCallback& shouldCancel) {
  RssFetchDiagnostics::Record diagnostic;
  diagnostic.startedMs = millis();
  diagnostic.transport = "figaro-auth";
  diagnostic.phase = "configuration";
  const auto finish = [&](const HttpDownloader::DownloadError result, const bool discard) {
    diagnostic.result = static_cast<int>(result);
    if (session.client && result != HttpDownloader::OK) {
      diagnostic.socketError = esp_http_client_get_errno(session.client);
      esp_http_client_get_and_clear_last_tls_error(session.client, &diagnostic.tlsError, &diagnostic.tlsFlags);
    }
    // Record before cleanup loses the transport's last error. No header values
    // or HTML are handed to the reporter, and a log failure cannot affect result.
    RssFetchDiagnostics::write(url.c_str(), diagnostic);
    if (discard) dropClient();
    return result;
  };
  const auto fail = [&](const HttpDownloader::DownloadError error) { return finish(error, true); };
  const auto cancelled = [&]() { return shouldCancel && shouldCancel(); };
  if (cancelled()) return fail(HttpDownloader::ABORTED);
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) {
    LOG_ERR("RSS", "Figaro AUTH: invalid URL, cookie or callback");
    return fail(HttpDownloader::HTTP_ERROR);
  }

  // X4 Pro scratch lives in PSRAM, not on the activity/task stack.
  diagnostic.phase = "buffer-allocation";
  auto buffer = makePsramByteBufferNoThrow(READ_CHUNK_SIZE);
  if (!buffer) return fail(HttpDownloader::HTTP_ERROR);

  std::string currentUrl = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (cancelled()) return fail(HttpDownloader::ABORTED);
    diagnostic.phase = "client-init";
    if (!isAllowedUrl(currentUrl) || !ensureClient(currentUrl)) return fail(HttpDownloader::HTTP_ERROR);
    session.redirectLocation.clear();
    session.encodedResponse = false;
    diagnostic.phase = "request-setup";
    esp_err_t error = esp_http_client_set_timeout_ms(session.client, CONNECT_TIMEOUT_MS);
    if (error == ESP_OK) error = esp_http_client_set_header(session.client, "Cookie", session.cookie.c_str());
    if (error != ESP_OK) {
      diagnostic.detail = error;
      return fail(cancelled() ? HttpDownloader::ABORTED : HttpDownloader::HTTP_ERROR);
    }
    diagnostic.phase = "open";
    uint32_t stageStart = millis();
    error = esp_http_client_open(session.client, 0);
    diagnostic.openMs += static_cast<uint32_t>(millis() - stageStart);
    diagnostic.detail = error;
    if (error != ESP_OK) {
      LOG_ERR("RSS", "Figaro AUTH: connection/request failed");
      return fail(cancelled() ? HttpDownloader::ABORTED : HttpDownloader::HTTP_ERROR);
    }

    diagnostic.phase = "read-setup";
    error = esp_http_client_set_timeout_ms(session.client, READ_POLL_MS);
    diagnostic.detail = error;
    if (error != ESP_OK) return fail(HttpDownloader::HTTP_ERROR);
    session.lastProgressMs = millis();
    diagnostic.phase = "headers";
    stageStart = millis();
    int64_t contentLength;
    while (true) {
      if (cancelled()) return fail(HttpDownloader::ABORTED);
      contentLength = esp_http_client_fetch_headers(session.client);
      diagnostic.detail = contentLength;
      if (contentLength >= 0) break;
      if (contentLength != -ESP_ERR_HTTP_EAGAIN ||
          static_cast<uint32_t>(millis() - session.lastProgressMs) >= IDLE_TIMEOUT_MS) {
        diagnostic.headersMs += static_cast<uint32_t>(millis() - stageStart);
        diagnostic.httpStatus = esp_http_client_get_status_code(session.client);
        LOG_ERR("RSS", "Figaro AUTH: headers failed (%lld)", static_cast<long long>(contentLength));
        return fail(HttpDownloader::HTTP_ERROR);
      }
      delay(1);
    }
    diagnostic.headersMs += static_cast<uint32_t>(millis() - stageStart);
    diagnostic.expected = contentLength;
    if (cancelled()) return fail(HttpDownloader::ABORTED);

    const int status = esp_http_client_get_status_code(session.client);
    diagnostic.httpStatus = status;
    diagnostic.encoded = session.encodedResponse;
    if (isRedirect(status)) {
      diagnostic.phase = "redirect";
      const std::string nextUrl = buildRedirectUrl(currentUrl, session.redirectLocation);
      // Never reuse a socket with an unread redirect body, nor send cookies
      // outside the HTTPS Figaro allowlist.
      dropClient();
      if (session.redirectLocation.empty() || !isAllowedUrl(nextUrl)) return fail(HttpDownloader::HTTP_ERROR);
      currentUrl = nextUrl;
      continue;
    }
    if (status != 200 || session.encodedResponse) {
      diagnostic.phase = session.encodedResponse ? "encoded-response" : "http-status";
      LOG_ERR("RSS", "Figaro AUTH: rejected HTTP response (%d, encoded=%d)", status, session.encodedResponse);
      return fail(HttpDownloader::HTTP_ERROR);
    }

    ArticleBoundary article;
    size_t bytesReceived = 0;
    diagnostic.phase = "body";
    stageStart = millis();
    while (true) {
      if (cancelled()) return fail(HttpDownloader::ABORTED);
      const int read = esp_http_client_read(session.client, reinterpret_cast<char*>(buffer.get()), READ_CHUNK_SIZE);
      diagnostic.bodyMs = static_cast<uint32_t>(millis() - stageStart);
      diagnostic.detail = read;
      if (cancelled()) return fail(HttpDownloader::ABORTED);
      if (read > 0) {
        session.lastProgressMs = millis();
        const size_t length = static_cast<size_t>(read);
        const size_t useful = article.consume(buffer.get(), length);
        diagnostic.received += length;
        if (article.closed && !diagnostic.articleClosed) {
          diagnostic.articleClosed = true;
          diagnostic.articleMs = static_cast<uint32_t>(millis() - diagnostic.startedMs);
        }
        if (useful > 0 && !onData(buffer.get(), useful)) {
          diagnostic.phase = "receiver";
          LOG_ERR("RSS", "Figaro AUTH: receiver rejected data");
          return fail(cancelled() ? HttpDownloader::ABORTED : HttpDownloader::HTTP_ERROR);
        }
        diagnostic.stored += useful;
        bytesReceived += length;
        if (article.closed) {
          diagnostic.phase = "tail";
          const uint64_t remaining = contentLength > 0 && static_cast<uint64_t>(contentLength) > bytesReceived
                                         ? static_cast<uint64_t>(contentLength) - bytesReceived
                                         : 0;
          if (contentLength <= 0 || remaining > KEEPALIVE_TAIL_LIMIT) {
            diagnostic.phase = "article-end";
            return finish(HttpDownloader::OK, true);
          }
        }
        continue;
      }

      if (read == 0 && esp_http_client_is_complete_data_received(session.client)) {
        if (!article.closed) {
          diagnostic.phase = "missing-article-end";
          LOG_ERR("RSS", "Figaro AUTH: response ended before </article> (%zu bytes)", bytesReceived);
          return fail(HttpDownloader::HTTP_ERROR);
        }
        diagnostic.phase = "response-end";
        return finish(HttpDownloader::OK, !esp_http_client_is_persistent_connection(session.client));
      }
      const bool idle = static_cast<uint32_t>(millis() - session.lastProgressMs) >= IDLE_TIMEOUT_MS;
      if ((read < 0 && read != -ESP_ERR_HTTP_EAGAIN) || idle) {
        // Preserve 225 semantics. The diagnostic now distinguishes a completed
        // article followed by a tail timeout from an actual failed body fetch.
        if (article.closed) {
          diagnostic.phase = idle ? "tail-idle" : "tail-error";
          return finish(HttpDownloader::OK, true);
        }
        diagnostic.phase = idle ? "body-idle" : "body-error";
        LOG_ERR("RSS", "Figaro AUTH: %s before </article> (%zu bytes, read=%d)",
                idle ? "idle timeout" : "read error", bytesReceived, read);
        return fail(HttpDownloader::HTTP_ERROR);
      }
      delay(1);
    }
  }

  diagnostic.phase = "redirect-limit";
  LOG_ERR("RSS", "Figaro AUTH: redirect limit reached");
  return fail(HttpDownloader::HTTP_ERROR);
}

}  // namespace RssFigaroAuth
