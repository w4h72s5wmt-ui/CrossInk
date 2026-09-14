from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old = r'''  const int w = renderer.getTextWidth(UI_10_FONT_ID, meta);
  const int h = renderer.getLineHeight(UI_10_FONT_ID);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x, right - w);
  const int y = header.y + std::max(0, (header.height - h) / 2);
  renderer.drawText(UI_10_FONT_ID, x, y, meta);
'''

new = r'''  const int w = renderer.getTextWidth(UI_10_FONT_ID, meta);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x, right - w);

  // Match the title's text baseline exactly instead of independently centering
  // UI_10 in the header. TouchHeaderBackButton positions the title inside its
  // action lane; derive that same title baseline, then back out UI_10's top Y
  // using its ascender. This keeps Missile Command and Vague/Villes on one line.
  const auto titleLayout = TouchHeaderBackButton::layout(header);
  const int titleLineH = renderer.getLineHeight(UI_12_FONT_ID);
  const int titleBaseline = titleLayout.iconRect.y +
                            std::max(0, (titleLayout.iconRect.height - titleLineH) / 2) +
                            renderer.getFontAscenderSize(UI_12_FONT_ID);
  const int y = titleBaseline - renderer.getFontAscenderSize(UI_10_FONT_ID);
  renderer.drawText(UI_10_FONT_ID, x, y, meta);
'''

if old not in text:
    raise SystemExit("header metadata vertical positioning block not found")

CPP.write_text(text.replace(old, new, 1))
print("Missile header Vague/Villes aligned to title baseline")
