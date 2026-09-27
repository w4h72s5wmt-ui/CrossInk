#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalClock.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
#include <strings.h>
#include <sys/time.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <string>

namespace RssFigaroAuth {
namespace {
constexpr char AUTH_PATH[] = "/RSS/figaro_auth.txt";
constexpr size_t MAX_AUTH_BYTES = 4096;
constexpr size_t IO_BUFFER_SIZE = 2048;
constexpr uint32_t HTTP_TIMEOUT_MS = 30000;
constexpr uint8_t MAX_REDIRECTS = 5;
constexpr uint16_t MIN_TLS_CLOCK_YEAR = 2024;

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

struct ResponseHeaders {
  std::string location;
  bool encoded = false;
};

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

bool isLeapYear(const uint16_t year) {
  return (year % 4U == 0U && year % 100U != 0U) || year % 400U == 0U;
}

uint8_t daysInMonth(const uint16_t year, const uint8_t month) {
  static constexpr uint8_t DAYS[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (month < 1 || month > 12) return 0;
  return month == 2 && isLeapYear(year) ? 29 : DAYS[month - 1];
}

int64_t daysFromCivil(int year, const unsigned month, const unsigned day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(year - era * 400);
  const int shiftedMonth = static_cast<int>(month) + (month > 2 ? -3 : 9);
  const unsigned doy = (153U * static_cast<unsigned>(shiftedMonth) + 2U) / 5U + day - 1U;
  const unsigned doe = yoe * 365U + yoe / 4U - yoe / 100U + doy;
  return static_cast<int64_t>(era) * 146097 + static_cast<int64_t>(doe) - 719468;
}

bool syncSystemClockFromRtc(int64_t& detail) {
  uint16_t year = 0;
  uint8_t month = 0;
  uint8_t day = 0;
  uint8_t hour = 0;
  uint8_t minute = 0;
  if (!halClock.getDateTime(year, month, day, hour, minute)) {
    detail = -1006;
    return false;
  }

  const uint8_t monthDays = daysInMonth(year, month);
  if (year < MIN_TLS_CLOCK_YEAR || year > 2099 || monthDays == 0 || day < 1 || day > monthDays || hour > 23 ||
      minute > 59) {
    detail = -1007;
    return false;
  }

  const int64_t epoch = daysFromCivil(static_cast<int>(year), month, day) * 86400LL +
                        static_cast<int64_t>(hour) * 3600LL + static_cast<int64_t>(minute) * 60LL;
  if (epoch <= 0) {
    detail = -1007;
    return false;
  }

  timeval tv{};
  tv.tv_sec = static_cast<time_t>(epoch);
  tv.tv_usec = 0;
  if (settimeofday(&tv, nullptr) != 0) {
    detail = -1008;
    return false;
  }
  detail = 0;
  return true;
}

esp_err_t captureResponseHeaders(esp_http_client_event_t* event) {
  if (!event || event->event_id != HTTP_EVENT_ON_HEADER || !event->user_data || !event->header_key ||
      !event->header_value) {
    return ESP_OK;
  }

  auto* headers = static_cast<ResponseHeaders*>(event->user_data);
  if (strcasecmp(event->header_key, "Location") == 0) {
    headers->location.assign(event->header_value);
  } else if (strcasecmp(event->header_key, "Content-Encoding") == 0 &&
             strcasecmp(event->header_value, "identity") != 0 && event->header_value[0] != '\0') {
    headers->encoded = true;
  }
  return ESP_OK;
}

void captureTlsDiagnostic(esp_http_client_handle_t client, RssFetchDiagnostics::Record& d) {
  int tlsError = 0;
  int tlsFlags = 0;
  const esp_err_t err = esp_http_client_get_and_clear_last_tls_error(client, &tlsError, &tlsFlags);
  if (err != ESP_OK || tlsError != 0 || tlsFlags != 0) {
    d.tlsError = tlsError;
    d.tlsFlags = tlsFlags;
  }
}

}  // namespace

bool isConfiguredFor(const std::string& url) {
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  // Keep the existing cache namespace stable: changing TLS transport must not
  // invalidate already-cached Figaro bodies.
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
  d.transport = "figaro-auth-esp-http-v160";
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

  if (!syncSystemClockFromRtc(d.detail)) {
    d.phase = "clock";
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

    ResponseHeaders responseHeaders;
    esp_http_client_config_t config = {};
    config.url = current.c_str();
    config.buffer_size = static_cast<int>(IO_BUFFER_SIZE);
    config.buffer_size_tx = 1024;
    config.timeout_ms = static_cast<int>(HTTP_TIMEOUT_MS);
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.keep_alive_enable = false;
    config.event_handler = captureResponseHeaders;
    config.user_data = &responseHeaders;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
      d.phase = "client-init";
      d.detail = -1021;
      return finish(HttpDownloader::HTTP_ERROR);
    }

    esp_http_client_set_header(client, "User-Agent", "Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)");
    esp_http_client_set_header(client, "Accept", "text/html,application/xhtml+xml");
    esp_http_client_set_header(client, "Accept-Encoding", "identity");
    esp_http_client_set_header(client, "Connection", "close");
    esp_http_client_set_header(client, "Cookie", session.cookie.c_str());

    d.phase = "tls";
    const uint32_t openStart = millis();
    const esp_err_t openResult = esp_http_client_open(client, 0);
    d.openMs += millis() - openStart;
    if (openResult != ESP_OK) {
      d.detail = openResult;
      captureTlsDiagnostic(client, d);
      session.noResponseThisRefresh = true;
      esp_http_client_cleanup(client);
      return finish(HttpDownloader::HTTP_ERROR);
    }

    d.phase = "headers";
    const uint32_t headerStart = millis();
    const int64_t responseLength = esp_http_client_fetch_headers(client);
    d.headersMs += millis() - headerStart;
    d.httpStatus = esp_http_client_get_status_code(client);
    d.expected = responseLength >= 0 ? responseLength : -1;

    if (d.httpStatus <= 0) {
      d.detail = responseLength;
      captureTlsDiagnostic(client, d);
      session.noResponseThisRefresh = true;
      esp_http_client_cleanup(client);
      return finish(HttpDownloader::HTTP_ERROR);
    }

    if (isRedirectStatus(d.httpStatus)) {
      const std::string next = redirectUrl(current, responseHeaders.location);
      esp_http_client_cleanup(client);
      if (responseHeaders.location.empty() || !isAllowedUrl(next)) {
        d.phase = "redirect";
        return finish(HttpDownloader::HTTP_ERROR);
      }
      current = next;
      continue;
    }

    if (d.httpStatus != 200 || responseHeaders.encoded) {
      d.phase = responseHeaders.encoded ? "encoded-response" : "http-status";
      esp_http_client_cleanup(client);
      return finish(HttpDownloader::HTTP_ERROR);
    }

    auto buffer = makePsramByteBufferNoThrow(IO_BUFFER_SIZE);
    if (!buffer) buffer = makeHeapByteBufferNoThrow(IO_BUFFER_SIZE);
    if (!buffer) {
      d.phase = "buffer-allocation";
      esp_http_client_cleanup(client);
      return finish(HttpDownloader::HTTP_ERROR);
    }

    d.phase = "body";
    const uint32_t bodyStart = millis();
    while (true) {
      if (shouldCancel && shouldCancel()) {
        d.bodyMs = millis() - bodyStart;
        esp_http_client_cleanup(client);
        return finish(HttpDownloader::ABORTED);
      }

      const int bytesRead =
          esp_http_client_read(client, reinterpret_cast<char*>(buffer.get()), static_cast<int>(IO_BUFFER_SIZE));
      if (bytesRead < 0) {
        d.detail = bytesRead;
        captureTlsDiagnostic(client, d);
        d.bodyMs = millis() - bodyStart;
        esp_http_client_cleanup(client);
        return finish(HttpDownloader::HTTP_ERROR);
      }
      if (bytesRead == 0) break;

      d.received += static_cast<size_t>(bytesRead);
      if (!onData(buffer.get(), static_cast<size_t>(bytesRead))) {
        d.detail = -1012;
        d.bodyMs = millis() - bodyStart;
        esp_http_client_cleanup(client);
        return finish(HttpDownloader::HTTP_ERROR);
      }
      d.stored += static_cast<size_t>(bytesRead);
      delay(0);
    }

    d.bodyMs = millis() - bodyStart;
    const bool complete = esp_http_client_is_complete_data_received(client);
    esp_http_client_cleanup(client);

    if (!complete && d.expected >= 0) {
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
