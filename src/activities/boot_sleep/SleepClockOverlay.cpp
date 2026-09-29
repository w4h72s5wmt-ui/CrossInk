#include "SleepClockOverlay.h"

#include <cstdint>

#if !defined(SIMULATOR)
#include <esp_attr.h>
#endif

namespace SleepClockOverlay {
namespace {

constexpr uint32_t RETAINED_MAGIC = 0x53434C4BU;

struct RetainedClockState {
  uint32_t magic;
  ClockTextState state;
  uint16_t partialCount;
};

#if !defined(SIMULATOR)
RTC_DATA_ATTR RetainedClockState retainedClockState;
#else
RetainedClockState retainedClockState;
#endif

bool renderedThisSleep = false;

}  // namespace

bool getLastRenderedState(ClockTextState& state, uint16_t& partialCount) {
  if (retainedClockState.magic != RETAINED_MAGIC || retainedClockState.state.time[0] == '\0') {
    return false;
  }
  state = retainedClockState.state;
  partialCount = retainedClockState.partialCount;
  return true;
}

void rememberRenderedState(const ClockTextState& state, const uint16_t partialCount) {
  retainedClockState.magic = RETAINED_MAGIC;
  retainedClockState.state = state;
  retainedClockState.partialCount = partialCount;
}

void markRenderedThisSleep() { renderedThisSleep = true; }

bool wasRenderedThisSleep() { return renderedThisSleep; }

}  // namespace SleepClockOverlay
