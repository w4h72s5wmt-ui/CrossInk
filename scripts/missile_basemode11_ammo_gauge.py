from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  for (int i = 0; i < kBatteryCount; ++i) {
    if (baseMode_ && !batteriesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);
    char ammoText[8];
    std::snprintf(ammoText, sizeof(ammoText), "%u", static_cast<unsigned>(ammo_[static_cast<size_t>(i)]));
    drawCenteredText(renderer, UI_10_FONT_ID, battery, ammoText);
  }
'''

new = r'''  for (int i = 0; i < kBatteryCount; ++i) {
    if (baseMode_ && !batteriesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};

    // Ammo is represented directly by the battery body. At the start of a wave
    // the inside is solid black. Each fired missile permanently punches one or
    // two small white cells into that black area (15 visual cells scaled to the
    // current 10..15-round capacity). No text rasterization and no dedicated
    // display refresh: the normal gameplay dirty-window path sees only the tiny
    // cells that actually changed.
    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);
    constexpr int gaugeCols = 5;
    constexpr int gaugeRows = 3;
    constexpr int gaugeCells = gaugeCols * gaugeRows;
    constexpr int gaugeGap = 2;
    const Rect gauge{battery.x + 4, battery.y + 4, battery.width - 8, battery.height - 8};
    renderer.fillRect(gauge.x, gauge.y, gauge.width, gauge.height, true);

    const int capacity = 10 + std::min<int>(wave_ / 2, 5);
    const int remaining = std::clamp<int>(ammo_[static_cast<size_t>(i)], 0, capacity);
    const int spent = capacity - remaining;
    const int spentCells = spent == 0 ? 0 : std::min(gaugeCells, (spent * gaugeCells + capacity - 1) / capacity);
    const int cellW = std::max(1, (gauge.width - gaugeGap * (gaugeCols - 1)) / gaugeCols);
    const int cellH = std::max(1, (gauge.height - gaugeGap * (gaugeRows - 1)) / gaugeRows);

    // Empty from right to left, top to bottom. Because the gauge is recomposed
    // from state every frame this is deterministic, while the physical panel
    // only receives changed cells through Cluster1.
    for (int cell = 0; cell < spentCells; ++cell) {
      const int row = cell / gaugeCols;
      const int col = gaugeCols - 1 - (cell % gaugeCols);
      const int gx = gauge.x + col * (cellW + gaugeGap);
      const int gy = gauge.y + row * (cellH + gaugeGap);
      renderer.fillRect(gx, gy, cellW, cellH, false);
    }
  }
'''

if old not in text:
    raise SystemExit("battery ammo-number rendering anchor not found")
text = text.replace(old, new, 1)

text = text.replace("/missile-command-bm10-explosion-polish-bench.csv",
                    "/missile-command-bm11-ammo-gauge-bench.csv")
text = text.replace("/missile-command-bm10-explosion-polish-trace.csv",
                    "/missile-command-bm11-ammo-gauge-trace.csv")
text = text.replace("bm10-explosion-polish-started", "bm11-ammo-gauge-started")
text = text.replace("bm10-explosion-polish,%lu,%lu,%lu,%lu,%lu",
                    "bm11-ammo-gauge,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM10-EXPLOSION-POLISH", "MISSILE-BM11-AMMO-GAUGE")

CPP.write_text(text)
print("Missile BaseMode11: turret-body ammo gauge applied")
