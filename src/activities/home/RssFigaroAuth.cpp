#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
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
  const HttpDownloader::DataCallback* onData = nullptr;
  const HttpDownloader::CancelCallback* shouldCancel = nullptr;
  RssFetchDiagnostics::Record* diagnostic = nullptr;
  bool cancelled = false;
  bool seenArticle = false;
  bool articleClosed = false;
  bool earlyArticleEnd = false;
  bool receiverRejected = false;
  bool encodedResponse = false;
  bool encodedRejected = false;
  size_t bytesReceived = 0;
  size_t bytesStored = 0;
  uint32_t firstDataMs = 0;
  uint32_t articleClosedMs = 0;
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
  const size_t pathStart = url.find_first_of("/?#", hostStart);
  const std::string hostPort = url.substr(hostStart, pathStart == std::string::npos ? std::string::npos : pathStart - hostStart);
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
  return !out.host.empty() && out.host.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-") == std::string::npos;
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
  if (bytes == 0 || bytes > MAX_AUTH_BYTES) { file.close(); return false; }
  out.resize(bytes);
  const int read = file.read(out.data(), bytes);
  file.close();
  if (read != static_cast<int>(bytes)) { out.clear(); return false; }
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
    if (c < 0x20 || c == 0x7f) { out.clear(); return false; }
  }
  return true;
}

bool ensureCookie() {
  if (session.cookieLoaded) return !session.cookie.empty();
  session.cookieLoaded = true;
  return readCookie(session.cookie);
}

uint64_t fnv1a64(const std::string& text, uint64_t hash = 14695981039346656037ULL) {
  for (const unsigned char c : text) { hash ^= c; hash *= 1099511628211ULL; }
  return hash;
}

bool cancelRequested() {
  if (!session.shouldCancel || !*session.shouldCancel) return false;
  if ((*session.shouldCancel)()) { session.cancelled = true; return true; }
  return false;
}

bool isRedirect(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

char combinedByteAt(const uint8_t* data, const size_t index) {
  if (index < session.tailLength) return session.tail[index];
  return static_cast<char>(data[index - session.tailLength]);
}

size_t findMarker(const uint8_t* data, const size_t length, const char* marker) {
  if (!data || length == 0 || !marker || !marker[0]) return std::string::npos;
  const size_t markerLength = std::strlen(marker);
  const size_t combinedLength = session.tailLength + length;
  if (markerLength > combinedLength) return std::string::npos;
  for (size_t i = 0; i + markerLength <= combinedLength; ++i) {
    size_t j = 0;
    while (j < markerLength && std::tolower(static_cast<unsigned char>(combinedByteAt(data, i + j))) == std::tolower(static_cast<unsigned char>(marker[j]))) ++j;
    if (j == markerLength) {
      if (i + markerLength <= session.tailLength) return 0;
      return i + markerLength - session.tailLength;
    }
  }
  return std::string::npos;
}

void rememberTail(const uint8_t* data, const size_t length) {
  const size_t keep = sizeof(session.tail);
  if (length >= keep) {
    session.tailLength = keep;
    std::memcpy(session.tail, data + length - keep, keep);
    return;
  }
  const size_t oldKeep = std::min(session.tailLength, keep - length);
  if (oldKeep > 0) std::memmove(session.tail, session.tail + session.tailLength - oldKeep, oldKeep);
  std::memcpy(session.tail + oldKeep, data, length);
  session.tailLength = oldKeep + length;
}

void resetRequestState(const HttpDownloader::DataCallback& onData, const HttpDownloader::CancelCallback& shouldCancel, RssFetchDiagnostics::Record& diagnostic) {
  session.redirectLocation.clear();
  session.onData = &onData;
  session.shouldCancel = &shouldCancel;
  session.diagnostic = &diagnostic;
  session.cancelled = false;
  session.seenArticle = false;
  session.articleClosed = false;
  session.earlyArticleEnd = false;
  session.receiverRejected = false;
  session.encodedResponse = false;
  session.encodedRejected = false;
  session.bytesReceived = 0;
  session.bytesStored = 0;
  session.firstDataMs = 0;
  session.articleClosedMs = 0;
  session.tailLength = 0;
}

void clearRequestState() {
  session.onData = nullptr;
  session.shouldCancel = nullptr;
  session.diagnostic = nullptr;
}

esp_err_t onHttpEvent(esp_http_client_event_t* event) {
  if (!event) return ESP_OK;
  if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value) {
    if (session.diagnostic && session.diagnostic->headersMs == 0) session.diagnostic->headersMs = static_cast<uint32_t>(millis() - session.diagnostic->startedMs);
    if (strcasecmp(event->header_key, "Location") == 0) session.redirectLocation.assign(event->header_value);
    if (strcasecmp(event->header_key, "Content-Encoding") == 0 && strcasecmp(event->header_value, "identity") != 0) session.encodedResponse = true;
    return ESP_OK;
  }
  if (event->event_id != HTTP_EVENT_ON_DATA || !event->data || event->data_len <= 0) return ESP_OK;
  if (cancelRequested()) return ESP_FAIL;
  const auto* data = static_cast<const uint8_t*>(event->data);
  const size_t length = static_cast<size_t>(event->data_len);
  const uint32_t now = millis();
  if (session.firstDataMs == 0) session.firstDataMs = now;
  session.bytesReceived += length;
  if (session.diagnostic) {
    session.diagnostic->received += length;
    session.diagnostic->bodyMs = static_cast<uint32_t>(now - session.firstDataMs);
  }
  const int status = esp_http_client_get_status_code(event->client);
  if (status != 0 && status != 200) return ESP_OK;
  if (session.encodedResponse) { session.encodedRejected = true; return ESP_FAIL; }
  if (!session.onData || !*session.onData) { session.receiverRejected = true; return ESP_FAIL; }
  if (session.articleClosed) { session.earlyArticleEnd = true; return ESP_FAIL; }
  if (!session.seenArticle && findMarker(data, length, ARTICLE_START) != std::string::npos) session.seenArticle = true;
  const size_t articleEnd = session.seenArticle ? findMarker(data, length, ARTICLE_END) : std::string::npos;
  const size_t forwardLength = articleEnd == std::string::npos ? length : std::min(articleEnd, length);
  if (forwardLength > 0 && !(*session.onData)(data, forwardLength)) { session.receiverRejected = true; return ESP_FAIL; }
  session.bytesStored += forwardLength;
  if (session.diagnostic) session.diagnostic->stored += forwardLength;
  if (articleEnd != std::string::npos) {
    session.articleClosed = true;
    session.articleClosedMs = now;
    if (session.diagnostic) {
      session.diagnostic->articleClosed = true;
      session.diagnostic->articleMs = static_cast<uint32_t>(now - session.diagnostic->startedMs);
    }
    const int64_t contentLength = esp_http_client_get_content_length(event->client);
    if (contentLength > 0 && static_cast<uint64_t>(contentLength) <= session.bytesReceived) return ESP_OK;
    session.earlyArticleEnd = true;
    return ESP_FAIL;
  }
  rememberTail(data, length);
  return ESP_OK;
}

void dropClient() {
  if (session.client) { esp_http_client_cleanup(session.client); session.client = nullptr; }
}

bool ensureClient(const std::string& url) {
  if (session.client) return esp_http_client_set_url(session.client, url.c_str()) == ESP_OK;
  esp_http_client_config_t config = {};
  config.url = url.c_str();
  config.buffer_size = RX_BUFFER_SIZE;
  config.buffer_size_tx = std::max(TX_BUFFER_SIZE, session.cookie.size() + sizeof("Cookie: \r\n"));
  config.timeout_ms = HTTP_TIMEOUT_MS;
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
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  const uint64_t hash = fnv1a64(session.cookie, fnv1a64("Figaro AUTH perform v3"));
  return hash != 0 ? hash : 1;
}

void resetSession() {
  clearRequestState();
  dropClient();
  std::string().swap(session.cookie);
  session.cookieLoaded = false;
  std::string().swap(session.redirectLocation);
  session.cancelled = false;
  session.seenArticle = false;
  session.articleClosed = false;
  session.earlyArticleEnd = false;
  session.receiverRejected = false;
  session.encodedResponse = false;
  session.encodedRejected = false;
  session.bytesReceived = 0;
  session.bytesStored = 0;
  session.firstDataMs = 0;
  session.articleClosedMs = 0;
  session.tailLength = 0;
}

HttpDownloader::DownloadError streamUrl(const std::string& url, const HttpDownloader::DataCallback& onData, const HttpDownloader::CancelCallback& shouldCancel) {
  RssFetchDiagnostics::Record diagnostic;
  diagnostic.startedMs = millis();
  diagnostic.transport = "figaro-auth-perform";
  diagnostic.phase = "configuration";
  const auto finish = [&](const HttpDownloader::DownloadError result, const bool discard) {
    diagnostic.result = static_cast<int>(result);
    diagnostic.httpStatus = session.client ? esp_http_client_get_status_code(session.client) : diagnostic.httpStatus;
    diagnostic.expected = session.client ? esp_http_client_get_content_length(session.client) : diagnostic.expected;
    diagnostic.encoded = session.encodedResponse;
    diagnostic.articleClosed = session.articleClosed;
    if (session.firstDataMs != 0) diagnostic.bodyMs = static_cast<uint32_t>(millis() - session.firstDataMs);
    if (session.client && result != HttpDownloader::OK) {
      diagnostic.socketError = esp_http_client_get_errno(session.client);
      esp_http_client_get_and_clear_last_tls_error(session.client, &diagnostic.tlsError, &diagnostic.tlsFlags);
    }
    clearRequestState();
    RssFetchDiagnostics::write(url.c_str(), diagnostic);
    if (discard) dropClient();
    return result;
  };
  const auto fail = [&](const HttpDownloader::DownloadError error) { return finish(error, true); };
  if (shouldCancel && shouldCancel()) return fail(HttpDownloader::ABORTED);
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) {
    LOG_ERR("RSS", "Figaro AUTH: invalid URL, cookie or callback");
    return fail(HttpDownloader::HTTP_ERROR);
  }
  std::string currentUrl = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    if (shouldCancel && shouldCancel()) return fail(HttpDownloader::ABORTED);
    diagnostic.phase = "client-init";
    if (!isAllowedUrl(currentUrl) || !ensureClient(currentUrl)) return fail(HttpDownloader::HTTP_ERROR);
    resetRequestState(onData, shouldCancel, diagnostic);
    diagnostic.phase = "request-setup";
    esp_err_t error = esp_http_client_set_timeout_ms(session.client, HTTP_TIMEOUT_MS);
    if (error == ESP_OK) error = esp_http_client_set_header(session.client, "Cookie", session.cookie.c_str());
    if (error != ESP_OK) { diagnostic.detail = error; return fail(HttpDownloader::HTTP_ERROR); }
    diagnostic.phase = "perform";
    const uint32_t performStart = millis();
    const esp_err_t performResult = esp_http_client_perform(session.client);
    diagnostic.detail = performResult;
    diagnostic.bodyMs = session.firstDataMs != 0 ? static_cast<uint32_t>(millis() - session.firstDataMs) : static_cast<uint32_t>(millis() - performStart);
    const int status = esp_http_client_get_status_code(session.client);
    diagnostic.httpStatus = status;
    diagnostic.expected = esp_http_client_get_content_length(session.client);
    diagnostic.encoded = session.encodedResponse;
    if (session.cancelled) { diagnostic.phase = "cancelled"; return finish(HttpDownloader::ABORTED, true); }
    if (session.receiverRejected) { diagnostic.phase = "receiver"; return fail(HttpDownloader::HTTP_ERROR); }
    if (session.encodedRejected || session.encodedResponse) { diagnostic.phase = "encoded-response"; return fail(HttpDownloader::HTTP_ERROR); }
    if (isRedirect(status)) {
      diagnostic.phase = "redirect";
      const std::string nextUrl = buildRedirectUrl(currentUrl, session.redirectLocation);
      clearRequestState();
      dropClient();
      if (session.redirectLocation.empty() || !isAllowedUrl(nextUrl)) return fail(HttpDownloader::HTTP_ERROR);
      currentUrl = nextUrl;
      continue;
    }
    if (status != 200) { diagnostic.phase = "http-status"; return fail(HttpDownloader::HTTP_ERROR); }
    if (session.articleClosed) {
      diagnostic.phase = performResult == ESP_OK ? "response-end" : "article-end";
      const bool discard = performResult != ESP_OK || session.earlyArticleEnd || !esp_http_client_is_persistent_connection(session.client);
      return finish(HttpDownloader::OK, discard);
    }
    if (performResult != ESP_OK) {
      diagnostic.phase = "perform-error";
      LOG_ERR("RSS", "Figaro AUTH: perform failed before </article> (%d, %zu bytes)", static_cast<int>(performResult), session.bytesReceived);
      return fail(HttpDownloader::HTTP_ERROR);
    }
    diagnostic.phase = "missing-article-end";
    LOG_ERR("RSS", "Figaro AUTH: response ended before </article> (%zu bytes)", session.bytesReceived);
    return fail(HttpDownloader::HTTP_ERROR);
  }
  diagnostic.phase = "redirect-limit";
  return fail(HttpDownloader::HTTP_ERROR);
}

}  // namespace RssFigaroAuth
