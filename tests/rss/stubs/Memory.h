#pragma once
#include <cstdint>
#include <memory>
inline bool testOom = false;
using HeapByteBuffer = std::unique_ptr<uint8_t[]>;
inline HeapByteBuffer makePsramByteBufferNoThrow(size_t n) {
  return testOom ? HeapByteBuffer{} : HeapByteBuffer(new uint8_t[n]);
}
inline HeapByteBuffer makeHeapByteBufferNoThrow(size_t n) { return makePsramByteBufferNoThrow(n); }
