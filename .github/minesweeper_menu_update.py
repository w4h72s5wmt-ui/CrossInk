from pathlib import Path

p = Path("src/activities/home/MinesweeperActivity.cpp")
s = p.read_text()

def rep(old, new):
    global s
    if old not in s:
        raise SystemExit("expected block not found")
    s = s.replace(old, new, 1)

rep('''    item.label = GRID_LABELS[i];\n    item.value = i == gridSizeIndex_ ? "Choisie" : nullptr;\n    item.actionValue = static_cast<int16_t>(i);\n''', '''    item.label = GRID_LABELS[i];\n    item.value = nullptr;\n    item.actionValue = static_cast<int16_t>(i);\n''')

rep('''  assistItem.label = "Aide compteur de mines";\n  assistItem.value = assistedCounterChoice ? "[X]" : "[ ]";\n  assistItem.actionValue = 4;\n''', '''  assistItem.label = "Aide compteur de mines";\n  assistItem.value = nullptr;\n  assistItem.actionValue = 4;\n''')

rep('''  uiReady_ = false;\n  app_.render();\n  uiReady_ = true;\n\n  const Rect scorePanel = scoreTableRect(renderer, mappedInput);\n''', '''  uiReady_ = false;\n  app_.render();\n  uiReady_ = true;\n\n  // Draw option states as real e-ink checkboxes: white square with a black\n  // inset square when enabled. This avoids font-dependent checkbox glyphs.\n  const Rect listBounds = menuListRect(renderer, mappedInput);\n  const int drawnRows = std::max(1, visibleRows_);\n  const int boxSize = 22;\n  const int innerSize = 10;\n  const int boxX = renderer.getScreenWidth() - UITheme::getInstance().getMetrics().contentSidePadding - boxSize - 10;\n  for (int visible = 0; visible < drawnRows; ++visible) {\n    const int itemIndex = topIndex_ + visible;\n    if (itemIndex < 0 || itemIndex > 4) continue;\n    const int rowTop = listBounds.y + listBounds.height * visible / drawnRows;\n    const int rowBottom = listBounds.y + listBounds.height * (visible + 1) / drawnRows;\n    const int boxY = rowTop + std::max(0, (rowBottom - rowTop - boxSize) / 2);\n    renderer.fillRect(boxX, boxY, boxSize, boxSize, false);\n    renderer.drawRect(boxX, boxY, boxSize, boxSize, 2, true);\n    const bool checked = itemIndex < kGridOptionCount ? itemIndex == gridSizeIndex_ : assistedCounterChoice;\n    if (checked) {\n      const int inset = (boxSize - innerSize) / 2;\n      renderer.fillRect(boxX + inset, boxY + inset, innerSize, innerSize, true);\n    }\n  }\n\n  const Rect scorePanel = scoreTableRect(renderer, mappedInput);\n''')

rep('''  const int headerRowHeight = 28;\n  const int dataTop = scorePanel.y + headerRowHeight;\n  const int dataHeight = scorePanel.height - headerRowHeight;\n  const int splitX = scorePanel.x + scorePanel.width * 2 / 5;\n\n  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);\n  renderer.drawLine(splitX, scorePanel.y, splitX, scorePanel.y + scorePanel.height, 1, true);\n''', '''  const int headerRowHeight = 30;\n  const int dataTop = scorePanel.y + headerRowHeight;\n  const int dataHeight = scorePanel.height - headerRowHeight;\n  const int splitX = scorePanel.x + scorePanel.width * 2 / 5;\n\n  renderer.drawLine(scorePanel.x, dataTop, scorePanel.x + scorePanel.width, dataTop, 1, true);\n  renderer.drawLine(splitX, dataTop, splitX, scorePanel.y + scorePanel.height, 1, true);\n''')

rep('''  const Rect gridHeader{scorePanel.x, scorePanel.y, splitX - scorePanel.x, headerRowHeight};\n  const Rect bestHeader{splitX, scorePanel.y, scorePanel.x + scorePanel.width - splitX, headerRowHeight};\n  drawCenteredCellText(UI_10_FONT_ID, gridHeader, "GRILLE");\n  drawCenteredCellText(UI_10_FONT_ID, bestHeader, "MEILLEUR SCORE");\n''', '''  const Rect scoreHeader{scorePanel.x, scorePanel.y, scorePanel.width, headerRowHeight};\n  drawCenteredCellText(UI_12_FONT_ID, scoreHeader, "SCORES");\n''')

p.write_text(s)
