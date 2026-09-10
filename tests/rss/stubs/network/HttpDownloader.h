#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <string>
#include <deque>
namespace HttpDownloader {
enum DownloadError { OK, HTTP_ERROR, ABORTED, FILE_ERROR };
enum class Transport { WOLFSSL, ESP_HTTP };
using DataCallback = std::function<bool(const uint8_t*,size_t)>;
using CancelCallback = std::function<bool()>;
struct DownloadOptions {
  size_t bufferSize = 4096;
  Transport transport = Transport::WOLFSSL;
  CancelCallback shouldCancel;
};
struct Reply { std::string body; DownloadError result = OK; size_t chunk = 1024; };
inline std::deque<Reply> replies;
inline int publicCalls = 0, authCalls = 0;
inline DownloadError deliver(const DataCallback& data, const CancelCallback& cancel) {
  if (cancel && cancel()) return ABORTED;
  if (replies.empty()) return HTTP_ERROR;
  Reply reply = std::move(replies.front()); replies.pop_front();
  for (size_t pos=0; pos<reply.body.size();) {
    if (cancel && cancel()) return ABORTED;
    const size_t n=std::min(reply.chunk,reply.body.size()-pos);
    if (!data(reinterpret_cast<const uint8_t*>(reply.body.data()+pos),n)) return FILE_ERROR;
    pos+=n;
  }
  return reply.result;
}
inline DownloadError streamUrl(const std::string&, const DataCallback& data, bool*, const std::string&,
                               const std::string&, DownloadOptions options) {
  ++publicCalls;
  return deliver(data, options.shouldCancel);
}
}
