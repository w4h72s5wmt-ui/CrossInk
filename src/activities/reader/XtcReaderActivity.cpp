/**
 * XtcReaderActivity.cpp
 *
 * XTC ebook reader activity implementation
 * Displays pre-rendered XTC pages on e-ink display
 */

#include "XtcReaderActivity.h"

#include <FsHelpers.h>
#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <Memory.h>

#include <algorithm>

#include "BookStatsActivity.h"
#include "CrossPointSettings.h"
#include "CrossPointState.h"
#include "GlobalActions.h"
#include "MappedInputManager.h"
#include "QuickActions.h"
#include "ReaderUtils.h"
#include "RecentBooksStore.h"
#include "XtcReaderChapterSelectionActivity.h"
#include "XtcReaderMenuActivity.h"
#include "activities/boot_sleep/SleepCoverAssets.h"
#include "activities/util/ConfirmationActivity.h"
#include "components/UITheme.h"
#include "components/themes/lyra/LyraCarouselTheme.h"
#include "fontIds.h"
#include "util/BookCacheUtils.h"

namespace {
constexpr unsigned long MIN_READING_STATS_PAGE_MS = 2000UL;
constexpr uint16_t MIN_TIME_LEFT_PACE_SAMPLE_COUNT = 3;
constexpr unsigned long LONG_PRESS_MENU_MS = 600UL;

std::string confirmationHeading(const StrId actionLabelId) {
  return std::string(tr(STR_CONFIRM)) + ": " + std::string(I18N.get(actionLabelId));
}

void drawToast(const GfxRenderer& renderer, const char* msg) {
  constexpr int toastPadX = 20;
  constexpr int toastPadY = 12;
  const bool toastBackgroundBlack = ReaderUtils::readerForegroundBlack();
  const int msgW = renderer.getTextWidth(UI_10_FONT_ID, msg);
  const int msgH = renderer.getLineHeight(UI_10_FONT_ID);
  const int toastW = msgW + toastPadX * 2;
  const int toastH = msgH + toastPadY * 2;
  const int toastX = (renderer.getScreenWidth() - toastW) / 2;
  const int toastY = (renderer.getScreenHeight() - toastH) / 2;
  renderer.fillRect(toastX, toastY, toastW, toastH, toastBackgroundBlack);
  renderer.drawRect(toastX, toastY, toastW, toastH, !toastBackgroundBlack);
  renderer.drawText(UI_10_FONT_ID, toastX + toastPadX, toastY + toastPadY, msg, !toastBackgroundBlack);
  renderer.displayBuffer();
}

enum class XtchRenderPass { Base, Lsb, Msb };

struct XtcZoomViewport {
  uint16_t x = 0;
  uint16_t y = 0;
  uint16_t width = 0;
  uint16_t height = 0;
};

bool isXtcMidRes15x(const uint16_t pageWidth, const uint16_t pageHeight, const GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  return screenWidth > 0 && screenHeight > 0 && static_cast<int>(pageWidth) * 2 == screenWidth * 3 &&
         static_cast<int>(pageHeight) * 2 == screenHeight * 3;
}

bool isXtcHiRes2x(const uint16_t pageWidth, const uint16_t pageHeight, const GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  return screenWidth > 0 && screenHeight > 0 && pageWidth == screenWidth * 2 && pageHeight == screenHeight * 2;
}

size_t xtcBitmapSize(const uint8_t bitDepth, const uint16_t pageWidth, const uint16_t pageHeight) {
  if (bitDepth == 2) return ((static_cast<size_t>(pageWidth) * pageHeight + 7) / 8) * 2;
  return ((pageWidth + 7) / 8) * pageHeight;
}

XtcZoomViewport makeXtcZoomViewport(const uint16_t pageWidth, const uint16_t pageHeight, const GfxRenderer& renderer,
                                    const int tapX, const int tapY) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  if (pageWidth == 0 || pageHeight == 0 || screenWidth <= 1 || screenHeight <= 1) return {};

  const uint16_t visibleWidth = std::max<uint16_t>(1, pageWidth / 2);
  const uint16_t visibleHeight = std::max<uint16_t>(1, pageHeight / 2);
  const int sourceTapX =
      std::clamp((tapX * static_cast<int>(pageWidth) + screenWidth / 2) / screenWidth, 0,
                 static_cast<int>(pageWidth) - 1);
  const int sourceTapY =
      std::clamp((tapY * static_cast<int>(pageHeight) + screenHeight / 2) / screenHeight, 0,
                 static_cast<int>(pageHeight) - 1);

  const int sourceX =
      std::clamp(sourceTapX - static_cast<int>(visibleWidth) / 2, 0, static_cast<int>(pageWidth - visibleWidth));
  const int sourceY =
      std::clamp(sourceTapY - static_cast<int>(visibleHeight) / 2, 0, static_cast<int>(pageHeight - visibleHeight));

  return {static_cast<uint16_t>(sourceX), static_cast<uint16_t>(sourceY), visibleWidth, visibleHeight};
}

bool xtcPixelBlack(const uint8_t* pageBuffer, const size_t srcRowBytes, const uint16_t pageWidth,
                   const uint16_t pageHeight, int x, int y) {
  x = std::clamp(x, 0, static_cast<int>(pageWidth) - 1);
  y = std::clamp(y, 0, static_cast<int>(pageHeight) - 1);
  return !((pageBuffer[static_cast<size_t>(y) * srcRowBytes + static_cast<size_t>(x) / 8] >>
            (7 - (static_cast<size_t>(x) & 7))) &
           1);
}

void drawXtcEpx2x(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                  const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();

  auto rowPixelBlack = [](const uint8_t* row, const int x) {
    return ((row[x >> 3] >> (7 - (x & 7))) & 1) == 0;
  };

  for (uint16_t sy = viewport.y; sy < viewport.y + viewport.height; ++sy) {
    const int y = sy;
    const uint8_t* rowN = pageBuffer + static_cast<size_t>(std::max(0, y - 1)) * srcRowBytes;
    const uint8_t* rowC = pageBuffer + static_cast<size_t>(y) * srcRowBytes;
    const uint8_t* rowS =
        pageBuffer + static_cast<size_t>(std::min(static_cast<int>(pageHeight) - 1, y + 1)) * srcRowBytes;

    int x = viewport.x;
    bool w = rowPixelBlack(rowC, std::max(0, x - 1));
    bool e = rowPixelBlack(rowC, x);

    for (; x < static_cast<int>(viewport.x + viewport.width); ++x) {
      const int xr = std::min(static_cast<int>(pageWidth) - 1, x + 1);
      const bool r = rowPixelBlack(rowC, xr);
      const bool n = rowPixelBlack(rowN, x);
      const bool s = rowPixelBlack(rowS, x);

      bool q0 = e;
      bool q1 = e;
      bool q2 = e;
      bool q3 = e;
      if (n != s && w != r) {
        q0 = w == n ? w : e;
        q1 = n == r ? r : e;
        q2 = w == s ? w : e;
        q3 = s == r ? r : e;
      }

      const int dx = (x - static_cast<int>(viewport.x)) * 2;
      const int dy = (y - static_cast<int>(viewport.y)) * 2;
      if (q0 && dx < screenWidth && dy < screenHeight) renderer.drawPixel(dx, dy, true);
      if (q1 && dx + 1 < screenWidth && dy < screenHeight) renderer.drawPixel(dx + 1, dy, true);
      if (q2 && dx < screenWidth && dy + 1 < screenHeight) renderer.drawPixel(dx, dy + 1, true);
      if (q3 && dx + 1 < screenWidth && dy + 1 < screenHeight) renderer.drawPixel(dx + 1, dy + 1, true);

      w = e;
      e = r;
    }
  }
}

uint8_t xtchPixelValue(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight, int x, int y) {
  x = std::clamp(x, 0, static_cast<int>(pageWidth) - 1);
  y = std::clamp(y, 0, static_cast<int>(pageHeight) - 1);
  const size_t planeSize = (static_cast<size_t>(pageWidth) * pageHeight + 7) / 8;
  const size_t colBytes = (pageHeight + 7) / 8;
  const size_t colIndex = static_cast<size_t>(pageWidth - 1 - x);
  const size_t byteOffset = colIndex * colBytes + static_cast<size_t>(y) / 8;
  const uint8_t bit = static_cast<uint8_t>(7 - (y & 7));
  const uint8_t bit1 = (pageBuffer[byteOffset] >> bit) & 1;
  const uint8_t bit2 = (pageBuffer[planeSize + byteOffset] >> bit) & 1;
  return static_cast<uint8_t>((bit1 << 1) | bit2);
}

uint8_t xtchBlackness(const uint8_t value) {
  switch (value) {
    case 1:
      return 160;
    case 2:
      return 80;
    case 3:
      return 255;
    default:
      return 0;
  }
}

bool xtcDitherBlack(const int blackness, const int x, const int y) {
  static constexpr uint8_t BAYER_4X4[16] = {
      0, 8, 2, 10,
      12, 4, 14, 6,
      3, 11, 1, 9,
      15, 7, 13, 5,
  };
  if (blackness <= 0) return false;
  if (blackness >= 255) return true;
  const int threshold = static_cast<int>(BAYER_4X4[((y & 3) << 2) | (x & 3)]) * 16 + 8;
  return blackness >= threshold;
}

void drawXtchFast1x(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                    GfxRenderer& renderer) {
  const int maxX = std::min<int>(pageWidth, renderer.getScreenWidth());
  const int maxY = std::min<int>(pageHeight, renderer.getScreenHeight());
  for (int y = 0; y < maxY; ++y) {
    for (int x = 0; x < maxX; ++x) {
      if (xtcDitherBlack(xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, x, y)), x, y)) {
        renderer.drawPixel(x, y, true);
      }
    }
  }
}

void drawXtchLite2x(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                    const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (uint16_t sy = viewport.y; sy < viewport.y + viewport.height; ++sy) {
    for (uint16_t sx = viewport.x; sx < viewport.x + viewport.width; ++sx) {
      const int e = xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy));
      const int r = xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, static_cast<int>(sx) + 1, sy));
      const int s = xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, static_cast<int>(sy) + 1));
      const int d = xtchBlackness(
          xtchPixelValue(pageBuffer, pageWidth, pageHeight, static_cast<int>(sx) + 1, static_cast<int>(sy) + 1));

      const int q0 = e;
      const int q1 = (3 * e + r + 2) >> 2;
      const int q2 = (3 * e + s + 2) >> 2;
      const int q3 = (9 * e + 3 * r + 3 * s + d + 8) >> 4;

      const int dx = static_cast<int>(sx - viewport.x) * 2;
      const int dy = static_cast<int>(sy - viewport.y) * 2;
      if (dx < screenWidth && dy < screenHeight && xtcDitherBlack(q0, dx, dy)) renderer.drawPixel(dx, dy, true);
      if (dx + 1 < screenWidth && dy < screenHeight && xtcDitherBlack(q1, dx + 1, dy))
        renderer.drawPixel(dx + 1, dy, true);
      if (dx < screenWidth && dy + 1 < screenHeight && xtcDitherBlack(q2, dx, dy + 1))
        renderer.drawPixel(dx, dy + 1, true);
      if (dx + 1 < screenWidth && dy + 1 < screenHeight && xtcDitherBlack(q3, dx + 1, dy + 1))
        renderer.drawPixel(dx + 1, dy + 1, true);
    }
  }
}

void drawXtcMidResNormal(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                         GfxRenderer& renderer) {
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = (y * 3) >> 1;
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = (x * 3) >> 1;
      const int blackness =
          (static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx, sy)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx + 1, sy)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx, sy + 1)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx + 1, sy + 1))) *
          64;
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtcMidResZoom(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                       const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = viewport.y + ((y * 3 + 1) >> 2);
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = viewport.x + ((x * 3 + 1) >> 2);
      if (xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx, sy)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtchMidResNormal(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                          GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = (y * 3) >> 1;
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = (x * 3) >> 1;
      const int blackness =
          (xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx + 1, sy)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy + 1)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx + 1, sy + 1)) +
           2) /
          4;
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtchMidResZoom(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                        const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = viewport.y + ((y * 3 + 1) >> 2);
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = viewport.x + ((x * 3 + 1) >> 2);
      const int blackness = xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy));
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtcHiResNormal(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                        GfxRenderer& renderer) {
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = y * 2;
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = x * 2;
      const int blackness =
          (static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx, sy)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx + 1, sy)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx, sy + 1)) +
           static_cast<int>(xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, sx + 1, sy + 1))) *
          64;
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtcHiResZoom(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                      const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = viewport.y + y;
    for (int x = 0; x < screenWidth; ++x) {
      if (xtcPixelBlack(pageBuffer, srcRowBytes, pageWidth, pageHeight, viewport.x + x, sy)) {
        renderer.drawPixel(x, y, true);
      }
    }
  }
}

void drawXtchHiResNormal(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                         GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = y * 2;
    for (int x = 0; x < screenWidth; ++x) {
      const int sx = x * 2;
      const int blackness =
          (xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx + 1, sy)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx, sy + 1)) +
           xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, sx + 1, sy + 1)) +
           2) /
          4;
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

void drawXtchHiResZoom(const uint8_t* pageBuffer, const uint16_t pageWidth, const uint16_t pageHeight,
                       const XtcZoomViewport& viewport, GfxRenderer& renderer) {
  const int screenWidth = renderer.getScreenWidth();
  const int screenHeight = renderer.getScreenHeight();
  for (int y = 0; y < screenHeight; ++y) {
    const int sy = viewport.y + y;
    for (int x = 0; x < screenWidth; ++x) {
      const int blackness = xtchBlackness(xtchPixelValue(pageBuffer, pageWidth, pageHeight, viewport.x + x, sy));
      if (xtcDitherBlack(blackness, x, y)) renderer.drawPixel(x, y, true);
    }
  }
}

bool streamXtchRenderPass(const Xtc& xtc, const uint32_t pageIndex, const uint16_t pageWidth, const uint16_t pageHeight,
                          GfxRenderer& renderer, const XtchRenderPass pass) {
  const size_t planeSize = (static_cast<size_t>(pageWidth) * pageHeight + 7) / 8;
  const size_t colBytes = (pageHeight + 7) / 8;
  const xtc::XtcError error =
      xtc.loadPageStreaming(pageIndex, [&](const uint8_t* data, const size_t size, const size_t offset) {
        for (size_t i = 0; i < size; i++) {
          const size_t absoluteOffset = offset + i;
          const bool secondPlane = absoluteOffset >= planeSize;
          const size_t planeOffset = secondPlane ? absoluteOffset - planeSize : absoluteOffset;
          const size_t colIndex = planeOffset / colBytes;
          if (colIndex >= pageWidth) continue;

          const uint16_t x = static_cast<uint16_t>(pageWidth - 1 - colIndex);
          const uint16_t yBase = static_cast<uint16_t>((planeOffset % colBytes) * 8);
          for (uint8_t bit = 0; bit < 8 && yBase + bit < pageHeight; bit++) {
            const uint16_t y = static_cast<uint16_t>(yBase + bit);
            const bool bitSet = ((data[i] >> (7 - bit)) & 1) != 0;
            switch (pass) {
              case XtchRenderPass::Base:
                // Applying both planes onto a white buffer produces bit1 OR bit2.
                if (bitSet) renderer.drawPixel(x, y, true);
                break;
              case XtchRenderPass::Lsb:
                // Starting black, plane 1 clears candidates and plane 2 removes
                // false positives, leaving white only for XTH value 1.
                if (!bitSet) renderer.drawPixel(x, y, secondPlane);
                break;
              case XtchRenderPass::Msb:
                // XTH values 1 and 2 are bit1 XOR bit2. Plane 1 seeds the
                // framebuffer; set plane-2 bits then toggle those pixels.
                if (!secondPlane && bitSet) {
                  renderer.drawPixel(x, y, false);
                } else if (secondPlane && bitSet) {
                  renderer.drawPixel(x, y, !renderer.isPixelBlack(x, y));
                }
                break;
            }
          }
        }
      });
  if (error == xtc::XtcError::OK) return true;
  LOG_ERR("XTR", "Failed to stream XTCH page %lu: %s", pageIndex, xtc::errorToString(error));
  return false;
}
}  // namespace

void XtcReaderActivity::onEnter() {
  Activity::onEnter();

  if (!xtc) {
    return;
  }

  xtc->setupCacheDir();

  const bool midRes15x = isXtcMidRes15x(xtc->getPageWidth(), xtc->getPageHeight(), renderer);
  const bool hiRes2x = isXtcHiRes2x(xtc->getPageWidth(), xtc->getPageHeight(), renderer);
  const bool needsSourceCache = xtc->getBitDepth() == 2 || midRes15x || hiRes2x;
  if (needsSourceCache && psramHeapAvailable()) {
    sourcePageBufferSize = xtcBitmapSize(xtc->getBitDepth(), xtc->getPageWidth(), xtc->getPageHeight());
    sourcePageBuffer = makePsramByteBufferNoThrow(sourcePageBufferSize);
    if (!sourcePageBuffer) {
      LOG_ERR("XTR", "Failed to allocate XTC source PSRAM buffer (%lu bytes)",
              static_cast<unsigned long>(sourcePageBufferSize));
      sourcePageBufferSize = 0;
    } else {
      sourceBufferedPage = UINT32_MAX;
      LOG_DBG("XTR", "XTC source cache enabled: %ux%u %u-bit, %lu bytes",
              xtc->getPageWidth(), xtc->getPageHeight(), xtc->getBitDepth(),
              static_cast<unsigned long>(sourcePageBufferSize));
    }
  }

  // Activate reader-specific front button mapping (if configured).
  mappedInput.setReaderMode(true);

  // Load saved progress
  loadProgress();

  stats = BookReadingStats::load(xtc->getCachePath());
  globalStats = GlobalReadingStats::load();
  sessionReadingSeconds = 0;
  hasSessionStartLocalDateTime = getCurrentLocalReadingStatsDateTime(sessionStartLocalDateTime);

  // Save current XTC as last opened book and add to recent books
  APP_STATE.openEpubPath = xtc->getPath();
  APP_STATE.saveToFile();
  if (!skipRecentBookUpdateOnEntry) {
    RECENT_BOOKS.addOrUpdateBook(xtc->getPath(), xtc->getTitle(), xtc->getAuthor(), xtc->getThumbBmpPath());
  }
  SleepCoverAssets::prepareXtc(*xtc);

  // Trigger first update
  requestUpdate();
}

void XtcReaderActivity::onExit() {
  mappedInput.setReaderTouchscreenOverride(false);
  Activity::onExit();

  mappedInput.setReaderMode(false);

  if (!flushQueuedProgress()) {
    LOG_ERR("XTR", "Failed to flush debounced reader progress on exit");
  }

  APP_STATE.readerActivityLoadCount = 0;
  APP_STATE.saveToFile();

  commitReadingStats();

  // Generate carousel thumbnails while XTC is still loaded so the home screen
  // can display the cover on the very first render without a loading popup.
  if (xtc &&
      static_cast<CrossPointSettings::UI_THEME>(SETTINGS.uiTheme) == CrossPointSettings::UI_THEME::LYRA_CAROUSEL) {
    xtc->generateThumbBmp(LyraCarouselTheme::kCenterCoverW, LyraCarouselTheme::kCenterCoverH);
    xtc->generateThumbBmp(LyraCarouselTheme::kSideCoverW, LyraCarouselTheme::kSideCoverH);
  }

  sourcePageBuffer.reset();
  sourcePageBufferSize = 0;
  sourceBufferedPage = UINT32_MAX;
  xtc.reset();
}

void XtcReaderActivity::openReaderMenu() {
  bool hasChapters = false;
  std::string title;
  {
    RenderLock lock(*this);
    if (!xtc) {
      return;
    }
    hasChapters = xtc->hasChapters() && xtc->getChapterCount() > 0;
    title = xtc->getTitle();
  }

  pauseReadingStatsTimer("reader_menu");
  startActivityForResult(
      std::make_unique<XtcReaderMenuActivity>(renderer, mappedInput, std::move(title), hasChapters, stats.isCompleted),
      [this](const ActivityResult& result) {
        const auto* menu = std::get_if<MenuResult>(&result.data);
        if (result.isCancelled || menu == nullptr) {
          resumeReadingStatsTimer("reader_menu_return");
          requestUpdate();
          return;
        }
        onReaderMenuConfirm(menu->action);
      });
}

void XtcReaderActivity::loop() {
  if (!xtc) {
    return;
  }
  if (quickActionsPopup.handleInput(mappedInput, [this] { requestUpdate(); })) return;

  const bool shortcutPageTurn = shortcutPageTurnPending;
  shortcutPageTurnPending = false;
  const bool shortcutPreviousPage = shortcutPreviousPagePending;
  shortcutPreviousPagePending = false;

  const auto touch = ReaderUtils::detectTouchPageTurn(renderer, mappedInput);
  const int statusBarHeight = UITheme::getInstance().getStatusBarHeight();
  const auto statusBarMode = static_cast<CrossPointSettings::XTC_STATUS_BAR_MODE>(SETTINGS.xtcStatusBarMode);
  const bool tappedStatusBar =
      touch.tapped && ((statusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_TOP &&
                        ReaderUtils::isTopStatusBarTap(renderer, touch.y, statusBarHeight)) ||
                       (statusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_BOTTOM &&
                        ReaderUtils::isBottomStatusBarTap(renderer, touch.y, statusBarHeight)));
  if (tappedStatusBar) {
    statusBarVisible = !statusBarVisible;
    requestUpdate();
    return;
  }

  // One short tap toggles a single 2x zoom level. Native 1-bit pages
  // need no persistent source cache; XTCH and 960x1600 sources do.
  const bool scaledZoomSource =
      isXtcMidRes15x(xtc->getPageWidth(), xtc->getPageHeight(), renderer) ||
      isXtcHiRes2x(xtc->getPageWidth(), xtc->getPageHeight(), renderer);
  const bool zoomSupported =
      scaledZoomSource ? static_cast<bool>(sourcePageBuffer)
                       : (xtc->getBitDepth() == 1 ||
                          (xtc->getBitDepth() == 2 && static_cast<bool>(sourcePageBuffer)));
  if (touch.tapped && zoomSupported && currentPage < xtc->getPageCount()) {
    if (zoomActive) {
      zoomActive = false;
      LOG_DBG("XTR", "XTC zoom off");
    } else {
      zoomCenterX = touch.x;
      zoomCenterY = touch.y;
      zoomActive = true;
      LOG_DBG("XTR", "XTC %u-bit zoom on around %d,%d", xtc->getBitDepth(), zoomCenterX, zoomCenterY);
    }
    zoomRefreshPending = true;
    requestUpdate();
    return;
  }

  // Paged back into the book: release the end screen app and its theme tokens.
  {
    RenderLock lock(*this);
    if (currentPage < xtc->getPageCount() && endOfBookOptions) {
      endOfBookOptions.reset();
    }
  }

  // While the end screen suggestion menu is showing it owns Confirm/Back/navigation
  // input. Anything it doesn't handle (e.g. long-press Back to the file browser) falls
  // through to the regular handlers below; page turns are absorbed by the end-of-book
  // block.
  EndOfBookOptions::Action endOfBookAction = EndOfBookOptions::Action::None;
  std::string openPath;
  bool endOfBookNeedsUpdate = false;
  {
    RenderLock lock(*this);
    if (currentPage >= xtc->getPageCount() && endOfBookOptions && endOfBookOptions->menuActive()) {
      endOfBookAction = endOfBookOptions->handleMenuInput(mappedInput, &openPath);
      if (endOfBookAction == EndOfBookOptions::Action::LastPage) {
        const uint32_t pageCount = xtc->getPageCount();
        currentPage = pageCount > 0 ? pageCount - 1 : 0;
        endOfBookNeedsUpdate = true;
      } else if (endOfBookAction == EndOfBookOptions::Action::Redraw) {
        endOfBookNeedsUpdate = true;
      }
    }
  }
  switch (endOfBookAction) {
    case EndOfBookOptions::Action::OpenBook:
      activityManager.goToReader(openPath);
      return;
    case EndOfBookOptions::Action::GoHome:
      onGoHome();
      return;
    case EndOfBookOptions::Action::LastPage:
    case EndOfBookOptions::Action::Redraw:
      if (endOfBookNeedsUpdate) {
        requestUpdate();
      }
      return;
    case EndOfBookOptions::Action::None:
      break;
  }

  if (longPressMenuHandled) {
    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm) ||
        !mappedInput.isPressed(MappedInputManager::Button::Confirm)) {
      longPressMenuHandled = false;
    }
    return;
  }

  const auto longPressMenuAction =
      static_cast<CrossPointSettings::LONG_PRESS_MENU_ACTION>(SETTINGS.longPressMenuAction);
  if (longPressMenuAction == CrossPointSettings::LONG_MENU_QUICK_LOCK &&
      mappedInput.isPressed(MappedInputManager::Button::Confirm) && mappedInput.getHeldTime() >= LONG_PRESS_MENU_MS) {
    longPressMenuHandled = true;
    mappedInput.suppressNextConfirmRelease();
    handleGlobalPowerButtonAction(CrossPointSettings::SHORT_PWRBTN::QUICK_LOCK, QuickLockTrigger::LongMenu);
    return;
  }
  if (longPressMenuAction == CrossPointSettings::LONG_MENU_QUICK_LOCK &&
      mappedInput.wasReleased(MappedInputManager::Button::Confirm) && mappedInput.getHeldTime() >= LONG_PRESS_MENU_MS) {
    mappedInput.suppressNextConfirmRelease();
    handleGlobalPowerButtonAction(CrossPointSettings::SHORT_PWRBTN::QUICK_LOCK, QuickLockTrigger::LongMenu);
    return;
  }

  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm) || ReaderUtils::isTouchMenuGesture(mappedInput)) {
    openReaderMenu();
    return;
  }

  if (longPressBackHandled) {
    if (mappedInput.wasReleased(MappedInputManager::Button::Back) ||
        !mappedInput.isPressed(MappedInputManager::Button::Back)) {
      longPressBackHandled = false;
    }
    return;
  }

  if (!longPressBackHandled && mappedInput.isPressed(MappedInputManager::Button::Back) &&
      mappedInput.getHeldTime() >= ReaderUtils::GO_HOME_MS) {
    longPressBackHandled = true;
    mappedInput.suppressNextBackRelease();
    executeLongPressBackAction();
    return;
  }

  // Short press BACK goes directly to home
  if (!touch.prev && !touch.next && mappedInput.wasReleased(MappedInputManager::Button::Back) &&
      mappedInput.getHeldTime() < ReaderUtils::GO_HOME_MS) {
    onGoHome();
    return;
  }

  const bool sideLongPressSkipsChapter =
      SETTINGS.sideButtonLongPress == CrossPointSettings::SIDE_LONG_PRESS::SIDE_LONG_CHAPTER_SKIP;
  if (sideLongPressSkipsChapter) {
    const bool sidePrevReleased = mappedInput.wasReleased(MappedInputManager::Button::PageBack);
    const bool sideNextReleased = mappedInput.wasReleased(MappedInputManager::Button::PageForward);
    if (sideButtonLongPressHandled && (sidePrevReleased || sideNextReleased)) {
      sideButtonLongPressHandled = false;
      return;
    }

    const bool longPressReady = mappedInput.getHeldTime() > ReaderUtils::SKIP_HOLD_MS;
    const bool prevLongPressed = longPressReady && mappedInput.isPressed(MappedInputManager::Button::PageBack);
    const bool nextLongPressed = longPressReady && mappedInput.isPressed(MappedInputManager::Button::PageForward);
    if (!sideButtonLongPressHandled && (prevLongPressed || nextLongPressed)) {
      sideButtonLongPressHandled = true;

      bool goHome = false;
      bool needsUpdate = false;
      {
        RenderLock lock(*this);
        const uint32_t pageCount = xtc->getPageCount();
        if (currentPage >= pageCount) {
          if (nextLongPressed) {
            goHome = true;
          } else {
            currentPage = pageCount > 0 ? pageCount - 1 : 0;
            needsUpdate = true;
          }
        } else {
          uint32_t forwardReadSeconds = 0;
          const bool shouldRecordForwardRead =
              nextLongPressed && forwardPageReadElapsed(forwardReadSeconds, "side_long_press");
          recordCurrentPageReadingTime("side_long_press");
          if (prevLongPressed) {
            currentPage = currentPage >= 10 ? currentPage - 10 : 0;
          } else {
            currentPage += 10;
            if (currentPage >= pageCount) {
              currentPage = pageCount;
            }
            if (shouldRecordForwardRead) {
              recordForwardPageTurn(forwardReadSeconds, false);
            }
          }
          needsUpdate = true;
        }
      }
      if (goHome) {
        onGoHome();
        return;
      }
      if (needsUpdate) {
        requestUpdate();
      }
      return;
    }
  }

  // Side buttons fire on press only when long-press action is OFF.
  const bool sideUsePress = SETTINGS.sideButtonLongPress == CrossPointSettings::SIDE_LONG_PRESS::SIDE_LONG_OFF;

  const bool tiltNext = SETTINGS.tiltPageTurn && halTiltSensor.wasTiltedForward();
  const bool tiltPrev = SETTINGS.tiltPageTurn && halTiltSensor.wasTiltedBack();
  const bool sidePrev = sideUsePress ? mappedInput.wasPressed(MappedInputManager::Button::PageBack)
                                     : mappedInput.wasReleased(MappedInputManager::Button::PageBack);
  const bool sideNext = sideUsePress ? mappedInput.wasPressed(MappedInputManager::Button::PageForward)
                                     : mappedInput.wasReleased(MappedInputManager::Button::PageForward);
  const bool frontPrev = mappedInput.wasReleased(MappedInputManager::Button::Left);
  const bool powerReleased = mappedInput.wasReleased(MappedInputManager::Button::Power);
  if (powerReleased && longPowerPageTurnHandled) {
    longPowerPageTurnHandled = false;
    return;
  }
  if (powerReleased && mappedInput.getHeldTime() < SETTINGS.getPowerButtonLongPressDuration() &&
      executeReaderShortcutAction(static_cast<CrossPointSettings::SHORT_PWRBTN>(SETTINGS.shortPwrBtn))) {
    return;
  }
  if (!longPowerPageTurnHandled && mappedInput.isPressed(MappedInputManager::Button::Power) &&
      mappedInput.getHeldTime() >= SETTINGS.getPowerButtonLongPressDuration() &&
      executeReaderShortcutAction(static_cast<CrossPointSettings::SHORT_PWRBTN>(SETTINGS.longPwrBtn))) {
    longPowerPageTurnHandled = true;
    return;
  }

  const bool shortPowerTurn = SETTINGS.shortPwrBtn == CrossPointSettings::SHORT_PWRBTN::PAGE_TURN && powerReleased &&
                              mappedInput.getHeldTime() < SETTINGS.getPowerButtonLongPressDuration();
  const bool longPowerTurn = SETTINGS.longPwrBtn == CrossPointSettings::SHORT_PWRBTN::PAGE_TURN && powerReleased &&
                             mappedInput.getHeldTime() >= SETTINGS.getPowerButtonLongPressDuration();
  const bool timedLongPowerTurn = SETTINGS.longPwrBtn == CrossPointSettings::SHORT_PWRBTN::PAGE_TURN &&
                                  !longPowerPageTurnHandled &&
                                  mappedInput.isPressed(MappedInputManager::Button::Power) &&
                                  mappedInput.getHeldTime() >= SETTINGS.getPowerButtonLongPressDuration();
  if (timedLongPowerTurn) {
    longPowerPageTurnHandled = true;
  }
  const bool powerPageTurn = shortPowerTurn || longPowerTurn || timedLongPowerTurn;
  const bool frontNext = mappedInput.wasReleased(MappedInputManager::Button::Right) || powerPageTurn;

  const bool frontLongPressAction = SETTINGS.longPressButtonBehavior == CrossPointSettings::CHAPTER_SKIP ||
                                    SETTINGS.longPressButtonBehavior == CrossPointSettings::FONT_SIZE_CHANGE;
  if (frontLongPressAction) {
    const bool leftReleased = mappedInput.wasReleased(MappedInputManager::Button::Left);
    const bool rightReleased = mappedInput.wasReleased(MappedInputManager::Button::Right);
    if (frontButtonLongPressHandled && (leftReleased || rightReleased)) {
      frontButtonLongPressHandled = false;
      return;
    }

    const bool longPressReady = mappedInput.getHeldTime() > ReaderUtils::SKIP_HOLD_MS;
    const bool prevLongPressed = longPressReady && mappedInput.isPressed(MappedInputManager::Button::Left);
    const bool nextLongPressed = longPressReady && mappedInput.isPressed(MappedInputManager::Button::Right);
    if (!frontButtonLongPressHandled && (prevLongPressed || nextLongPressed)) {
      frontButtonLongPressHandled = true;
      if (SETTINGS.longPressButtonBehavior == CrossPointSettings::FONT_SIZE_CHANGE) {
        return;
      }

      bool goHome = false;
      bool needsUpdate = false;
      {
        RenderLock lock(*this);
        const uint32_t pageCount = xtc->getPageCount();
        if (currentPage >= pageCount) {
          if (nextLongPressed) {
            goHome = true;
          } else {
            currentPage = pageCount > 0 ? pageCount - 1 : 0;
            needsUpdate = true;
          }
        } else {
          uint32_t forwardReadSeconds = 0;
          const bool shouldRecordForwardRead =
              nextLongPressed && forwardPageReadElapsed(forwardReadSeconds, "front_long_press");
          recordCurrentPageReadingTime("front_long_press");
          if (prevLongPressed) {
            currentPage = currentPage >= 10 ? currentPage - 10 : 0;
          } else {
            currentPage += 10;
            if (currentPage >= pageCount) {
              currentPage = pageCount;
            }
            if (shouldRecordForwardRead) {
              recordForwardPageTurn(forwardReadSeconds, false);
            }
          }
          needsUpdate = true;
        }
      }
      if (goHome) {
        onGoHome();
        return;
      }
      if (needsUpdate) {
        requestUpdate();
      }
      return;
    }
  }

  const bool fromSideBtn = (sidePrev || sideNext) && !(frontPrev || frontNext);
  const bool fromTilt = tiltPrev || tiltNext;
  bool prevTriggered = tiltPrev || sidePrev || frontPrev;
  bool nextTriggered = tiltNext || sideNext || frontNext;
  prevTriggered = prevTriggered || touch.prev || shortcutPreviousPage;
  nextTriggered = nextTriggered || touch.next || shortcutPageTurn;

  if (!prevTriggered && !nextTriggered) {
    return;
  }

  // Touch page turns deliberately ignore the physical-button long-press
  // settings. Keep those saved settings intact for a later move back to a
  // button device, but never let a held screen tap skip pages.
  const bool fromTouch = touch.prev || touch.next;
  const unsigned long heldMs = fromTouch ? touch.heldMs : mappedInput.getHeldTime();

  // XTC pages are fixed-size bitmaps, so the orientation long-press action is
  // consumed here instead of rotating/clipping the pre-rendered page image.
  if (fromSideBtn &&
      SETTINGS.sideButtonLongPress == CrossPointSettings::SIDE_LONG_PRESS::SIDE_LONG_ORIENTATION_CHANGE &&
      heldMs > ReaderUtils::SKIP_HOLD_MS) {
    return;
  }

  // Mirror EPUB's manual-turn guard: the render task updates the panel
  // concurrently, so accepting another turn before it owns RenderLock can mix
  // two pages. The short time gap covers that request-to-render startup window.
  constexpr unsigned long kMinManualTurnGapMs = 200;
  const unsigned long now = millis();
  if (RenderLock::peek() || (now - lastPageTurnTime) < kMinManualTurnGapMs) {
    return;
  }
  lastPageTurnTime = now;

  const bool skipPages =
      !fromTouch && !fromTilt && !powerPageTurn && heldMs > ReaderUtils::SKIP_HOLD_MS &&
      (fromSideBtn ? SETTINGS.sideButtonLongPress == CrossPointSettings::SIDE_LONG_PRESS::SIDE_LONG_CHAPTER_SKIP
                   : SETTINGS.longPressButtonBehavior == CrossPointSettings::CHAPTER_SKIP);
  const int skipAmount = skipPages ? 10 : 1;

  bool goHome = false;
  bool needsUpdate = false;
  {
    RenderLock lock(*this);
    const uint32_t pageCount = xtc->getPageCount();
    // At end of the book with no suggestion menu, forward button goes home and back
    // button returns to last page.
    if (currentPage >= pageCount) {
      if (endOfBookOptions && endOfBookOptions->menuActive()) {
        // Selection movement was handled above; absorb leftover page-turn triggers so
        // e.g. "previous" at the top of the list doesn't jump back into the book.
        return;
      }
      if (nextTriggered) {
        goHome = true;
      } else {
        currentPage = pageCount > 0 ? pageCount - 1 : 0;
        needsUpdate = true;
      }
    } else if (prevTriggered) {
      recordCurrentPageReadingTime("page_back");
      if (currentPage >= static_cast<uint32_t>(skipAmount)) {
        currentPage -= skipAmount;
      } else {
        currentPage = 0;
      }
      needsUpdate = true;
    } else if (nextTriggered) {
      uint32_t forwardReadSeconds = 0;
      const bool shouldRecordForwardRead = forwardPageReadElapsed(forwardReadSeconds, "page_forward");
      recordCurrentPageReadingTime("page_forward");
      currentPage += skipAmount;
      if (currentPage >= pageCount) {
        currentPage = pageCount;  // Allow showing "End of book"
      }
      if (shouldRecordForwardRead) {
        recordForwardPageTurn(forwardReadSeconds, !skipPages);
      }
      needsUpdate = true;
    }
  }
  if (goHome) {
    onGoHome();
  } else if (needsUpdate) {
    requestUpdate();
  }
}

bool XtcReaderActivity::handleTwoFingerSwipeAction(const CrossPointSettings::TWO_FINGER_SWIPE_ACTION) {
  // XTC pages are pre-rendered images: they cannot be reflowed for font-size
  // changes, and the reader does not expose stable chapter jumps. Consume the
  // configured command without letting it turn into a regular page swipe.
  return true;
}

void XtcReaderActivity::toggleHomeButtonInReader() {
  if (!mappedInput.hasHomeKey()) return;
  SETTINGS.homeButtonInReaderEnabled = SETTINGS.homeButtonInReaderEnabled ? 0 : 1;
  if (!SETTINGS.saveToFile()) {
    LOG_ERR("XTR", "Failed to save Home button reader setting");
  }
  mappedInput.clearDeferredHomeGesture();
  drawToast(renderer, SETTINGS.homeButtonInReaderEnabled ? tr(STR_HOME_BUTTON_ENABLED) : tr(STR_HOME_BUTTON_DISABLED));
  delay(1000);
  requestUpdate();
}

void XtcReaderActivity::pauseReadingStatsTimer(const char* source) {
  recordCurrentPageReadingTime(source);
  pageShownAtMs = 0UL;
}

void XtcReaderActivity::resumeReadingStatsTimer(const char*) {
  if (xtc && currentPage < xtc->getPageCount()) {
    pageShownAtMs = millis();
  } else {
    pageShownAtMs = 0UL;
  }
}

void XtcReaderActivity::onInputLockChanged(const bool locked) {
  if (locked) {
    pauseReadingStatsTimer("quick_lock");
  } else {
    resumeReadingStatsTimer("quick_lock");
  }
}

bool XtcReaderActivity::handleQuickLockUnlock(const QuickLockTrigger trigger) {
  if (trigger == QuickLockTrigger::LongMenu) {
    if (longPressMenuHandled) {
      if (mappedInput.wasReleased(MappedInputManager::Button::Confirm) ||
          !mappedInput.isPressed(MappedInputManager::Button::Confirm)) {
        longPressMenuHandled = false;
      }
      return true;
    }
    if (SETTINGS.longPressMenuAction == CrossPointSettings::LONG_MENU_QUICK_LOCK &&
        mappedInput.isPressed(MappedInputManager::Button::Confirm) && mappedInput.getHeldTime() >= LONG_PRESS_MENU_MS) {
      longPressMenuHandled = true;
      mappedInput.suppressNextConfirmRelease();
      handleGlobalPowerButtonAction(CrossPointSettings::SHORT_PWRBTN::QUICK_LOCK, QuickLockTrigger::LongMenu);
      return true;
    }
    return false;
  }

  if (trigger == QuickLockTrigger::LongBack) {
    if (longPressBackHandled) {
      if (mappedInput.wasReleased(MappedInputManager::Button::Back) ||
          !mappedInput.isPressed(MappedInputManager::Button::Back)) {
        longPressBackHandled = false;
      }
      return true;
    }
    if (SETTINGS.longPressBackAction == CrossPointSettings::LONG_MENU_QUICK_LOCK &&
        mappedInput.isPressed(MappedInputManager::Button::Back) &&
        mappedInput.getHeldTime() >= ReaderUtils::GO_HOME_MS) {
      longPressBackHandled = true;
      mappedInput.suppressNextBackRelease();
      handleGlobalPowerButtonAction(CrossPointSettings::SHORT_PWRBTN::QUICK_LOCK, QuickLockTrigger::LongBack);
      return true;
    }
    return false;
  }

  return false;
}

bool XtcReaderActivity::currentPageReadingSecondsForStats(uint32_t& seconds, const char* source) const {
  seconds = 0;
  if (!SETTINGS.shouldTrackReadingStats() || pageShownAtMs == 0UL) {
    return false;
  }

  const unsigned long elapsedMs = millis() - pageShownAtMs;
  const uint32_t elapsedSeconds = static_cast<uint32_t>(elapsedMs / 1000UL);
  if (elapsedSeconds == 0) {
    return false;
  }

  const uint32_t thresholdSeconds = SETTINGS.getReadingIdleTimeThresholdSeconds();
  if (elapsedSeconds > thresholdSeconds) {
    return false;
  }

  seconds = elapsedSeconds;
  return true;
}

bool XtcReaderActivity::forwardPageReadElapsed(uint32_t& seconds, const char*) const {
  seconds = 0;
  if (!SETTINGS.shouldTrackReadingStats() || pageShownAtMs == 0UL) {
    return false;
  }

  const unsigned long elapsedMs = millis() - pageShownAtMs;
  if (elapsedMs < MIN_READING_STATS_PAGE_MS) {
    return false;
  }

  const uint32_t elapsedSeconds = static_cast<uint32_t>(elapsedMs / 1000UL);
  if (elapsedSeconds > SETTINGS.getReadingIdleTimeThresholdSeconds()) {
    return false;
  }

  seconds = elapsedSeconds;
  return true;
}

void XtcReaderActivity::recordCurrentPageReadingTime(const char* source) {
  uint32_t seconds = 0;
  if (currentPageReadingSecondsForStats(seconds, source)) {
    sessionReadingSeconds = sessionReadingSeconds > UINT32_MAX - seconds ? UINT32_MAX : sessionReadingSeconds + seconds;
  }
  pageShownAtMs = 0UL;
}

void XtcReaderActivity::recordForwardPageTurn(const uint32_t seconds, const bool recordPace) {
  if (recordPace) {
    stats.recordForwardPageRead(seconds);
  }
  stats.totalPagesTurned++;
  globalStats.totalPagesTurned++;
}

bool XtcReaderActivity::formatTimeLeftLabel(char* buf, const size_t len, const uint32_t pageToRender) const {
  if (!buf || len == 0 || !xtc ||
      SETTINGS.statusBarTimeLeft == CrossPointSettings::STATUS_BAR_TIME_LEFT::TIME_LEFT_HIDE) {
    return false;
  }

  const bool bookEstimate = SETTINGS.statusBarTimeLeft == CrossPointSettings::STATUS_BAR_TIME_LEFT::TIME_LEFT_BOOK;
  const auto pageInfo = getStatusBarInfo(pageToRender);
  const uint32_t current = bookEstimate ? pageToRender + 1U : static_cast<uint32_t>(pageInfo.currentPage);
  const uint32_t total = bookEstimate ? xtc->getPageCount() : static_cast<uint32_t>(pageInfo.pageCount);
  if (current >= total) {
    return false;
  }

  if (stats.avgSecondsPerForwardPage == 0 || stats.paceSampleCount < MIN_TIME_LEFT_PACE_SAMPLE_COUNT) {
    snprintf(buf, len, "%s", tr(STR_TIME_LEFT_CALCULATING));
    return true;
  }

  const uint64_t estimatedSeconds =
      static_cast<uint64_t>(total - current) * static_cast<uint64_t>(stats.avgSecondsPerForwardPage);
  formatCompactReadingDuration(static_cast<uint32_t>(std::min<uint64_t>(estimatedSeconds, UINT32_MAX)), buf, len);
  return true;
}

void XtcReaderActivity::commitReadingStats() {
  if (!xtc || !SETTINGS.shouldTrackReadingStats()) {
    return;
  }

  recordCurrentPageReadingTime("reader_exit");
  const uint32_t elapsedSecs = sessionReadingSeconds;
  if (elapsedSecs >= 60) {
    stats.sessionCount++;
    globalStats.totalSessions++;
  }
  if (elapsedSecs >= 10) {
    stats.totalReadingSeconds += elapsedSecs;
    globalStats.totalReadingSeconds += elapsedSecs;
    if (hasSessionStartLocalDateTime) {
      stats.recordReadingSpan(sessionStartLocalDateTime, elapsedSecs);
      globalStats.recordReadingSpan(sessionStartLocalDateTime, elapsedSecs);
    }
    if (elapsedSecs >= 120 && !stats.startDateManual && !stats.startDate.isValid() && hasSessionStartLocalDateTime) {
      stats.startDate = sessionStartLocalDateTime.date;
    }
  }
  stats.save(xtc->getCachePath());
  globalStats.save();
}

void XtcReaderActivity::resetCurrentBookStatsAfterDelete() {
  stats = BookReadingStats{};
  sessionReadingSeconds = 0;
  hasSessionStartLocalDateTime = getCurrentLocalReadingStatsDateTime(sessionStartLocalDateTime);
}

void XtcReaderActivity::setBookCompleted(const bool isCompleted) {
  if (!xtc || stats.isCompleted == isCompleted) {
    return;
  }

  stats.isCompleted = isCompleted;
  if (isCompleted && !stats.finishedDateManual) {
    ReadingStatsDateTime now;
    if (getCurrentLocalReadingStatsDateTime(now)) {
      stats.finishedDate = now.date;
    }
  }

  if (isCompleted) {
    globalStats.completedBooks++;
  } else if (globalStats.completedBooks > 0) {
    globalStats.completedBooks--;
  }

  stats.save(xtc->getCachePath());
  globalStats.save();
}

float XtcReaderActivity::getCurrentBookProgressPercent() const {
  if (!xtc || xtc->getPageCount() == 0) {
    return -1.0f;
  }
  const uint32_t pageCount = xtc->getPageCount();
  const uint32_t clampedPage = currentPage >= pageCount ? pageCount - 1 : currentPage;
  return static_cast<float>(xtc->calculateProgress(clampedPage));
}

void XtcReaderActivity::openChapterSelection() {
  uint32_t pageToSelect = 0;
  bool hasChapters = false;
  {
    RenderLock lock(*this);
    if (xtc) {
      hasChapters = xtc->hasChapters() && xtc->getChapterCount() > 0;
      pageToSelect = currentPage;
    }
  }
  if (!hasChapters) {
    resumeReadingStatsTimer("chapter_selection_unavailable");
    requestUpdate();
    return;
  }

  startActivityForResult(std::make_unique<XtcReaderChapterSelectionActivity>(renderer, mappedInput, xtc, pageToSelect),
                         [this](const ActivityResult& result) {
                           if (!result.isCancelled) {
                             RenderLock lock(*this);
                             currentPage = std::get<PageResult>(result.data).page;
                           }
                           resumeReadingStatsTimer("chapter_selection_return");
                           requestUpdate();
                         });
}

void XtcReaderActivity::openReadingStats() {
  if (!xtc) {
    resumeReadingStatsTimer("book_stats_no_book");
    requestUpdate();
    return;
  }

  BookReadingStats displayStats = stats;
  if (SETTINGS.shouldTrackReadingStats()) {
    displayStats.totalReadingSeconds = displayStats.totalReadingSeconds > UINT32_MAX - sessionReadingSeconds
                                           ? UINT32_MAX
                                           : displayStats.totalReadingSeconds + sessionReadingSeconds;
    uint32_t currentPageSeconds = 0;
    if (currentPageReadingSecondsForStats(currentPageSeconds, "book_stats_preview")) {
      displayStats.totalReadingSeconds = displayStats.totalReadingSeconds > UINT32_MAX - currentPageSeconds
                                             ? UINT32_MAX
                                             : displayStats.totalReadingSeconds + currentPageSeconds;
    }
  }

  const bool hasSyncedStats = GlobalReadingStats::hasSyncedStats();
  const GlobalReadingStats displayAllDevicesStats =
      hasSyncedStats ? GlobalReadingStats::loadAggregated(globalStats) : GlobalReadingStats{};
  if (hasSyncedStats) {
    startActivityForResult(std::make_unique<BookStatsActivity>(
                               renderer, mappedInput, xtc->getTitle(), xtc->getCachePath(), displayStats,
                               getCurrentBookProgressPercent(), false, 0, globalStats, displayAllDevicesStats),
                           [this](const ActivityResult&) {
                             if (xtc) {
                               stats = BookReadingStats::load(xtc->getCachePath());
                             }
                             globalStats = GlobalReadingStats::load();
                             resumeReadingStatsTimer("book_stats_return");
                             requestUpdate();
                           });
  } else {
    startActivityForResult(
        std::make_unique<BookStatsActivity>(renderer, mappedInput, xtc->getTitle(), xtc->getCachePath(), displayStats,
                                            getCurrentBookProgressPercent(), false, 0, globalStats),
        [this](const ActivityResult&) {
          if (xtc) {
            stats = BookReadingStats::load(xtc->getCachePath());
          }
          globalStats = GlobalReadingStats::load();
          resumeReadingStatsTimer("book_stats_return");
          requestUpdate();
        });
  }
}

void XtcReaderActivity::deleteBookStats() {
  startActivityForResult(
      std::make_unique<ConfirmationActivity>(renderer, mappedInput, confirmationHeading(StrId::STR_DELETE_BOOK_STATS),
                                             xtc ? xtc->getTitle() : std::string{}),
      [this](const ActivityResult& result) {
        if (!result.isCancelled && xtc) {
          bool statsDeleted = false;
          {
            RenderLock lock(*this);
            statsDeleted = BookReadingStats::remove(xtc->getCachePath());
            if (statsDeleted) {
              resetCurrentBookStatsAfterDelete();
            }
          }
          if (statsDeleted) {
            drawToast(renderer, tr(STR_BOOK_STATS_DELETED));
            delay(1000);
          } else {
            LOG_ERR("XTR", "Failed to delete book stats");
          }
        }
        resumeReadingStatsTimer("delete_stats_return");
        requestUpdate();
      });
}

void XtcReaderActivity::deleteBookCache() {
  startActivityForResult(
      std::make_unique<ConfirmationActivity>(renderer, mappedInput, confirmationHeading(StrId::STR_DELETE_CACHE),
                                             xtc ? xtc->getTitle() : std::string{}, false, true),
      [this](const ActivityResult& result) {
        if (!result.isCancelled && xtc) {
          bool cacheDeleted = false;
          {
            RenderLock lock(*this);
            stats.save(xtc->getCachePath());
            cacheDeleted = clearBookCachePreservingUserState(xtc->getPath());
            xtc->setupCacheDir();
            stats.save(xtc->getCachePath());
          }
          if (cacheDeleted) {
            drawToast(renderer, tr(STR_BOOK_CACHE_DELETED));
            delay(1000);
          } else {
            LOG_ERR("XTR", "Failed to delete book cache");
          }
        }
        resumeReadingStatsTimer("delete_cache_return");
        requestUpdate();
      });
}

void XtcReaderActivity::onReaderMenuConfirm(const int action) {
  switch (static_cast<XtcReaderMenuActivity::MenuAction>(action)) {
    case XtcReaderMenuActivity::MenuAction::SELECT_CHAPTER:
      openChapterSelection();
      break;
    case XtcReaderMenuActivity::MenuAction::READING_STATS:
      openReadingStats();
      break;
    case XtcReaderMenuActivity::MenuAction::TOGGLE_COMPLETED:
      setBookCompleted(!stats.isCompleted);
      resumeReadingStatsTimer("toggle_completed_return");
      requestUpdate();
      break;
    case XtcReaderMenuActivity::MenuAction::DELETE_STATS:
      deleteBookStats();
      break;
    case XtcReaderMenuActivity::MenuAction::DELETE_CACHE:
      deleteBookCache();
      break;
    case XtcReaderMenuActivity::MenuAction::SEND_NEARBY_BOOK:
      saveProgress(currentPage);
      activityManager.goToNearbyBookSend(xtc ? xtc->getPath() : std::string{}, true);
      return;
    case XtcReaderMenuActivity::MenuAction::DISABLE_TOUCHSCREEN:
      break;
  }
}

bool XtcReaderActivity::supportsQuickAction(const CrossPointSettings::SHORT_PWRBTN action) {
  switch (action) {
    case CrossPointSettings::SHORT_PWRBTN::PREVIOUS_PAGE:
    case CrossPointSettings::SHORT_PWRBTN::SLEEP:
    case CrossPointSettings::SHORT_PWRBTN::FORCE_REFRESH:
    case CrossPointSettings::SHORT_PWRBTN::FILE_TRANSFER:
    case CrossPointSettings::SHORT_PWRBTN::CALIBRE_WIRELESS:
    case CrossPointSettings::SHORT_PWRBTN::JOIN_NETWORK:
    case CrossPointSettings::SHORT_PWRBTN::CREATE_HOTSPOT:
    case CrossPointSettings::SHORT_PWRBTN::FILE_BROWSER:
    case CrossPointSettings::SHORT_PWRBTN::TOGGLE_FRONTLIGHT:
    case CrossPointSettings::SHORT_PWRBTN::TOGGLE_TOUCHSCREEN:
      return true;
    default:
      return false;
  }
}

bool XtcReaderActivity::executeReaderShortcutAction(const CrossPointSettings::SHORT_PWRBTN action) {
  switch (action) {
    case CrossPointSettings::SHORT_PWRBTN::PAGE_TURN:
      shortcutPageTurnPending = true;
      return true;
    case CrossPointSettings::SHORT_PWRBTN::PREVIOUS_PAGE:
      shortcutPreviousPagePending = true;
      return true;
    case CrossPointSettings::SHORT_PWRBTN::FILE_TRANSFER:
      activityManager.goToFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::SHORT_PWRBTN::CALIBRE_WIRELESS:
      activityManager.goToCalibreWireless(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::SHORT_PWRBTN::JOIN_NETWORK:
      activityManager.goToJoinNetworkFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::SHORT_PWRBTN::CREATE_HOTSPOT:
      activityManager.goToHotspotFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::SHORT_PWRBTN::FILE_BROWSER:
      activityManager.goToFileBrowser(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::SHORT_PWRBTN::TOGGLE_HOME_BUTTON_IN_READER:
      toggleHomeButtonInReader();
      return true;
    case CrossPointSettings::SHORT_PWRBTN::TOGGLE_FRONTLIGHT:
    case CrossPointSettings::SHORT_PWRBTN::TOGGLE_TOUCHSCREEN:
      return handleGlobalPowerButtonAction(action);
    default:
      return false;
  }
}

bool XtcReaderActivity::executeLongPressBackAction() {
  switch (static_cast<CrossPointSettings::LONG_PRESS_MENU_ACTION>(SETTINGS.longPressBackAction)) {
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_SLEEP:
      enterDeepSleep();
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_REFRESH_SCREEN:
      prepareManualRefresh();
      requestUpdate();
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_FILE_TRANSFER:
      activityManager.goToFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_CALIBRE_WIRELESS:
      activityManager.goToCalibreWireless(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_JOIN_NETWORK:
      activityManager.goToJoinNetworkFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_CREATE_HOTSPOT:
      activityManager.goToHotspotFileTransfer(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_FILE_BROWSER:
      activityManager.goToFileBrowser(xtc ? xtc->getPath() : "");
      return true;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_CREATE_CLIPPING:
      return false;
    case CrossPointSettings::LONG_PRESS_MENU_ACTION::LONG_MENU_QUICK_LOCK:
      return handleGlobalPowerButtonAction(CrossPointSettings::SHORT_PWRBTN::QUICK_LOCK, QuickLockTrigger::LongBack);
    default:
      return false;
  }
}

bool XtcReaderActivity::handleShortcutAction(const CrossPointSettings::SHORT_PWRBTN action) {
  if (action == CrossPointSettings::SHORT_PWRBTN::QUICK_ACTIONS) {
    QuickActions::showConfiguredPopup(
        quickActionsPopup, [this] { requestUpdate(); },
        [this](const auto quickAction) {
          mappedInput.setReaderTouchscreenOverride(false);
          dispatchShortcutAction(quickAction);
        },
        [](const auto quickAction) { return supportsQuickAction(quickAction); });
    if (quickActionsPopup.isActive()) {
      mappedInput.setReaderTouchscreenOverride(true);
      quickActionsPopup.setCancelCallback([this] { mappedInput.setReaderTouchscreenOverride(false); });
    }
    return true;
  }
  return executeReaderShortcutAction(action);
}

void XtcReaderActivity::render(RenderLock&&) {
  if (!xtc) {
    return;
  }
  if (quickActionsPopup.processRender(renderer, mappedInput)) {
    return;
  }

  const uint32_t pageToRender = currentPage;
  if (pageToRender >= xtc->getPageCount()) {
    // This is the sole creation and load site: its app and theme tokens are
    // absent during normal reading and allocation failure leaves an empty end screen.
    if (!endOfBookOptions) {
      endOfBookOptions = makeUniqueNoThrow<EndOfBookOptions>(renderer);
      if (!endOfBookOptions) {
        LOG_ERR("XTR", "OOM: EndOfBookOptions (%u bytes)", static_cast<unsigned>(sizeof(EndOfBookOptions)));
      }
    }
    renderer.clearScreen();
    if (endOfBookOptions) {
      endOfBookOptions->loadOnce(xtc->getPath());
      endOfBookOptions->render(renderer, mappedInput);
    }
    renderer.displayBuffer();
    return;
  }

  renderPage(pageToRender);
  pageShownAtMs = millis();
  if (!queueProgressSave(pageToRender)) {
    LOG_ERR("XTR", "Failed to save debounced reader progress");
  }
}

XtcReaderActivity::StatusBarInfo XtcReaderActivity::getStatusBarInfo(const uint32_t pageToRender) const {
  const auto statusBar = SETTINGS.statusBarSpec();
  const int bookPageCount = static_cast<int>(xtc->getPageCount());
  const int bookPage = static_cast<int>(pageToRender) + 1;
  std::string title =
      SETTINGS.statusBarTitle == CrossPointSettings::STATUS_BAR_TITLE::BOOK_TITLE ? xtc->getTitle() : "";

  if (!xtc->hasChapters()) {
    return StatusBarInfo{bookPage, bookPageCount, std::move(title)};
  }

  xtc::ChapterInfo chapter{};
  if (!xtc->getChapterForPage(pageToRender, chapter) || chapter.endPage < chapter.startPage) {
    return StatusBarInfo{bookPage, bookPageCount, std::move(title)};
  }

  if (statusBar.titleMode == CrossPointSettings::STATUS_BAR_TITLE::CHAPTER_TITLE) {
    title = chapter.name[0] == '\0' ? tr(STR_UNNAMED) : chapter.name;
  }

  return StatusBarInfo{static_cast<int>(pageToRender - chapter.startPage) + 1,
                       static_cast<int>(chapter.endPage - chapter.startPage) + 1, std::move(title)};
}

void XtcReaderActivity::renderStatusBarOverlay(const StatusBarOverlayPosition position,
                                               const uint32_t pageToRender) const {
  const bool drawBottom = SETTINGS.xtcStatusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_BOTTOM &&
                          position == StatusBarOverlayPosition::Bottom;
  const bool drawTop = SETTINGS.xtcStatusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_TOP &&
                       position == StatusBarOverlayPosition::Top;
  if (!drawBottom && !drawTop) {
    return;
  }

  const int statusBarHeight = UITheme::getInstance().getStatusBarHeight();
  if (statusBarHeight <= 0) {
    return;
  }

  int orientedMarginTop, orientedMarginRight, orientedMarginBottom, orientedMarginLeft;
  renderer.getOrientedViewableTRBL(&orientedMarginTop, &orientedMarginRight, &orientedMarginBottom,
                                   &orientedMarginLeft);

  int clearY;
  int paddingBottom = 0;
  if (position == StatusBarOverlayPosition::Bottom) {
    clearY = renderer.getScreenHeight() - orientedMarginBottom - statusBarHeight - 4;
    if (clearY < 0) {
      clearY = 0;
    }
  } else {
    clearY = orientedMarginTop;
    paddingBottom = renderer.getScreenHeight() - statusBarHeight - orientedMarginBottom - orientedMarginTop - 4;
  }
  const int clearHeight = position == StatusBarOverlayPosition::Bottom
                              ? renderer.getScreenHeight() - orientedMarginBottom - clearY
                              : statusBarHeight + 4;
  if (clearHeight > 0) {
    renderer.fillRect(0, clearY, renderer.getScreenWidth(), clearHeight, false);
  }

  // XTC pages already contain a status strip in their bitmap. Clear that same
  // overlay area before returning so hiding it does not leave stale pixels.
  if (!statusBarVisible) {
    return;
  }

  const int pageCount = static_cast<int>(xtc->getPageCount());
  const int displayPage = static_cast<int>(pageToRender) + 1;
  const float progress = pageCount > 0 ? (static_cast<float>(displayPage) * 100.0f) / pageCount : 0.0f;
  const auto pageInfo = getStatusBarInfo(pageToRender);
  char timeLeftLabel[24] = {};
  const char* timeLeft =
      formatTimeLeftLabel(timeLeftLabel, sizeof(timeLeftLabel), pageToRender) ? timeLeftLabel : nullptr;
  GUI.drawStatusBar(renderer, progress, pageInfo.currentPage, pageInfo.pageCount, pageInfo.title.c_str(), paddingBottom,
                    0, false, timeLeft);
}

void XtcReaderActivity::renderPage(const uint32_t pageToRender) {
  const uint16_t pageWidth = xtc->getPageWidth();
  const uint16_t pageHeight = xtc->getPageHeight();
  const uint8_t bitDepth = xtc->getBitDepth();
  const bool midRes15x = isXtcMidRes15x(pageWidth, pageHeight, renderer);
  const bool hiRes2x = isXtcHiRes2x(pageWidth, pageHeight, renderer);
  const bool scaledSource = midRes15x || hiRes2x;

  auto showLoadError = [&](const bool memoryError) {
    renderer.clearScreen();
    renderer.drawCenteredText(UI_12_FONT_ID, 300, memoryError ? tr(STR_MEMORY_ERROR) : tr(STR_PAGE_LOAD_ERROR), true,
                              EpdFontFamily::BOLD);
    renderer.displayBuffer();
  };

  auto displayFastOrCadence = [&]() {
    if (zoomRefreshPending) {
      renderer.displayBuffer(HalDisplay::FAST_REFRESH);
      zoomRefreshPending = false;
    } else {
      ReaderUtils::displayWithRefreshCycle(renderer, pagesUntilFullRefresh);
    }
  };

  if ((bitDepth == 2 || scaledSource) && sourcePageBuffer && sourcePageBufferSize > 0) {
    const size_t expectedSize = xtcBitmapSize(bitDepth, pageWidth, pageHeight);
    if (expectedSize > sourcePageBufferSize) {
      LOG_ERR("XTR", "XTC source page exceeds cache: need=%lu have=%lu", static_cast<unsigned long>(expectedSize),
              static_cast<unsigned long>(sourcePageBufferSize));
      showLoadError(true);
      return;
    }

    if (sourceBufferedPage != pageToRender) {
      const size_t bytesRead = xtc->loadPage(pageToRender, sourcePageBuffer.get(), sourcePageBufferSize);
      if (bytesRead != expectedSize) {
        sourceBufferedPage = UINT32_MAX;
        LOG_ERR("XTR", "Failed to load cached XTC page %lu: expected=%lu got=%lu error=%s", pageToRender,
                static_cast<unsigned long>(expectedSize), static_cast<unsigned long>(bytesRead),
                xtc::errorToString(xtc->getLastError()));
        showLoadError(false);
        return;
      }
      sourceBufferedPage = pageToRender;
    }

    renderer.clearScreen();
    if (bitDepth == 2) {
      if (hiRes2x) {
        if (zoomActive) {
          const XtcZoomViewport viewport =
              makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
          drawXtchHiResZoom(sourcePageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
        } else {
          drawXtchHiResNormal(sourcePageBuffer.get(), pageWidth, pageHeight, renderer);
        }
      } else if (midRes15x) {
        if (zoomActive) {
          const XtcZoomViewport viewport =
              makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
          drawXtchMidResZoom(sourcePageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
        } else {
          drawXtchMidResNormal(sourcePageBuffer.get(), pageWidth, pageHeight, renderer);
        }
      } else if (zoomActive) {
        const XtcZoomViewport viewport =
            makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
        drawXtchLite2x(sourcePageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
      } else {
        drawXtchFast1x(sourcePageBuffer.get(), pageWidth, pageHeight, renderer);
      }
    } else {
      if (hiRes2x) {
        if (zoomActive) {
          const XtcZoomViewport viewport =
              makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
          drawXtcHiResZoom(sourcePageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
        } else {
          drawXtcHiResNormal(sourcePageBuffer.get(), pageWidth, pageHeight, renderer);
        }
      } else if (midRes15x) {
        if (zoomActive) {
          const XtcZoomViewport viewport =
              makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
          drawXtcMidResZoom(sourcePageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
        } else {
          drawXtcMidResNormal(sourcePageBuffer.get(), pageWidth, pageHeight, renderer);
        }
      }
    }

    if (SETTINGS.xtcStatusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_TOP) {
      renderStatusBarOverlay(StatusBarOverlayPosition::Top, pageToRender);
    } else {
      renderStatusBarOverlay(StatusBarOverlayPosition::Bottom, pageToRender);
    }
    displayFastOrCadence();
    return;
  }

  if (scaledSource) {
    LOG_ERR("XTR", "Scaled XTC page requires PSRAM source cache (%ux%u %u-bit)", pageWidth, pageHeight, bitDepth);
    showLoadError(true);
    return;
  }

  if (bitDepth == 2) {
    auto showStreamError = [&]() {
      renderer.clearScreen();
      const char* message =
          xtc->getLastError() == xtc::XtcError::MEMORY_ERROR ? tr(STR_MEMORY_ERROR) : tr(STR_PAGE_LOAD_ERROR);
      renderer.drawCenteredText(UI_12_FONT_ID, 300, message, true, EpdFontFamily::BOLD);
      renderer.displayBuffer();
    };
    const auto clearHiddenStatusBar = [this, pageToRender] {
      if (statusBarVisible) return;
      if (SETTINGS.xtcStatusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_TOP) {
        renderStatusBarOverlay(StatusBarOverlayPosition::Top, pageToRender);
      } else {
        renderStatusBarOverlay(StatusBarOverlayPosition::Bottom, pageToRender);
      }
    };

    renderer.clearScreen();
    if (!streamXtchRenderPass(*xtc, pageToRender, pageWidth, pageHeight, renderer, XtchRenderPass::Base)) {
      showStreamError();
      return;
    }
    clearHiddenStatusBar();

    if (pagesUntilFullRefresh <= 1) {
      renderer.displayBuffer(pagesUntilFullRefresh < 0 ? manualScreenRefreshMode() : HalDisplay::HALF_REFRESH);
      renderer.preconditionGrayscale();
      pagesUntilFullRefresh = SETTINGS.getRefreshFrequency();
    } else {
      renderer.displayGrayscaleBase(HalDisplay::FAST_REFRESH);
      pagesUntilFullRefresh--;
    }

    renderer.clearScreen(0x00);
    if (!streamXtchRenderPass(*xtc, pageToRender, pageWidth, pageHeight, renderer, XtchRenderPass::Lsb)) {
      showStreamError();
      return;
    }
    clearHiddenStatusBar();
    renderer.copyGrayscaleLsbBuffers();

    renderer.clearScreen(0x00);
    if (!streamXtchRenderPass(*xtc, pageToRender, pageWidth, pageHeight, renderer, XtchRenderPass::Msb)) {
      showStreamError();
      return;
    }
    clearHiddenStatusBar();
    renderer.copyGrayscaleMsbBuffers();
    renderer.displayGrayBuffer();

    renderer.clearScreen();
    if (!streamXtchRenderPass(*xtc, pageToRender, pageWidth, pageHeight, renderer, XtchRenderPass::Base)) {
      showStreamError();
      return;
    }
    clearHiddenStatusBar();
    renderer.cleanupGrayscaleWithFrameBuffer();
    return;
  }

  const size_t pageBufferSize = xtcBitmapSize(bitDepth, pageWidth, pageHeight);
  auto pageBuffer = makeUniqueNoThrow<uint8_t[]>(pageBufferSize);
  if (!pageBuffer) {
    LOG_ERR("XTR", "Failed to allocate XTC page buffer (%lu bytes)", static_cast<unsigned long>(pageBufferSize));
    showLoadError(true);
    return;
  }

  const size_t bytesRead = xtc->loadPage(pageToRender, pageBuffer.get(), pageBufferSize);
  if (bytesRead != pageBufferSize) {
    LOG_ERR("XTR", "Failed to load page %lu: expected=%lu got=%lu error=%s", pageToRender,
            static_cast<unsigned long>(pageBufferSize), static_cast<unsigned long>(bytesRead),
            xtc::errorToString(xtc->getLastError()));
    showLoadError(false);
    return;
  }

  renderer.clearScreen();
  const size_t srcRowBytes = (pageWidth + 7) / 8;
  if (zoomActive) {
    const XtcZoomViewport viewport =
        makeXtcZoomViewport(pageWidth, pageHeight, renderer, zoomCenterX, zoomCenterY);
    drawXtcEpx2x(pageBuffer.get(), pageWidth, pageHeight, viewport, renderer);
  } else {
    for (uint16_t y = 0; y < pageHeight; ++y) {
      const size_t row = static_cast<size_t>(y) * srcRowBytes;
      for (uint16_t x = 0; x < pageWidth; ++x) {
        if (!((pageBuffer[row + x / 8] >> (7 - (x & 7))) & 1)) renderer.drawPixel(x, y, true);
      }
    }
  }

  if (SETTINGS.xtcStatusBarMode == CrossPointSettings::XTC_STATUS_BAR_MODE::XTC_STATUS_BAR_TOP) {
    renderStatusBarOverlay(StatusBarOverlayPosition::Top, pageToRender);
  } else {
    renderStatusBarOverlay(StatusBarOverlayPosition::Bottom, pageToRender);
  }
  displayFastOrCadence();
}

bool XtcReaderActivity::saveProgress(const uint32_t page) {
  if (!xtc) {
    return false;
  }
  HalFile f;
  if (!Storage.openFileForWrite("XTR", xtc->getCachePath() + "/progress.bin", f)) {
    return false;
  }
  uint8_t data[4];
  data[0] = page & 0xFF;
  data[1] = (page >> 8) & 0xFF;
  data[2] = (page >> 16) & 0xFF;
  data[3] = (page >> 24) & 0xFF;
  const bool written = f.write(data, sizeof(data)) == sizeof(data);
  f.close();
  if (!written) {
    LOG_ERR("XTR", "Short write saving reader progress");
    return false;
  }
  progressSaveDebouncer.markPersisted(page);
  return true;
}

bool XtcReaderActivity::queueProgressSave(const uint32_t pageToRender) {
  if (!progressSaveDebouncer.observe(pageToRender)) {
    return true;
  }
  return saveProgress(pageToRender);
}

bool XtcReaderActivity::flushQueuedProgress() {
  return !progressSaveDebouncer.hasPending() || saveProgress(progressSaveDebouncer.lastObservedPosition());
}

void XtcReaderActivity::loadProgress() {
  HalFile f;
  if (Storage.openFileForRead("XTR", xtc->getCachePath() + "/progress.bin", f)) {
    uint8_t data[4];
    if (f.read(data, 4) == 4) {
      currentPage = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24);

      // Validate page number
      if (currentPage >= xtc->getPageCount()) {
        currentPage = 0;
      }
    }
    f.close();
  }
}

bool XtcReaderActivity::drawCurrentPageToBuffer(const std::string& filePath, GfxRenderer& renderer) {
  Xtc xtc(filePath, "/.crosspoint");
  if (!xtc.load()) {
    LOG_DBG("SLP", "XTC: failed to load %s", filePath.c_str());
    return false;
  }

  uint32_t savedPage = 0;
  FsFile f;
  if (Storage.openFileForRead("SLP", xtc.getCachePath() + "/progress.bin", f)) {
    uint8_t data[4];
    if (f.read(data, 4) == 4) {
      savedPage = (uint32_t)data[0] | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
    }
    f.close();
  }
  if (savedPage >= xtc.getPageCount()) savedPage = 0;

  const uint16_t pageWidth = xtc.getPageWidth();
  const uint16_t pageHeight = xtc.getPageHeight();
  const uint8_t bitDepth = xtc.getBitDepth();
  const bool midRes15x = isXtcMidRes15x(pageWidth, pageHeight, renderer);
  const bool hiRes2x = isXtcHiRes2x(pageWidth, pageHeight, renderer);
  const size_t pageBufferSize = xtcBitmapSize(bitDepth, pageWidth, pageHeight);

  // Sleep snapshots may need up to ~384 KB for a 960x1600 XTCH page. Prefer
  // PSRAM when available; otherwise fail cleanly rather than risking the stack
  // or silently cropping the high-resolution source.
  HeapByteBuffer pageBuffer =
      psramHeapAvailable() && pageBufferSize > renderer.getBufferSize()
          ? makePsramByteBufferNoThrow(pageBufferSize)
          : makeHeapByteBufferNoThrow(pageBufferSize);
  if (!pageBuffer) {
    LOG_ERR("SLP", "XTC: failed to allocate page buffer (%lu bytes)", static_cast<unsigned long>(pageBufferSize));
    return false;
  }

  const size_t bytesRead = xtc.loadPage(savedPage, pageBuffer.get(), pageBufferSize);
  if (bytesRead != pageBufferSize) {
    LOG_ERR("SLP", "XTC: failed to load page %lu: expected=%lu got=%lu", savedPage,
            static_cast<unsigned long>(pageBufferSize), static_cast<unsigned long>(bytesRead));
    return false;
  }

  renderer.clearScreen();

  if (hiRes2x) {
    if (bitDepth == 2) {
      drawXtchHiResNormal(pageBuffer.get(), pageWidth, pageHeight, renderer);
    } else {
      drawXtcHiResNormal(pageBuffer.get(), pageWidth, pageHeight, renderer);
    }
    return true;
  }
  if (midRes15x) {
    if (bitDepth == 2) {
      drawXtchMidResNormal(pageBuffer.get(), pageWidth, pageHeight, renderer);
    } else {
      drawXtcMidResNormal(pageBuffer.get(), pageWidth, pageHeight, renderer);
    }
    return true;
  }

  if (bitDepth == 2) {
    // Match the reader's fast 1-bit representation for a sleep-overlay base.
    drawXtchFast1x(pageBuffer.get(), pageWidth, pageHeight, renderer);
    return true;
  }

  const size_t srcRowBytes = (pageWidth + 7) / 8;
  for (uint16_t y = 0; y < pageHeight; ++y) {
    const size_t row = static_cast<size_t>(y) * srcRowBytes;
    for (uint16_t x = 0; x < pageWidth; ++x) {
      if (!((pageBuffer[row + x / 8] >> (7 - (x & 7))) & 1)) renderer.drawPixel(x, y, true);
    }
  }
  return true;
}

ScreenshotInfo XtcReaderActivity::getScreenshotInfo() const {
  ScreenshotInfo info;
  info.readerType = ScreenshotInfo::ReaderType::Xtc;
  if (xtc) {
    const std::string t = xtc->getTitle();
    snprintf(info.title, sizeof(info.title), "%s", t.c_str());
    const uint32_t pageCount = xtc->getPageCount();
    info.totalPages = pageCount;
    // Clamp to last valid page to avoid sentinel value (currentPage == pageCount)
    uint32_t clampedPage = (pageCount > 0 && currentPage >= pageCount) ? pageCount - 1 : currentPage;
    info.progressPercent = pageCount > 0 ? xtc->calculateProgress(clampedPage) : 0;
    info.currentPage = static_cast<int>(clampedPage) + 1;
  } else {
    info.currentPage = currentPage + 1;
  }
  return info;
}
