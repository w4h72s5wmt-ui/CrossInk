from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")

# ---------------------------------------------------------------------------
# Header cleanup requested after the 4P visual/perf validation: one single title
# render, no metadata lane. Keep the exact same header renderer/font/placement,
# only shorten the gameplay title so it fits comfortably.
# ---------------------------------------------------------------------------
text = CPP.read_text()
old_title = r'''  char gameplayTitle[64];
  std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Missile Command - Wave %u - Town %d",
                static_cast<unsigned>(wave_), aliveCityCount());
'''
new_title = r'''  char gameplayTitle[64];
  std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Vague n° %u - Ville(s) : %d",
                static_cast<unsigned>(wave_), aliveCityCount());
'''
if old_title not in text:
    raise SystemExit("4P gameplay title block not found")
text = text.replace(old_title, new_title, 1)
CPP.write_text(text)

# ---------------------------------------------------------------------------
# Dirty-cluster experiment: keep the dominant dirty region at full cadence and
# defer at most ONE small, spatially-disjoint satellite component for exactly
# one frame. The next frame is forced to catch all remaining dirt, so nothing
# can starve. This attacks cases where two distant moving regions create a huge
# union PTL while preserving one blocking DRF per game cycle.
#
# Important invariants:
#   * split only when the satellite is <= 40% of dirty tiles;
#   * satellite bbox must be disjoint from the remainder on X or Y;
#   * omitting it must shrink scan bbox area by >= 30%;
#   * after a split, the next frame never splits (one-frame max deferral);
#   * shadow is copied only for the physical bbox actually refreshed.
# ---------------------------------------------------------------------------
text = HDR.read_text()
anchor = "  bool windowShadowValid_ = false;\n"
if anchor not in text:
    raise SystemExit("window shadow state anchor not found")
text = text.replace(anchor, anchor + "  bool clusterCatchupPending_ = false;\n", 1)
HDR.write_text(text)

text = CPP.read_text()
old_dirty = r'''  constexpr uint16_t TILE_W = 32;
  constexpr uint16_t TILE_H = 16;
  constexpr uint16_t TILE_COLS = (HalDisplay::DISPLAY_WIDTH + TILE_W - 1) / TILE_W;
  constexpr uint16_t TILE_ROWS = (HalDisplay::DISPLAY_HEIGHT + TILE_H - 1) / TILE_H;
  constexpr uint16_t TILE_COUNT = TILE_COLS * TILE_ROWS;
  constexpr uint16_t TILE_MASK_BYTES = (TILE_COUNT + 7) / 8;
  std::array<uint8_t, TILE_MASK_BYTES> tileMask{};
  uint16_t dirtyTiles = 0;

  for (uint16_t row = minY; row <= maxY; ++row) {
    const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
    for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
      const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
      const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
      const uint8_t mask = static_cast<uint8_t>(1u << (bit & 7));
      if ((tileMask[bit >> 3] & mask) == 0) {
        tileMask[bit >> 3] |= mask;
        ++dirtyTiles;
      }
    }
  }

  const uint32_t bboxPayload = static_cast<uint32_t>(w / 8) * h;
  const uint32_t sparsePayload = static_cast<uint32_t>(dirtyTiles) * (TILE_W / 8) * TILE_H;
  // PTL command overhead is tiny, but don't fragment dense frames. Require at
  // least 30% RAM-byte savings and cap the number of small windows.
  const bool useSparse = dirtyTiles > 0 && dirtyTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
  if (useSparse) {
    display.displaySparseWindow(tileMask.data(), TILE_COLS, TILE_ROWS, TILE_W, TILE_H, x, y, w, h, false);
  } else {
    display.displayWindow(x, y, w, h, false);
  }

  const uint16_t copyBytes = static_cast<uint16_t>(w / 8);
  for (uint16_t row = 0; row < h; ++row) {
    const uint32_t offset = static_cast<uint32_t>(y + row) * wb + minByte;
    memcpy(windowShadow_ + offset, fb + offset, copyBytes);
  }
'''

new_dirty = r'''  constexpr uint16_t TILE_W = 32;
  constexpr uint16_t TILE_H = 16;
  constexpr uint16_t TILE_COLS = (HalDisplay::DISPLAY_WIDTH + TILE_W - 1) / TILE_W;
  constexpr uint16_t TILE_ROWS = (HalDisplay::DISPLAY_HEIGHT + TILE_H - 1) / TILE_H;
  constexpr uint16_t TILE_COUNT = TILE_COLS * TILE_ROWS;
  constexpr uint16_t TILE_MASK_BYTES = (TILE_COUNT + 7) / 8;
  std::array<uint8_t, TILE_MASK_BYTES> tileMask{};
  uint16_t dirtyTiles = 0;

  for (uint16_t row = minY; row <= maxY; ++row) {
    const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
    for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
      const uint32_t offset = rowOffset + bx;
      if (fb[offset] == windowShadow_[offset]) continue;
      const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
      const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
      const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
      const uint8_t mask = static_cast<uint8_t>(1u << (bit & 7));
      if ((tileMask[bit >> 3] & mask) == 0) {
        tileMask[bit >> 3] |= mask;
        ++dirtyTiles;
      }
    }
  }

  std::array<uint8_t, TILE_MASK_BYTES> refreshMask = tileMask;
  uint16_t refreshTiles = dirtyTiles;
  uint16_t refreshMinByte = minByte;
  uint16_t refreshMaxByte = maxByte;
  uint16_t refreshMinY = minY;
  uint16_t refreshMaxY = maxY;

  // A split frame is always followed by a catch-up frame. Since the app shadow
  // is NOT advanced for the omitted satellite, those pixels remain dirty and
  // the next pass naturally uploads their latest state (skipping only one
  // intermediate visual frame, never simulation state).
  if (clusterCatchupPending_) {
    clusterCatchupPending_ = false;
  } else if (dirtyTiles >= 2 && dirtyTiles <= 128) {
    struct DirtyComponent {
      uint16_t count = 0;
      uint16_t minTx = TILE_COLS;
      uint16_t maxTx = 0;
      uint16_t minTy = TILE_ROWS;
      uint16_t maxTy = 0;
    };
    constexpr uint8_t MAX_COMPONENTS = 32;
    std::array<uint8_t, TILE_COUNT> componentOf{};
    std::array<uint16_t, TILE_COUNT> queue{};
    std::array<DirtyComponent, MAX_COMPONENTS> components{};
    uint8_t componentCount = 0;
    bool componentOverflow = false;

    const auto tileDirty = [&](uint16_t bit) {
      return (tileMask[bit >> 3] & static_cast<uint8_t>(1u << (bit & 7))) != 0;
    };

    for (uint16_t seed = 0; seed < TILE_COUNT && !componentOverflow; ++seed) {
      if (!tileDirty(seed) || componentOf[seed] != 0) continue;
      if (componentCount >= MAX_COMPONENTS) {
        componentOverflow = true;
        break;
      }
      const uint8_t id = static_cast<uint8_t>(++componentCount);
      DirtyComponent& comp = components[id - 1];
      uint16_t qHead = 0;
      uint16_t qTail = 0;
      queue[qTail++] = seed;
      componentOf[seed] = id;

      while (qHead < qTail) {
        const uint16_t bit = queue[qHead++];
        const uint16_t tx = static_cast<uint16_t>(bit % TILE_COLS);
        const uint16_t ty = static_cast<uint16_t>(bit / TILE_COLS);
        ++comp.count;
        comp.minTx = std::min(comp.minTx, tx);
        comp.maxTx = std::max(comp.maxTx, tx);
        comp.minTy = std::min(comp.minTy, ty);
        comp.maxTy = std::max(comp.maxTy, ty);

        const auto visit = [&](int nx, int ny) {
          if (nx < 0 || ny < 0 || nx >= TILE_COLS || ny >= TILE_ROWS) return;
          const uint16_t nbit = static_cast<uint16_t>(ny * TILE_COLS + nx);
          if (!tileDirty(nbit) || componentOf[nbit] != 0) return;
          componentOf[nbit] = id;
          queue[qTail++] = nbit;
        };
        visit(static_cast<int>(tx) - 1, ty);
        visit(static_cast<int>(tx) + 1, ty);
        visit(tx, static_cast<int>(ty) - 1);
        visit(tx, static_cast<int>(ty) + 1);
      }
    }

    if (!componentOverflow && componentCount >= 2) {
      const uint32_t globalArea = static_cast<uint32_t>(w) * h;
      int bestDefer = -1;
      uint32_t bestRemainArea = globalArea;

      for (uint8_t c = 0; c < componentCount; ++c) {
        const DirtyComponent& satellite = components[c];
        if (static_cast<uint32_t>(satellite.count) * 100u > static_cast<uint32_t>(dirtyTiles) * 40u) continue;

        uint16_t rMinTx = TILE_COLS;
        uint16_t rMaxTx = 0;
        uint16_t rMinTy = TILE_ROWS;
        uint16_t rMaxTy = 0;
        uint16_t remainCount = 0;
        for (uint8_t other = 0; other < componentCount; ++other) {
          if (other == c || components[other].count == 0) continue;
          const DirtyComponent& rc = components[other];
          remainCount = static_cast<uint16_t>(remainCount + rc.count);
          rMinTx = std::min(rMinTx, rc.minTx);
          rMaxTx = std::max(rMaxTx, rc.maxTx);
          rMinTy = std::min(rMinTy, rc.minTy);
          rMaxTy = std::max(rMaxTy, rc.maxTy);
        }
        if (remainCount == 0) continue;

        // Require a genuine spatial gap. Then a bbox refresh of the remainder
        // cannot accidentally paint any byte belonging to the deferred island.
        const bool separated = satellite.maxTx < rMinTx || satellite.minTx > rMaxTx ||
                               satellite.maxTy < rMinTy || satellite.minTy > rMaxTy;
        if (!separated) continue;

        const uint32_t rx0 = static_cast<uint32_t>(rMinTx) * TILE_W;
        const uint32_t ry0 = static_cast<uint32_t>(rMinTy) * TILE_H;
        const uint32_t rx1 = std::min<uint32_t>(panelW, static_cast<uint32_t>(rMaxTx + 1) * TILE_W);
        const uint32_t ry1 = std::min<uint32_t>(panelH, static_cast<uint32_t>(rMaxTy + 1) * TILE_H);
        const uint32_t remainArea = (rx1 - rx0) * (ry1 - ry0);
        if (remainArea * 10u > globalArea * 7u) continue;  // need >=30% scan-area reduction
        if (remainArea < bestRemainArea) {
          bestRemainArea = remainArea;
          bestDefer = c;
        }
      }

      if (bestDefer >= 0) {
        const uint8_t deferredId = static_cast<uint8_t>(bestDefer + 1);
        for (uint16_t bit = 0; bit < TILE_COUNT; ++bit) {
          if (componentOf[bit] != deferredId) continue;
          refreshMask[bit >> 3] &= static_cast<uint8_t>(~(1u << (bit & 7)));
        }
        refreshTiles = static_cast<uint16_t>(dirtyTiles - components[bestDefer].count);

        // Tight byte bbox for the non-deferred pixels, not merely the tile bbox.
        refreshMinByte = wb;
        refreshMaxByte = 0;
        refreshMinY = panelH;
        refreshMaxY = 0;
        bool refreshChanged = false;
        for (uint16_t row = minY; row <= maxY; ++row) {
          const uint32_t rowOffset = static_cast<uint32_t>(row) * wb;
          for (uint16_t bx = minByte; bx <= maxByte; ++bx) {
            const uint32_t offset = rowOffset + bx;
            if (fb[offset] == windowShadow_[offset]) continue;
            const uint16_t tx = static_cast<uint16_t>((bx * 8) / TILE_W);
            const uint16_t ty = static_cast<uint16_t>(row / TILE_H);
            const uint16_t bit = static_cast<uint16_t>(ty * TILE_COLS + tx);
            if (componentOf[bit] == deferredId) continue;
            refreshChanged = true;
            refreshMinByte = std::min(refreshMinByte, bx);
            refreshMaxByte = std::max(refreshMaxByte, bx);
            refreshMinY = std::min(refreshMinY, row);
            refreshMaxY = std::max(refreshMaxY, row);
          }
        }
        if (refreshChanged) clusterCatchupPending_ = true;
      }
    }
  }

  const uint16_t refreshX = static_cast<uint16_t>(refreshMinByte * 8);
  const uint16_t refreshY = refreshMinY;
  const uint16_t refreshW = static_cast<uint16_t>((refreshMaxByte - refreshMinByte + 1) * 8);
  const uint16_t refreshH = static_cast<uint16_t>(refreshMaxY - refreshMinY + 1);
  const uint32_t bboxPayload = static_cast<uint32_t>(refreshW / 8) * refreshH;
  const uint32_t sparsePayload = static_cast<uint32_t>(refreshTiles) * (TILE_W / 8) * TILE_H;
  const bool useSparse = refreshTiles > 0 && refreshTiles <= 128 && sparsePayload * 10u <= bboxPayload * 7u;
  if (useSparse) {
    display.displaySparseWindow(refreshMask.data(), TILE_COLS, TILE_ROWS, TILE_W, TILE_H,
                                refreshX, refreshY, refreshW, refreshH, false);
  } else {
    display.displayWindow(refreshX, refreshY, refreshW, refreshH, false);
  }

  // The deferred component is guaranteed outside this bbox on at least one
  // axis, so copying the refreshed bbox cannot falsely acknowledge it. It stays
  // different from windowShadow_ and is therefore mandatory on the next frame.
  const uint16_t copyBytes = static_cast<uint16_t>(refreshW / 8);
  for (uint16_t row = 0; row < refreshH; ++row) {
    const uint32_t offset = static_cast<uint32_t>(refreshY + row) * wb + refreshMinByte;
    memcpy(windowShadow_ + offset, fb + offset, copyBytes);
  }
'''

if old_dirty not in text:
    raise SystemExit("sparse dirty-window block not found")
text = text.replace(old_dirty, new_dirty, 1)

# Give this experiment its own CSV identity.
text = text.replace(
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline-bench.csv',
    '/missile-command-game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-bench.csv',
)
text = text.replace('MISSILE-A2-OPT12-4P', 'MISSILE-A2-OPT12-4P-CLUSTER1')
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline-started',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1-started',
)
text = text.replace(
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-titleline,%lu,%lu,%lu,%lu,%lu',
    'game-a2-lite-pll0f-sparse-trail64-fade-header-hud-opt12-4p-cluster1,%lu,%lu,%lu,%lu,%lu',
)
CPP.write_text(text)

print("4P: compact French title + one-frame satellite dirty-cluster deferral applied")
