from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old_reserve = r'''  return renderer.getTextWidth(UI_10_FONT_ID, meta) + 24;
'''
new_reserve = r'''  // Counters use the same title font slot as "Missile Command" so their
  // vertical metrics are identical. Reserve that exact regular-font width.
  return renderer.getTextWidth(UI_12_FONT_ID, meta) + 24;
'''
if old_reserve not in text:
    raise SystemExit("header metadata reserve block not found")
text = text.replace(old_reserve, new_reserve, 1)

old_draw = r'''  const int w = renderer.getTextWidth(UI_10_FONT_ID, meta);
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

new_draw = r'''  // Draw the metadata through the *same FreeInkUI title font slot* and the
  // exact same vertical text box used by TouchHeaderBackButton for
  // "Missile Command". GfxRendererTarget vertically centers both runs from
  // the same line-height, so their baseline is identical by construction.
  auto metaTarget = makeUiTarget(renderer);
  fui::TextStyle metaStyle = uiThemeTokens(metaTarget).titleText;
  metaStyle.bold = false;
  metaStyle.align = fui::TextAlign::Right;
  metaStyle.maxLines = 1;

  const auto titleLayout = TouchHeaderBackButton::layout(header);
  const int w = renderer.getTextWidth(UI_12_FONT_ID, meta);
  const int right = header.x + header.width - 12;
  const int x = std::max(header.x, right - w);
  metaTarget.text(fui::Rect{static_cast<int16_t>(x), static_cast<int16_t>(titleLayout.iconRect.y),
                            static_cast<int16_t>(std::max(1, right - x)),
                            static_cast<int16_t>(titleLayout.iconRect.height)},
                  meta, metaStyle);
'''

if old_draw not in text:
    raise SystemExit("baseline-aligned header metadata block not found")
text = text.replace(old_draw, new_draw, 1)

CPP.write_text(text)
print("Missile header counters now share the exact title text box/font baseline")
