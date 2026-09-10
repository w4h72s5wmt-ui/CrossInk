#include "RssFigaroAuth.h"
#include "RssFetchDiagnostics.h"

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>
#include <WiFiClient.h>
#include <strings.h>
#include <wolfssl/ssl.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>

namespace RssFigaroAuth {
namespace {
constexpr char AUTH_PATH[] = "/RSS/figaro_auth.txt";
constexpr size_t MAX_AUTH_BYTES = 4096;
constexpr size_t IO_BUFFER_SIZE = 2048;
constexpr size_t MAX_HEADER_LINE = 8192;
constexpr uint32_t TCP_TIMEOUT_MS = 15000;
constexpr uint32_t TLS_TIMEOUT_MS = 20000;
constexpr uint32_t HTTP_TIMEOUT_MS = 30000;
constexpr uint8_t MAX_REDIRECTS = 5;

// Public DigiCert Global Root G3. Figaro's current certificate chain is issued
// through DigiCert Global G3 TLS ECC SHA384 2020 CA1. The leaf hostname is also
// checked explicitly by wolfSSL before any authenticated HTTP bytes are sent.
constexpr char DIGICERT_GLOBAL_ROOT_G3[] = R"PEM(-----BEGIN CERTIFICATE-----
MIICPzCCAcWgAwIBAgIQBVVWvPJepDU1w6QP1atFcjAKBggqhkjOPQQDAzBhMQsw
CQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3d3cu
ZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBHMzAe
Fw0xMzA4MDExMjAwMDBaFw0zODAxMTUxMjAwMDBaMGExCzAJBgNVBAYTAlVTMRUw
EwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5jb20x
IDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IEczMHYwEAYHKoZIzj0CAQYF
K4EEACIDYgAE3afZu4q4C/sLfyHS8L6+c/MzXRq8NOrexpu80JX28MzQC7phW1FG
fp4tn+6OYwwX7Adw9c+ELkCDnOg/QW07rdOkFFk2eJ0DQ+4QE2xy3q6Ip6FrtUPO
Z9wj/wMco+I+o0IwQDAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAd
BgNVHQ4EFgQUs9tIpPmhxdiuNkHMEWNpYim8S8YwCgYIKoZIzj0EAwMDaAAwZQIx
AK288mw/EkrRLTnDCgmXc/SINoyIJ7vmiI1Qhadj+Z4y3maTD/HMsQmP3Wyr+mt/
oAIwOWZbwmSNuJ5Q3KjVSaLtx9zRSX8XAbjIho9OjIgrqJqpisXRAL34VOKa5Vt8
sycX
-----END CERTIFICATE-----)PEM";

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
  const std::string authority = url.substr(hostStart, pathStart == std::string::npos ? std::string::npos : pathStart - hostStart);
  if (authority.empty() || authority.find(':') != std::string::npos ||
      authority.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-") != std::string::npos) return false;
  out.host = authority;
  out.path = pathStart == std::string::npos ? "/" : url.substr(pathStart);
  if (out.path.empty() || out.path.front() != '/') out.path.insert(out.path.begin(), '/');
  return true;
}

bool isFigaroHost(const std::string& host) {
  static constexpr char ROOT[] = "lefigaro.fr";
  if (strcasecmp(host.c_str(), ROOT) == 0) return true;
  const size_t hl = host.size(), rl = sizeof(ROOT) - 1;
  return hl > rl && host[hl - rl - 1] == '.' && strcasecmp(host.c_str() + hl - rl, ROOT) == 0;
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
  if (bytes == 0 || bytes > MAX_AUTH_BYTES) { file.close(); return false; }
  out.resize(bytes);
  const int read = file.read(out.data(), bytes);
  file.close();
  if (read <= 0) { out.clear(); return false; }
  out.resize(static_cast<size_t>(read));
  while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back()))) out.pop_back();
  size_t start = 0;
  while (start < out.size() && std::isspace(static_cast<unsigned char>(out[start]))) ++start;
  if (start) out.erase(0, start);
  static constexpr char COOKIE_PREFIX[] = "Cookie:";
  if (out.size() >= sizeof(COOKIE_PREFIX) - 1 && strncasecmp(out.c_str(), COOKIE_PREFIX, sizeof(COOKIE_PREFIX) - 1) == 0) {
    out.erase(0, sizeof(COOKIE_PREFIX) - 1);
    while (!out.empty() && std::isspace(static_cast<unsigned char>(out.front()))) out.erase(out.begin());
  }
  if (out.empty()) return false;
  for (const unsigned char c : out) if (c < 0x20 || c == 0x7f) { out.clear(); return false; }
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

bool isRedirectStatus(const int status) {
  return status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
}

int wolfRecv(WOLFSSL*, char* buf, int size, void* ctx) {
  auto* tcp = static_cast<WiFiClient*>(ctx);
  if (!tcp->connected() && tcp->available() == 0) return WOLFSSL_CBIO_ERR_CONN_CLOSE;
  if (tcp->available() == 0) return WOLFSSL_CBIO_ERR_WANT_READ;
  const int n = tcp->read(reinterpret_cast<uint8_t*>(buf), static_cast<size_t>(size));
  return n > 0 ? n : WOLFSSL_CBIO_ERR_WANT_READ;
}
int wolfSend(WOLFSSL*, char* buf, int size, void* ctx) {
  auto* tcp = static_cast<WiFiClient*>(ctx);
  const int n = tcp->write(reinterpret_cast<const uint8_t*>(buf), static_cast<size_t>(size));
  if (n > 0) return n;
  return tcp->connected() ? WOLFSSL_CBIO_ERR_WANT_WRITE : WOLFSSL_CBIO_ERR_CONN_CLOSE;
}
bool wantIo(const int error) { return error == WOLFSSL_ERROR_WANT_READ || error == WOLFSSL_ERROR_WANT_WRITE; }

class VerifiedTls {
 public:
  ~VerifiedTls() { close(); }

  bool connect(const char* host, int& detail) {
    close();
    tcp.setConnectionTimeout(TCP_TIMEOUT_MS);
    tcp.setTimeout(HTTP_TIMEOUT_MS);
    if (!tcp.connect(host, 443)) { detail = -1001; return false; }
    ctx = wolfSSL_CTX_new(wolfSSLv23_client_method());
    if (!ctx) { detail = -1002; return false; }
    wolfSSL_CTX_set_verify(ctx, WOLFSSL_VERIFY_PEER, nullptr);
    if (wolfSSL_CTX_load_verify_buffer(ctx, reinterpret_cast<const unsigned char*>(DIGICERT_GLOBAL_ROOT_G3),
                                      std::strlen(DIGICERT_GLOBAL_ROOT_G3), WOLFSSL_FILETYPE_PEM) != WOLFSSL_SUCCESS) {
      detail = -1003; return false;
    }
    wolfSSL_SetIORecv(ctx, wolfRecv);
    wolfSSL_SetIOSend(ctx, wolfSend);
    ssl = wolfSSL_new(ctx);
    if (!ssl) { detail = -1004; return false; }
    wolfSSL_SetIOReadCtx(ssl, &tcp);
    wolfSSL_SetIOWriteCtx(ssl, &tcp);
    if (wolfSSL_UseSNI(ssl, WOLFSSL_SNI_HOST_NAME, host, std::strlen(host)) != WOLFSSL_SUCCESS ||
        wolfSSL_check_domain_name(ssl, host) != WOLFSSL_SUCCESS) {
      detail = -1005; return false;
    }
#if defined(WOLFSSL_TLS13) && defined(HAVE_CURVE25519)
    wolfSSL_UseKeyShare(ssl, WOLFSSL_ECC_X25519);
#endif
#ifdef HAVE_MAX_FRAGMENT
    wolfSSL_UseMaxFragment(ssl, WOLFSSL_MFL_2_11);
#endif
    const uint32_t deadline = millis() + TLS_TIMEOUT_MS;
    while (true) {
      const int result = wolfSSL_connect(ssl);
      if (result == WOLFSSL_SUCCESS) { detail = 0; return true; }
      detail = wolfSSL_get_error(ssl, result);
      if (!wantIo(detail) || static_cast<int32_t>(millis() - deadline) >= 0) return false;
      delay(5);
    }
  }

  bool writeAll(const char* data, size_t length, int& detail) {
    size_t offset = 0;
    const uint32_t deadline = millis() + HTTP_TIMEOUT_MS;
    while (offset < length) {
      const int n = wolfSSL_write(ssl, data + offset, static_cast<int>(length - offset));
      if (n > 0) { offset += static_cast<size_t>(n); continue; }
      detail = wolfSSL_get_error(ssl, n);
      if (!wantIo(detail) || static_cast<int32_t>(millis() - deadline) >= 0) return false;
      delay(2);
    }
    return true;
  }

  int readSome(uint8_t* out, size_t capacity, uint32_t deadline, int& detail) {
    while (true) {
      const int n = wolfSSL_read(ssl, out, static_cast<int>(capacity));
      if (n > 0) return n;
      detail = wolfSSL_get_error(ssl, n);
      if (detail == WOLFSSL_ERROR_ZERO_RETURN || (!tcp.connected() && tcp.available() == 0)) return 0;
      if (!wantIo(detail) || static_cast<int32_t>(millis() - deadline) >= 0) return -1;
      delay(2);
    }
  }

  void close() {
    if (ssl) { wolfSSL_free(ssl); ssl = nullptr; }
    if (ctx) { wolfSSL_CTX_free(ctx); ctx = nullptr; }
    tcp.stop();
  }

 private:
  WiFiClient tcp;
  WOLFSSL_CTX* ctx = nullptr;
  WOLFSSL* ssl = nullptr;
};

bool readLine(VerifiedTls& tls, std::string& line, int& detail) {
  line.clear();
  const uint32_t deadline = millis() + HTTP_TIMEOUT_MS;
  uint8_t byte = 0;
  while (line.size() < MAX_HEADER_LINE) {
    const int n = tls.readSome(&byte, 1, deadline, detail);
    if (n <= 0) return false;
    if (byte == '\n') {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      return true;
    }
    line.push_back(static_cast<char>(byte));
  }
  detail = -1010;
  return false;
}

bool deliverFixed(VerifiedTls& tls, size_t remaining, const HttpDownloader::DataCallback& onData,
                  const HttpDownloader::CancelCallback& cancel, RssFetchDiagnostics::Record& d, int& detail) {
  auto buffer = makePsramByteBufferNoThrow(IO_BUFFER_SIZE);
  if (!buffer) return false;
  while (remaining > 0) {
    if (cancel && cancel()) { detail = -1011; return false; }
    const size_t wanted = std::min(remaining, IO_BUFFER_SIZE);
    const int n = tls.readSome(buffer.get(), wanted, millis() + HTTP_TIMEOUT_MS, detail);
    if (n <= 0) return false;
    d.received += static_cast<size_t>(n);
    if (!onData(buffer.get(), static_cast<size_t>(n))) { detail = -1012; return false; }
    d.stored += static_cast<size_t>(n);
    remaining -= static_cast<size_t>(n);
  }
  return true;
}

bool deliverUntilClose(VerifiedTls& tls, const HttpDownloader::DataCallback& onData,
                       const HttpDownloader::CancelCallback& cancel, RssFetchDiagnostics::Record& d, int& detail) {
  auto buffer = makePsramByteBufferNoThrow(IO_BUFFER_SIZE);
  if (!buffer) return false;
  while (true) {
    if (cancel && cancel()) { detail = -1011; return false; }
    const int n = tls.readSome(buffer.get(), IO_BUFFER_SIZE, millis() + HTTP_TIMEOUT_MS, detail);
    if (n == 0) return true;
    if (n < 0) return false;
    d.received += static_cast<size_t>(n);
    if (!onData(buffer.get(), static_cast<size_t>(n))) { detail = -1012; return false; }
    d.stored += static_cast<size_t>(n);
  }
}

bool deliverChunked(VerifiedTls& tls, const HttpDownloader::DataCallback& onData,
                    const HttpDownloader::CancelCallback& cancel, RssFetchDiagnostics::Record& d, int& detail) {
  std::string line;
  while (true) {
    if (!readLine(tls, line, detail)) return false;
    const size_t semicolon = line.find(';');
    const std::string hex = line.substr(0, semicolon);
    char* end = nullptr;
    const unsigned long size = std::strtoul(hex.c_str(), &end, 16);
    if (!end || end == hex.c_str()) { detail = -1013; return false; }
    if (size == 0) {
      while (readLine(tls, line, detail) && !line.empty()) {}
      return line.empty();
    }
    if (!deliverFixed(tls, static_cast<size_t>(size), onData, cancel, d, detail)) return false;
    if (!readLine(tls, line, detail) || !line.empty()) { detail = -1014; return false; }
  }
}
}  // namespace

bool isConfiguredFor(const std::string& url) {
  return isAllowedUrl(url) && (ensureCookie() || Storage.exists(AUTH_PATH));
}

uint64_t cacheKeyFor(const std::string& url) {
  if (!isConfiguredFor(url)) return 0;
  const uint64_t hash = fnv1a64(session.cookie, fnv1a64("Figaro AUTH wolfSSL verified v5"));
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
  d.transport = "figaro-auth-wolfssl";
  d.phase = "configuration";
  const auto finish = [&](HttpDownloader::DownloadError result) {
    d.result = static_cast<int>(result);
    RssFetchDiagnostics::write(url.c_str(), d);
    return result;
  };
  if (shouldCancel && shouldCancel()) return finish(HttpDownloader::ABORTED);
  if (!onData || !isAllowedUrl(url) || !ensureCookie()) return finish(HttpDownloader::HTTP_ERROR);
  if (session.noResponseThisRefresh) { d.phase = "circuit-open"; return finish(HttpDownloader::HTTP_ERROR); }

  std::string current = url;
  for (uint8_t hop = 0; hop < MAX_REDIRECTS; ++hop) {
    ParsedUrl parsed;
    if (!parseUrl(current, parsed) || !isFigaroHost(parsed.host)) return finish(HttpDownloader::HTTP_ERROR);
    VerifiedTls tls;
    d.phase = "tls";
    const uint32_t openStart = millis();
    int detail = 0;
    if (!tls.connect(parsed.host.c_str(), detail)) {
      d.openMs += millis() - openStart;
      d.detail = detail;
      return finish(HttpDownloader::HTTP_ERROR);
    }
    d.openMs += millis() - openStart;

    std::string request;
    request.reserve(parsed.path.size() + session.cookie.size() + 256);
    request += "GET "; request += parsed.path; request += " HTTP/1.1\r\nHost: "; request += parsed.host;
    request += "\r\nUser-Agent: Mozilla/5.0 (XTEINK X4 Pro; CrossInk RSS)\r\n";
    request += "Accept: text/html,application/xhtml+xml\r\nAccept-Encoding: identity\r\nConnection: close\r\nCookie: ";
    request += session.cookie;
    request += "\r\n\r\n";
    d.phase = "request";
    if (!tls.writeAll(request.data(), request.size(), detail)) { d.detail = detail; return finish(HttpDownloader::HTTP_ERROR); }

    d.phase = "headers";
    const uint32_t headerStart = millis();
    std::string line;
    if (!readLine(tls, line, detail)) {
      d.headersMs += millis() - headerStart;
      d.detail = detail;
      session.noResponseThisRefresh = true;
      return finish(HttpDownloader::HTTP_ERROR);
    }
    d.headersMs += millis() - headerStart;
    if (line.rfind("HTTP/", 0) != 0) { d.detail = -1020; return finish(HttpDownloader::HTTP_ERROR); }
    const size_t space = line.find(' ');
    d.httpStatus = space == std::string::npos ? 0 : std::atoi(line.c_str() + space + 1);

    bool haveLength = false;
    size_t contentLength = 0;
    bool chunked = false;
    bool identityEncoding = true;
    std::string location;
    while (readLine(tls, line, detail)) {
      if (line.empty()) break;
      const size_t colon = line.find(':');
      if (colon == std::string::npos) continue;
      std::string name = line.substr(0, colon), value = line.substr(colon + 1);
      while (!value.empty() && std::isspace(static_cast<unsigned char>(value.front()))) value.erase(value.begin());
      std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
      std::string lower = value;
      std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
      if (name == "content-length") { contentLength = static_cast<size_t>(std::strtoull(value.c_str(), nullptr, 10)); haveLength = true; }
      else if (name == "transfer-encoding" && lower.find("chunked") != std::string::npos) chunked = true;
      else if (name == "content-encoding" && !lower.empty() && lower != "identity") identityEncoding = false;
      else if (name == "location") location = value;
    }
    if (!line.empty()) { d.detail = detail; return finish(HttpDownloader::HTTP_ERROR); }
    d.expected = haveLength ? static_cast<int64_t>(contentLength) : -1;

    if (isRedirectStatus(d.httpStatus)) {
      const std::string next = redirectUrl(current, location);
      if (location.empty() || !isAllowedUrl(next)) { d.phase = "redirect"; return finish(HttpDownloader::HTTP_ERROR); }
      current = next;
      continue;
    }
    if (d.httpStatus != 200 || !identityEncoding) {
      d.phase = identityEncoding ? "http-status" : "encoded-response";
      return finish(HttpDownloader::HTTP_ERROR);
    }

    d.phase = "body";
    const uint32_t bodyStart = millis();
    const bool ok = chunked ? deliverChunked(tls, onData, shouldCancel, d, detail)
                            : haveLength ? deliverFixed(tls, contentLength, onData, shouldCancel, d, detail)
                                         : deliverUntilClose(tls, onData, shouldCancel, d, detail);
    d.bodyMs = millis() - bodyStart;
    d.detail = detail;
    if (!ok) return finish((shouldCancel && shouldCancel()) ? HttpDownloader::ABORTED : HttpDownloader::HTTP_ERROR);
    d.phase = "body-ready";
    return finish(HttpDownloader::OK);
  }
  d.phase = "redirect-limit";
  return finish(HttpDownloader::HTTP_ERROR);
}

}  // namespace RssFigaroAuth
