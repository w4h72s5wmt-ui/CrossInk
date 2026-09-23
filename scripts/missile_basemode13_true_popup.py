from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

def replace_once(old: str, new: str, name: str):
    global text
    if old not in text:
        raise SystemExit(f"{name} anchor not found")
    text = text.replace(old, new, 1)

# Compact true popup, centred over the frozen gameplay field.
replace_once(
r'''Rect waveCompleteBox(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect header = headerRect(renderer, mappedInput);
  const int top = header.y + header.height + 12;
  const int bottom = renderer.getScreenHeight() - UITheme::getInstance().getMetrics().buttonHintsHeight - 10;
  const int width = std::min(560, renderer.getScreenWidth() - 40);
  const int height = std::max(220, bottom - top);
  return Rect{(renderer.getScreenWidth() - width) / 2, top, width, height};
}

Rect waveCompleteActionRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect box = waveCompleteBox(renderer, mappedInput);
  return Rect{box.x + 28, box.y + box.height - 58, box.width - 56, 44};
}
''',
r'''Rect waveCompleteBox(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  const int width = std::min(430, geometry.field.width - 40);
  const int height = std::min(272, geometry.field.height - 28);
  return Rect{geometry.field.x + (geometry.field.width - width) / 2,
              geometry.field.y + (geometry.field.height - height) / 2,
              width, height};
}

Rect waveCompleteActionRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {
  const Rect box = waveCompleteBox(renderer, mappedInput);
  return Rect{box.x + 34, box.y + box.height - 54, box.width - 68, 40};
}
''',
"compact popup geometry"
)

replace_once(
r'''void MissileCommandActivity::renderWaveComplete() {
  renderer.clearScreen();
  const Rect header = headerRect(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, header, "Missile Command", nullptr, false);
  }

  const Rect box = waveCompleteBox(renderer, mappedInput);
  const Rect action = waveCompleteActionRect(renderer, mappedInput);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 1, 8, true);

  char line[72];
  std::snprintf(line, sizeof(line), "Vague %u terminee", static_cast<unsigned>(completedWave_));
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 16, box.y + 14, box.width - 32, 34}, line);

  std::snprintf(line, sizeof(line), "Score actuel : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 62, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "Meilleur score : %lu", static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 94, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "Munitions restantes : %u",
                static_cast<unsigned>(waveEndAmmoRemaining_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 126, box.width - 40, 28}, line);

  std::snprintf(line, sizeof(line), "%s restantes : %u",
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 20, box.y + 158, box.width - 40, 28}, line);

  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Vague suivante");

  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);

  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  cycleRenderPending_.store(false);
}
''',
r'''void MissileCommandActivity::renderWaveComplete() {
  // TRUE popup: keep the exact last gameplay framebuffer as the backdrop.
  // Only paint an opaque white card over it. No clearScreen(), no header redraw,
  // no full-screen UI reconstruction.
  const Rect box = waveCompleteBox(renderer, mappedInput);
  const Rect action = waveCompleteActionRect(renderer, mappedInput);

  renderer.fillRect(box.x, box.y, box.width, box.height, false);
  renderer.drawRoundedRect(box.x, box.y, box.width, box.height, 2, 8, true);

  char line[72];
  std::snprintf(line, sizeof(line), "Vague %u terminee", static_cast<unsigned>(completedWave_));
  drawCenteredText(renderer, UI_12_FONT_ID, Rect{box.x + 16, box.y + 10, box.width - 32, 32}, line);

  std::snprintf(line, sizeof(line), "Score : %lu", static_cast<unsigned long>(score_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 51, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "Record : %lu", static_cast<unsigned long>(highScore_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 79, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "Munitions : %u", static_cast<unsigned>(waveEndAmmoRemaining_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 107, box.width - 36, 25}, line);

  std::snprintf(line, sizeof(line), "%s : %u",
                baseMode_ ? "Bases" : "Villes", static_cast<unsigned>(waveEndObjectives_));
  drawCenteredText(renderer, UI_10_FONT_ID, Rect{box.x + 18, box.y + 135, box.width - 36, 25}, line);

  renderer.drawRoundedRect(action.x, action.y, action.width, action.height, 1, 6, true);
  drawCenteredText(renderer, UI_10_FONT_ID, action, "Vague suivante");

  // Inter-wave is static and can use the stock clean HALF. The visible pixels
  // outside the card are unchanged, so the user still sees the frozen battlefield.
  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  windowShadowValid_ = false;
  clusterCatchupPending_ = false;
  cycleRenderPending_.store(false);
}
''',
"true popup render"
)

text = text.replace("/missile-command-bm12-interwave-fullfield-bench.csv",
                    "/missile-command-bm13-true-popup-bench.csv")
text = text.replace("/missile-command-bm12-interwave-fullfield-trace.csv",
                    "/missile-command-bm13-true-popup-trace.csv")
text = text.replace("bm12-interwave-fullfield-started", "bm13-true-popup-started")
text = text.replace("bm12-interwave-fullfield,%lu,%lu,%lu,%lu,%lu",
                    "bm13-true-popup,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM12-INTERWAVE-FULLFIELD", "MISSILE-BM13-TRUE-POPUP")

CPP.write_text(text)
print("Missile BaseMode13: true compact inter-wave popup over frozen gameplay applied")
