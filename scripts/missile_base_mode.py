from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
HDR = Path("src/activities/home/MissileCommandActivity.h")


def replace_once(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:180]!r}")
    return text.replace(old, new, 1)

# ---------------------------------------------------------------------------
# Header/state: add one menu row, a Base-mode toggle and three destructible
# battery/base states. This patch is applied last, after Explosion2 + PROFILE1,
# and deliberately does not touch the display pipeline or telemetry.
# ---------------------------------------------------------------------------
h = HDR.read_text()
h = replace_once(h,
    "  static constexpr int kMenuRowCount = 5;\n",
    "  static constexpr int kMenuRowCount = 6;\n",
    "menu row count")
h = replace_once(h,
    "  std::array<uint8_t, kBatteryCount> ammo_{};\n",
    "  std::array<uint8_t, kBatteryCount> ammo_{};\n"
    "  std::array<uint8_t, kBatteryCount> batteriesAlive_{{1, 1, 1}};\n"
    "  bool baseMode_ = false;\n",
    "base mode state")
HDR.write_text(h)

c = CPP.read_text()

# ---------------------------------------------------------------------------
# Menu behavior: rows 0..2 difficulty, row 3 toggles Base mode, row 4 Continue,
# row 5 New game. Checkbox drawing mirrors the existing simple e-ink option box.
# ---------------------------------------------------------------------------
c = replace_once(c,
'''  if (row == 3) {
    if (hasSavedGame_) continueGame();
    return;
  }
  if (row != 4) return;
''',
'''  if (row == 3) {
    baseMode_ = !baseMode_;
    requestUpdate();
    return;
  }
  if (row == 4) {
    if (hasSavedGame_) continueGame();
    return;
  }
  if (row != 5) return;
''',
"activate Base-mode row")

c = replace_once(c,
'''  items[3].label = "Continuer";
  if (hasSavedGame_) {
    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",
                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));
    items[3].value = continueValue_.data();
  } else {
    items[3].value = "Aucune partie";
  }
  items[3].actionValue = 3;

  items[4].label = "Nouvelle partie";
  items[4].value = DIFFICULTY_LABELS[difficulty_];
  items[4].actionValue = 4;
''',
'''  items[3].label = "Mode bases";
  items[3].value = nullptr;
  items[3].actionValue = 3;

  items[4].label = "Continuer";
  if (hasSavedGame_) {
    std::snprintf(continueValue_.data(), continueValue_.size(), "Vague %u - %lu pts",
                  static_cast<unsigned>(wave_), static_cast<unsigned long>(score_));
    items[4].value = continueValue_.data();
  } else {
    items[4].value = "Aucune partie";
  }
  items[4].actionValue = 4;

  items[5].label = "Nouvelle partie";
  items[5].value = DIFFICULTY_LABELS[difficulty_];
  items[5].actionValue = 5;
''',
"menu rows")

# Extend existing checkbox overlay to include Base mode, and draw an X rather
# than a filled square for that toggle.
old_loop = '''  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if (itemIndex < 0 || itemIndex >= kDifficultyCount) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    if (itemIndex == difficulty_) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    }
  }
'''
new_loop = '''  for (int visible = 0; visible < drawnRows; ++visible) {
    const int itemIndex = topIndex_ + visible;
    if ((itemIndex < 0 || itemIndex >= kDifficultyCount) && itemIndex != 3) continue;
    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;
    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;
    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);
    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);
    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);
    if (itemIndex < kDifficultyCount && itemIndex == difficulty_) {
      const int inset = (boxSize - innerSize) / 2;
      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);
    } else if (itemIndex == 3 && baseMode_) {
      renderer.drawLine(boxX + 5, boxY + 5, boxX + boxSize - 6, boxY + boxSize - 6, 2, true);
      renderer.drawLine(boxX + boxSize - 6, boxY + 5, boxX + 5, boxY + boxSize - 6, 2, true);
    }
  }
'''
c = replace_once(c, old_loop, new_loop, "checkbox overlay")

c = replace_once(c,
'''    if (itemIndex != 3 && itemIndex != 4) continue;
''',
'''    if (itemIndex != 4 && itemIndex != 5) continue;
''',
"action-row outlines")
c = replace_once(c,
'''    if (itemIndex == 3 && !hasSavedGame_) {
''',
'''    if (itemIndex == 4 && !hasSavedGame_) {
''',
"disabled Continue row")

# ---------------------------------------------------------------------------
# New game: initialize the three bases. Normal mode remains byte-for-byte in
# gameplay semantics except for carrying this unused state.
# ---------------------------------------------------------------------------
c = replace_once(c,
'''  citiesAlive_.fill(1);
  ammo_.fill(10);
''',
'''  citiesAlive_.fill(1);
  batteriesAlive_.fill(1);
  ammo_.fill(10);
''',
"new-game bases")

# A wave replenishes ammunition only for bases that are still alive in Base mode.
c = replace_once(c,
'''  ammo_.fill(static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5)));
''',
'''  const uint8_t waveAmmo = static_cast<uint8_t>(10 + std::min<int>(wave_ / 2, 5));
  for (int i = 0; i < kBatteryCount; ++i)
    ammo_[static_cast<size_t>(i)] = (!baseMode_ || batteriesAlive_[static_cast<size_t>(i)]) ? waveAmmo : 0;
''',
"wave ammo")

# ---------------------------------------------------------------------------
# Enemy impact and targeting. In Base mode enemies target the three battery
# positions directly; a hit destroys that battery and it can no longer fire.
# Normal city targeting is preserved unchanged in the else branch.
# ---------------------------------------------------------------------------
old_impact = '''    int nearest = 0;
    int nearestDist = 1 << 30;
    for (int i = 0; i < kCityCount; ++i) {
      if (!citiesAlive_[static_cast<size_t>(i)]) continue;
      const int cityX = geometry.field.x + (geometry.field.width * (i + 1)) / (kCityCount + 1);
      const int d = std::abs(cityX - missile.targetX);
      if (d < nearestDist) {
        nearestDist = d;
        nearest = i;
      }
    }
    if (nearestDist < std::max(24, geometry.field.width / 10)) citiesAlive_[static_cast<size_t>(nearest)] = 0;
    createExplosion(missile.targetX, missile.targetY);
'''
new_impact = '''    if (baseMode_) {
      int nearest = -1;
      int nearestDist = 1 << 30;
      for (int i = 0; i < kBatteryCount; ++i) {
        if (!batteriesAlive_[static_cast<size_t>(i)]) continue;
        const int bx = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
        const int d = std::abs(bx - missile.targetX);
        if (d < nearestDist) { nearestDist = d; nearest = i; }
      }
      if (nearest >= 0 && nearestDist < std::max(24, geometry.field.width / 8)) {
        batteriesAlive_[static_cast<size_t>(nearest)] = 0;
        ammo_[static_cast<size_t>(nearest)] = 0;
      }
    } else {
      int nearest = 0;
      int nearestDist = 1 << 30;
      for (int i = 0; i < kCityCount; ++i) {
        if (!citiesAlive_[static_cast<size_t>(i)]) continue;
        const int cityX = geometry.field.x + (geometry.field.width * (i + 1)) / (kCityCount + 1);
        const int d = std::abs(cityX - missile.targetX);
        if (d < nearestDist) { nearestDist = d; nearest = i; }
      }
      if (nearestDist < std::max(24, geometry.field.width / 10)) citiesAlive_[static_cast<size_t>(nearest)] = 0;
    }
    createExplosion(missile.targetX, missile.targetY);
'''
c = replace_once(c, old_impact, new_impact, "enemy impact")

old_spawn_target = '''  std::array<int, kCityCount> alive{};
  int aliveCount = 0;
  for (int i = 0; i < kCityCount; ++i) {
    if (citiesAlive_[static_cast<size_t>(i)]) alive[static_cast<size_t>(aliveCount++)] = i;
  }
  if (aliveCount <= 0) return;
  const int city = alive[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
  slot->targetX = static_cast<int16_t>(geometry.field.x + (geometry.field.width * (city + 1)) / (kCityCount + 1));
  slot->targetY = static_cast<int16_t>(geometry.groundY);
'''
new_spawn_target = '''  if (baseMode_) {
    std::array<int, kBatteryCount> aliveBases{};
    int aliveCount = 0;
    for (int i = 0; i < kBatteryCount; ++i) {
      if (batteriesAlive_[static_cast<size_t>(i)]) aliveBases[static_cast<size_t>(aliveCount++)] = i;
    }
    if (aliveCount <= 0) return;
    const int base = aliveBases[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
    slot->targetX = static_cast<int16_t>(geometry.field.x + geometry.field.width * (base * 2 + 1) / (kBatteryCount * 2));
    slot->targetY = static_cast<int16_t>(geometry.groundY + 18);
  } else {
    std::array<int, kCityCount> alive{};
    int aliveCount = 0;
    for (int i = 0; i < kCityCount; ++i) {
      if (citiesAlive_[static_cast<size_t>(i)]) alive[static_cast<size_t>(aliveCount++)] = i;
    }
    if (aliveCount <= 0) return;
    const int city = alive[static_cast<size_t>(esp_random() % static_cast<uint32_t>(aliveCount))];
    slot->targetX = static_cast<int16_t>(geometry.field.x + (geometry.field.width * (city + 1)) / (kCityCount + 1));
    slot->targetY = static_cast<int16_t>(geometry.groundY);
  }
'''
c = replace_once(c, old_spawn_target, new_spawn_target, "enemy target selection")

# Player fire can only originate from a surviving base in Base mode.
c = replace_once(c,
'''    if (d < bestDistance && ammo_[static_cast<size_t>(i)] > 0) {
''',
'''    if (d < bestDistance && ammo_[static_cast<size_t>(i)] > 0 &&
        (!baseMode_ || batteriesAlive_[static_cast<size_t>(i)])) {
''',
"nearest live battery")

# ---------------------------------------------------------------------------
# Game-over/lifecycle counting: keep the existing aliveCityCount() call sites
# and make it mean "surviving objectives" in Base mode.
# ---------------------------------------------------------------------------
c = replace_once(c,
'''int MissileCommandActivity::aliveCityCount() const {
  int count = 0;
  for (uint8_t alive : citiesAlive_) count += alive ? 1 : 0;
  return count;
}
''',
'''int MissileCommandActivity::aliveCityCount() const {
  int count = 0;
  if (baseMode_) {
    for (uint8_t alive : batteriesAlive_) count += alive ? 1 : 0;
  } else {
    for (uint8_t alive : citiesAlive_) count += alive ? 1 : 0;
  }
  return count;
}
''',
"objective count")

# Surviving-objective bonus uses bases instead of invisible cities.
c = replace_once(c,
'''  for (int i = 0; i < kCityCount; ++i) {
    if (citiesAlive_[static_cast<size_t>(i)]) score_ += 100;
  }
''',
'''  if (baseMode_) {
    for (int i = 0; i < kBatteryCount; ++i) {
      if (batteriesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  } else {
    for (int i = 0; i < kCityCount; ++i) {
      if (citiesAlive_[static_cast<size_t>(i)]) score_ += 100;
    }
  }
''',
"wave objective bonus")

# ---------------------------------------------------------------------------
# Rendering: no cities in Base mode. The three batteries become the visible
# objectives; destroyed ones disappear. Header says Bases instead of Villes.
# ---------------------------------------------------------------------------
c = replace_once(c,
'''  for (int i = 0; i < kCityCount; ++i) {
    if (!citiesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i + 1) / (kCityCount + 1);
    renderer.drawRect(x - 10, geometry.groundY - 11, 20, 11, 1, true);
    renderer.drawLine(x - 8, geometry.groundY - 11, x, geometry.groundY - 20, 1, true);
    renderer.drawLine(x, geometry.groundY - 20, x + 8, geometry.groundY - 11, 1, true);
  }
''',
'''  if (!baseMode_) {
    for (int i = 0; i < kCityCount; ++i) {
      if (!citiesAlive_[static_cast<size_t>(i)]) continue;
      const int x = geometry.field.x + geometry.field.width * (i + 1) / (kCityCount + 1);
      renderer.drawRect(x - 10, geometry.groundY - 11, 20, 11, 1, true);
      renderer.drawLine(x - 8, geometry.groundY - 11, x, geometry.groundY - 20, 1, true);
      renderer.drawLine(x, geometry.groundY - 20, x + 8, geometry.groundY - 11, 1, true);
    }
  }
''',
"hide cities")

c = replace_once(c,
'''  for (int i = 0; i < kBatteryCount; ++i) {
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
''',
'''  for (int i = 0; i < kBatteryCount; ++i) {
    if (baseMode_ && !batteriesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
''',
"hide destroyed bases")

# Cluster1 final title is generated earlier in the patch chain.
c = replace_once(c,
'''  std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Vague n° %u - Ville(s) : %d",
                static_cast<unsigned>(wave_), aliveCityCount());
''',
'''  if (baseMode_) {
    std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Vague n° %u - Base(s) : %d",
                  static_cast<unsigned>(wave_), aliveCityCount());
  } else {
    std::snprintf(gameplayTitle, sizeof(gameplayTitle), "Vague n° %u - Ville(s) : %d",
                  static_cast<unsigned>(wave_), aliveCityCount());
  }
''',
"Base-mode title")

# ---------------------------------------------------------------------------
# Save format v2: persist Base mode + battery states. Existing v1 saves remain
# loadable and are interpreted as classic city mode with all three batteries up.
# ---------------------------------------------------------------------------
c = replace_once(c,
'''constexpr uint8_t SAVE_VERSION = 1;
''',
'''constexpr uint8_t SAVE_VERSION = 2;
''',
"save version")

c = replace_once(c,
'''  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));
  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&
            writeValue(file, wave_) && writeValue(file, score_);
  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();
  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();
''',
'''  const uint8_t difficulty = static_cast<uint8_t>(std::clamp(difficulty_, 0, 2));
  const uint8_t baseMode = baseMode_ ? 1 : 0;
  bool ok = writeValue(file, SAVE_MAGIC) && writeValue(file, SAVE_VERSION) && writeValue(file, difficulty) &&
            writeValue(file, wave_) && writeValue(file, score_) && writeValue(file, baseMode);
  if (ok) ok = file.write(citiesAlive_.data(), citiesAlive_.size()) == citiesAlive_.size();
  if (ok) ok = file.write(ammo_.data(), ammo_.size()) == ammo_.size();
  if (ok) ok = file.write(batteriesAlive_.data(), batteriesAlive_.size()) == batteriesAlive_.size();
''',
"save v2 payload")

old_load = '''  uint16_t wave = 0;
  uint32_t score = 0;
  std::array<uint8_t, kCityCount> cities{};
  std::array<uint8_t, kBatteryCount> ammo{};
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, difficulty) &&
            readValue(file, wave) && readValue(file, score);
  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());
  if (ok) ok = file.read(ammo.data(), ammo.size()) == static_cast<int>(ammo.size());
  file.close();
  if (!ok || magic != SAVE_MAGIC || version != SAVE_VERSION || difficulty > 2 || wave == 0) {
    clearSavedGame();
    return false;
  }
'''
new_load = '''  uint16_t wave = 0;
  uint32_t score = 0;
  uint8_t baseMode = 0;
  std::array<uint8_t, kCityCount> cities{};
  std::array<uint8_t, kBatteryCount> ammo{};
  std::array<uint8_t, kBatteryCount> batteries{{1, 1, 1}};
  bool ok = readValue(file, magic) && readValue(file, version) && readValue(file, difficulty) &&
            readValue(file, wave) && readValue(file, score);
  if (ok && version >= 2) ok = readValue(file, baseMode);
  if (ok) ok = file.read(cities.data(), cities.size()) == static_cast<int>(cities.size());
  if (ok) ok = file.read(ammo.data(), ammo.size()) == static_cast<int>(ammo.size());
  if (ok && version >= 2)
    ok = file.read(batteries.data(), batteries.size()) == static_cast<int>(batteries.size());
  file.close();
  if (!ok || magic != SAVE_MAGIC || (version != 1 && version != 2) || difficulty > 2 || wave == 0 || baseMode > 1) {
    clearSavedGame();
    return false;
  }
'''
c = replace_once(c, old_load, new_load, "load v1/v2 payload")

c = replace_once(c,
'''  difficulty_ = difficulty;
  wave_ = wave;
  score_ = score;
  citiesAlive_ = cities;
  ammo_ = ammo;
''',
'''  for (uint8_t alive : batteries) {
    if (alive > 1) {
      clearSavedGame();
      return false;
    }
  }
  difficulty_ = difficulty;
  wave_ = wave;
  score_ = score;
  baseMode_ = version >= 2 && baseMode != 0;
  citiesAlive_ = cities;
  ammo_ = ammo;
  batteriesAlive_ = batteries;
''',
"restore Base-mode state")

# Separate benchmark/trace identity for this gameplay experiment.
c = c.replace("profile1-entryhalf-explosion2-trace.csv", "profile1-entryhalf-explosion2-basemode-trace.csv")
c = c.replace("profile1-entryhalf-explosion2-bench.csv", "profile1-entryhalf-explosion2-basemode-bench.csv")
c = c.replace("PROFILE1-ENTRYHALF-EXP2", "PROFILE1-ENTRYHALF-EXP2-BASE")
c = c.replace("profile1-entryhalf-explosion2-started", "profile1-entryhalf-explosion2-basemode-started")
c = c.replace("profile1-entryhalf-explosion2,%lu", "profile1-entryhalf-explosion2-basemode,%lu")

CPP.write_text(c)
print("Missile Base mode: checkbox + three destructible battery objectives applied")
