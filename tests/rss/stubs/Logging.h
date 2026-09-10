#pragma once
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
inline std::vector<std::string> testLogs;
inline void testLog(const char*, const char* format, ...) {
  char buffer[2048];
  va_list args;
  va_start(args, format);
  std::vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);
  testLogs.emplace_back(buffer);
}
#define LOG_ERR(...) testLog(__VA_ARGS__)
#define LOG_DBG(...) testLog(__VA_ARGS__)
