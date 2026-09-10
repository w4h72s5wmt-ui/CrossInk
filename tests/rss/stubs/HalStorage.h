#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
inline std::map<std::string, std::string> testFiles;
inline bool testWriteFail = false;
inline bool testSyncFail = false;
inline bool testRenameFail = false;
inline bool testReadFail = false;
inline int testOpenFiles = 0;
inline size_t testWrites = 0;
class FsFile {
  std::string path;
  size_t cursor = 0;
  bool open = false;
 public:
  ~FsFile() { close(); }
  void begin(const std::string& p) { close(); path=p; cursor=0; open=true; ++testOpenFiles; }
  size_t size() const { return testFiles[path].size(); }
  int read(void* out, size_t n) {
    if (!open || testReadFail) return -1;
    const auto& contents = testFiles[path];
    n = std::min(n, contents.size() - cursor);
    std::memcpy(out, contents.data()+cursor, n);
    cursor += n;
    return static_cast<int>(n);
  }
  size_t write(const uint8_t* data, size_t n) {
    ++testWrites;
    if (!open || testWriteFail) return 0;
    testFiles[path].append(reinterpret_cast<const char*>(data),n);
    cursor += n;
    return n;
  }
  bool sync() const { return !testSyncFail; }
  void close() { if (open) { --testOpenFiles; open=false; } }
};
struct TestStorage {
  bool exists(const char* p) const { return testFiles.count(p)>0; }
  bool openFileForRead(const char*, const std::string& p, FsFile& f) {
    if (!exists(p.c_str())) return false;
    f.begin(p); return true;
  }
  bool openFileForWrite(const char*, const std::string& p, FsFile& f) {
    if (testWriteFail) return false;
    testFiles[p].clear(); f.begin(p); return true;
  }
  bool ensureDirectoryExists(const char*) { return true; }
  bool remove(const char* p) { testFiles.erase(p); return true; }
  bool rename(const char* a, const char* b) {
    if (testRenameFail || !exists(a)) return false;
    testFiles[b]=testFiles[a]; testFiles.erase(a); return true;
  }
};
inline TestStorage Storage;
