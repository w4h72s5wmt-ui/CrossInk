#pragma once

#include <BoardConfig.h>
#include <GfxRenderer.h>
#include <HalClock.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "AppCapabilities.h"
#include "CrossPointSettings.h"
#include "fontIds.h"

// X4 Pro sleep-screen lock-screen clock. The clock is an independent overlay
// and does not select or alter the user's wallpaper/theme mode.
//
// The large time is vector-style: it is built from the renderer's own rounded
// rectangles at final size. This revision is 25% larger than the first vector
// version. There is no bitmap font decoder or runtime font scaling.
namespace SleepClockOverlay {

constexpr int DATE_Y = 30;
constexpr int DATE_OUTLINE = 2;
constexpr int DIGIT_WIDTH = 88;
constexpr int DIGIT_HEIGHT = 140;
constexpr int COLON_WIDTH = 30;
constexpr int CHAR_GAP = 13;
constexpr int STROKE = 15;
constexpr int OUTLINE = 4;
constexpr int SIDE_MARGIN = 16;

struct ClockTextState {
  char time[16];
  char date[40];
  bool hasDate;
};

bool getLastRenderedState(ClockTextState& state, uint16_t& partialCount);
void rememberRenderedState(const ClockTextState& state, uint16_t partialCount);
void markRenderedThisSleep();
bool wasRenderedThisSleep();

inline bool sameDate(const ClockTextState& lhs, const ClockTextState& rhs) {
  if (lhs.hasDate != rhs.hasDate) return false;
  if (!lhs.hasDate) return true;
  return std::strcmp(lhs.date, rhs.date) == 0;
}

inline int layoutMargin() {
  // Visible top edge of the outlined date is DATE_Y - DATE_OUTLINE.
  return DATE_Y - DATE_OUTLINE;
}

inline int dateTextHeight(const GfxRenderer& renderer) {
  return renderer.getTextHeight(LEXENDDECA_16_FONT_ID);
}

inline int dateY(const GfxRenderer& renderer) {
  if (SETTINGS.sleepDatePosition == CrossPointSettings::SLEEP_CLOCK_BOTTOM) {
    // Exact vertical mirror of DATE_Y. With the outlined glyph metrics this
    // gives the same visible margin at the bottom as DATE_Y gives at the top.
    return renderer.getScreenHeight() - DATE_Y - dateTextHeight(renderer);
  }
  return DATE_Y;
}

inline int dateVisualTop(const GfxRenderer& renderer) {
  return dateY(renderer) - DATE_OUTLINE;
}

inline int dateVisualBottom(const GfxRenderer& renderer) {
  return dateY(renderer) + dateTextHeight(renderer) + DATE_OUTLINE;
}

inline int topDateVisualBottom(const GfxRenderer& renderer) {
  return DATE_Y + dateTextHeight(renderer) + DATE_OUTLINE;
}

inline int topClockY(const GfxRenderer& renderer) {
  const int margin = layoutMargin();
  // The clock positions are anchored to the canonical TOP date geometry so
  // choosing the date's position does not move the clock itself.
  return topDateVisualBottom(renderer) + margin + OUTLINE;
}

inline int timeTop(const GfxRenderer& renderer) {
  const int topY = topClockY(renderer);
  if (SETTINGS.sleepClockPosition == CrossPointSettings::SLEEP_CLOCK_BOTTOM) {
    // Mirror the TOP clock's distance from the top edge:
    // top edge -> top clock == bottom clock -> bottom edge.
    // This deliberately keeps the lower DU window away from the panel edge.
    return renderer.getScreenHeight() - topY - DIGIT_HEIGHT;
  }
  return topY;
}

inline int updateLogicalTop(const GfxRenderer& renderer, const bool includeDate) {
  int top = timeTop(renderer) - OUTLINE;
  if (includeDate) top = std::min(top, dateVisualTop(renderer));
  return top - 8;
}

inline int updateLogicalBottom(const GfxRenderer& renderer, const bool includeDate) {
  int bottom = timeTop(renderer) + DIGIT_HEIGHT + OUTLINE;
  if (includeDate) bottom = std::max(bottom, dateVisualBottom(renderer));
  return bottom + 8;
}

enum Segment : uint8_t {
  SEG_A = 1u << 0,
  SEG_B = 1u << 1,
  SEG_C = 1u << 2,
  SEG_D = 1u << 3,
  SEG_E = 1u << 4,
  SEG_F = 1u << 5,
  SEG_G = 1u << 6,
};

inline bool enabled() {
#if FREEINK_DEVICE_X4PRO
  return BoardConfig::isX4Pro() && halClock.isAvailable() && SETTINGS.sleepClockEnabled != 0;
#else
  return false;
#endif
}

inline char dateSeparatorChar() {
  switch (SETTINGS.dateSeparator) {
    case CrossPointSettings::DATE_SEPARATOR_PERIOD:
      return '.';
    case CrossPointSettings::DATE_SEPARATOR_HYPHEN:
      return '-';
    case CrossPointSettings::DATE_SEPARATOR_SLASH:
    default:
      return '/';
  }
}

inline uint8_t digitSegments(const char c) {
  switch (c) {
    case '0':
      return SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F;
    case '1':
      return SEG_B | SEG_C;
    case '2':
      return SEG_A | SEG_B | SEG_G | SEG_E | SEG_D;
    case '3':
      return SEG_A | SEG_B | SEG_G | SEG_C | SEG_D;
    case '4':
      return SEG_F | SEG_G | SEG_B | SEG_C;
    case '5':
      return SEG_A | SEG_F | SEG_G | SEG_C | SEG_D;
    case '6':
      return SEG_A | SEG_F | SEG_G | SEG_E | SEG_C | SEG_D;
    case '7':
      return SEG_A | SEG_B | SEG_C;
    case '8':
      return SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F | SEG_G;
    case '9':
      return SEG_A | SEG_B | SEG_C | SEG_D | SEG_F | SEG_G;
    default:
      return 0;
  }
}

inline void fillCapsule(const GfxRenderer& renderer, int x, int y, int width, int height, const bool black) {
  if (black) {
    x -= OUTLINE;
    y -= OUTLINE;
    width += OUTLINE * 2;
    height += OUTLINE * 2;
  }
  const int radius = std::min(width, height) / 2;
  renderer.fillRoundedRect(x, y, width, height, radius, black ? Color::Black : Color::White);
}

inline void drawDigitPass(const GfxRenderer& renderer, const uint8_t mask, const int x, const int y,
                          const bool black) {
  constexpr int horizontalX = 10;
  constexpr int horizontalWidth = DIGIT_WIDTH - horizontalX * 2;
  constexpr int upperVerticalY = 10;
  constexpr int upperVerticalHeight = 54;
  constexpr int middleY = 63;
  constexpr int lowerVerticalY = 76;
  constexpr int lowerVerticalHeight = 54;
  constexpr int bottomY = DIGIT_HEIGHT - STROKE;
  constexpr int rightX = DIGIT_WIDTH - STROKE;

  if (mask & SEG_A) fillCapsule(renderer, x + horizontalX, y, horizontalWidth, STROKE, black);
  if (mask & SEG_B) fillCapsule(renderer, x + rightX, y + upperVerticalY, STROKE, upperVerticalHeight, black);
  if (mask & SEG_C) fillCapsule(renderer, x + rightX, y + lowerVerticalY, STROKE, lowerVerticalHeight, black);
  if (mask & SEG_D) fillCapsule(renderer, x + horizontalX, y + bottomY, horizontalWidth, STROKE, black);
  if (mask & SEG_E) fillCapsule(renderer, x, y + lowerVerticalY, STROKE, lowerVerticalHeight, black);
  if (mask & SEG_F) fillCapsule(renderer, x, y + upperVerticalY, STROKE, upperVerticalHeight, black);
  if (mask & SEG_G) fillCapsule(renderer, x + horizontalX, y + middleY, horizontalWidth, STROKE, black);
}

inline void drawDigit(const GfxRenderer& renderer, const char c, const int x, const int y) {
  const uint8_t mask = digitSegments(c);
  if (mask == 0) return;
  drawDigitPass(renderer, mask, x, y, true);
  drawDigitPass(renderer, mask, x, y, false);
}

inline void drawColon(const GfxRenderer& renderer, const int x, const int y) {
  constexpr int dot = 15;
  constexpr int dotX = (COLON_WIDTH - dot) / 2;
  constexpr int dot1Y = 39;
  constexpr int dot2Y = 86;

  fillCapsule(renderer, x + dotX, y + dot1Y, dot, dot, true);
  fillCapsule(renderer, x + dotX, y + dot2Y, dot, dot, true);
  fillCapsule(renderer, x + dotX, y + dot1Y, dot, dot, false);
  fillCapsule(renderer, x + dotX, y + dot2Y, dot, dot, false);
}

inline int charWidth(const char c) {
  return c == ':' ? COLON_WIDTH : (digitSegments(c) != 0 ? DIGIT_WIDTH : 0);
}

inline int measureTime(const char* text) {
  int width = 0;
  bool hasPrevious = false;
  for (const char* p = text; p && *p; ++p) {
    const int w = charWidth(*p);
    if (w <= 0) continue;
    if (hasPrevious) width += CHAR_GAP;
    width += w;
    hasPrevious = true;
  }
  return width;
}

inline void drawVectorTime(const GfxRenderer& renderer, const char* text, int x, const int y) {
  bool hasPrevious = false;
  for (const char* p = text; p && *p; ++p) {
    const int w = charWidth(*p);
    if (w <= 0) continue;
    if (hasPrevious) x += CHAR_GAP;
    if (*p == ':') {
      drawColon(renderer, x, y);
    } else {
      drawDigit(renderer, *p, x, y);
    }
    x += w;
    hasPrevious = true;
  }
}

inline void drawOutlinedSystemText(const GfxRenderer& renderer, const int fontId, const int x, const int y,
                                   const char* text, const EpdFontFamily::Style style,
                                   const int outlinePx = 1) {
  for (int dy = -outlinePx; dy <= outlinePx; ++dy) {
    for (int dx = -outlinePx; dx <= outlinePx; ++dx) {
      if (dx == 0 && dy == 0) continue;
      renderer.drawText(fontId, x + dx, y + dy, text, true, style);
    }
  }
  renderer.drawText(fontId, x, y, text, false, style);
}

inline bool roundFiveMinuteDisplay(char* time, const size_t timeSize, const uint8_t second) {
  if (SETTINGS.sleepClockRefresh != CrossPointSettings::SLEEP_CLOCK_EVERY_5_MINUTES) return true;

  int hour24 = 0;
  int minute = 0;
  if (SETTINGS.clockFormat != 0) {
    char suffix[3] = {};
    int hour12 = 0;
    if (std::sscanf(time, "%d:%d %2s", &hour12, &minute, suffix) != 3) return false;
    hour24 = hour12 % 12;
    if (suffix[0] == 'P' || suffix[0] == 'p') hour24 += 12;
  } else if (std::sscanf(time, "%d:%d", &hour24, &minute) != 2) {
    return false;
  }

  int totalMinutes = hour24 * 60 + minute;
  const int remainder = minute % 5;
  const bool roundUp = remainder > 2 || (remainder == 2 && second >= 30);
  totalMinutes += roundUp ? (5 - remainder) : -remainder;
  totalMinutes = ((totalMinutes % 1440) + 1440) % 1440;

  hour24 = totalMinutes / 60;
  minute = totalMinutes % 60;
  int written = 0;
  if (SETTINGS.clockFormat != 0) {
    const bool pm = hour24 >= 12;
    int hour12 = hour24 % 12;
    if (hour12 == 0) hour12 = 12;
    written = std::snprintf(time, timeSize, "%d:%02d %s", hour12, minute, pm ? "PM" : "AM");
  } else {
    written = std::snprintf(time, timeSize, "%02d:%02d", hour24, minute);
  }
  return written > 0 && static_cast<size_t>(written) < timeSize;
}

inline bool formatCurrentState(ClockTextState& state) {
  state = ClockTextState{};

  uint8_t rtcHour = 0;
  uint8_t rtcMinute = 0;
  uint8_t rtcSecond = 0;
  if (!halClock.getTime(rtcHour, rtcMinute, rtcSecond)) return false;

  if (!halClock.formatTime(state.time, sizeof(state.time), SETTINGS.clockUtcOffsetQ,
                           SETTINGS.clockFormat != 0) ||
      !roundFiveMinuteDisplay(state.time, sizeof(state.time), rtcSecond)) {
    return false;
  }

  if (SETTINGS.clockDateHasBeenSynced != 0) {
    const auto dateFormat = SETTINGS.dateFormat < HalClock::DATE_FORMAT_COUNT
                                ? static_cast<HalClock::DateFormat>(SETTINGS.dateFormat)
                                : HalClock::MONTH_DAY_YEAR_LONG;
    state.hasDate =
        halClock.formatDate(state.date, sizeof(state.date), SETTINGS.clockUtcOffsetQ, dateFormat, dateSeparatorChar());
  }
  return true;
}

inline bool drawState(GfxRenderer& renderer, const ClockTextState& state) {
  if (!enabled() || state.time[0] == '\0') return false;

  char mainTime[8] = {};
  char suffix[4] = {};
  const char* space = std::strchr(state.time, ' ');
  const size_t mainLength = space ? static_cast<size_t>(space - state.time) : std::strlen(state.time);
  if (mainLength == 0 || mainLength >= sizeof(mainTime)) return false;
  std::memcpy(mainTime, state.time, mainLength);
  mainTime[mainLength] = '\0';
  if (space && space[1] != '\0') {
    suffix[0] = space[1];
    if (space[2] != '\0') suffix[1] = space[2];
  }

  if (state.hasDate && state.date[0] != '\0') {
    const auto style = EpdFontFamily::BOLD;
    const int dateWidth = renderer.getTextWidth(LEXENDDECA_16_FONT_ID, state.date, style);
    const int dateX = (renderer.getScreenWidth() - dateWidth) / 2;
    drawOutlinedSystemText(renderer, LEXENDDECA_16_FONT_ID, dateX, dateY(renderer), state.date, style, 2);
  }

  const int timeWidth = measureTime(mainTime);
  if (timeWidth <= 0 || timeWidth > renderer.getScreenWidth() - SIDE_MARGIN * 2) return false;
  const int timeX = (renderer.getScreenWidth() - timeWidth) / 2;
  const int timeY = timeTop(renderer);
  drawVectorTime(renderer, mainTime, timeX, timeY);

  if (suffix[0] != '\0') {
    const auto style = EpdFontFamily::BOLD;
    const int suffixWidth = renderer.getTextWidth(LEXENDDECA_16_FONT_ID, suffix, style);
    int suffixX = timeX + timeWidth + 10;
    const int maxSuffixX = renderer.getScreenWidth() - SIDE_MARGIN - suffixWidth;
    if (suffixX > maxSuffixX) suffixX = maxSuffixX;
    drawOutlinedSystemText(renderer, LEXENDDECA_16_FONT_ID, suffixX, timeY + 84, suffix, style);
  }

  return true;
}

inline bool draw(GfxRenderer& renderer) {
  ClockTextState state;
  if (!formatCurrentState(state) || !drawState(renderer, state)) return false;
  rememberRenderedState(state, 0);
  markRenderedThisSleep();
  return true;
}

}  // namespace SleepClockOverlay
