from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()


def replace_once(old: str, new: str, name: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"{name} anchor not found: {old[:260]!r}")
    text = text.replace(old, new, 1)


# Match the Minesweeper menu pattern: reserve a dedicated button below the score
# table, and keep it outside the normal scrollable game-option rows.
replace_once(
    "constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;\n"
    "constexpr int MISSILE_SCORE_TABLE_GAP = 6;\n",
    "constexpr int MISSILE_SCORE_TABLE_HEIGHT = 132;\n"
    "constexpr int MISSILE_SCORE_TABLE_GAP = 6;\n"
    "constexpr int MISSILE_SCORE_RESET_GAP = 8;\n"
    "constexpr int MISSILE_SCORE_RESET_BUTTON_HEIGHT = 44;\n"
    "constexpr int MISSILE_SCORE_AREA_HEIGHT = MISSILE_SCORE_TABLE_HEIGHT + MISSILE_SCORE_TABLE_GAP +\n"
    "                                          MISSILE_SCORE_RESET_GAP + MISSILE_SCORE_RESET_BUTTON_HEIGHT;\n",
    "score reset geometry constants",
)

replace_once(
    "              std::max(1, renderer.getScreenHeight() - top - metrics.buttonHintsHeight -\n"
    "                              metrics.verticalSpacing - MISSILE_SCORE_TABLE_HEIGHT - MISSILE_SCORE_TABLE_GAP)};\n",
    "              std::max(1, renderer.getScreenHeight() - top - metrics.buttonHintsHeight -\n"
    "                              metrics.verticalSpacing - MISSILE_SCORE_AREA_HEIGHT)};\n",
    "reserve reset button area",
)

replace_once(
    "Rect missileScoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n"
    "  const auto& metrics = UITheme::getInstance().getMetrics();\n"
    "  const Rect list = menuRect(renderer, mappedInput);\n"
    "  return Rect{metrics.contentSidePadding, list.y + list.height + MISSILE_SCORE_TABLE_GAP,\n"
    "              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, MISSILE_SCORE_TABLE_HEIGHT};\n"
    "}\n",
    "Rect missileScoreTableRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n"
    "  const auto& metrics = UITheme::getInstance().getMetrics();\n"
    "  const Rect list = menuRect(renderer, mappedInput);\n"
    "  return Rect{metrics.contentSidePadding, list.y + list.height + MISSILE_SCORE_TABLE_GAP,\n"
    "              renderer.getScreenWidth() - 2 * metrics.contentSidePadding, MISSILE_SCORE_TABLE_HEIGHT};\n"
    "}\n\n"
    "Rect missileScoreResetButtonRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n"
    "  const Rect table = missileScoreTableRect(renderer, mappedInput);\n"
    "  return Rect{table.x, table.y + table.height + MISSILE_SCORE_RESET_GAP, table.width,\n"
    "              MISSILE_SCORE_RESET_BUTTON_HEIGHT};\n"
    "}\n",
    "reset button rect",
)

# Touch handling intentionally mirrors Minesweeper: intercept the dedicated
# reset button before routing touches to the scrollable option list.
replace_once(
    "  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||\n"
    "      mappedInput.wasPressed(MappedInputManager::Button::Back)) {\n"
    "    mappedInput.suppressNextBackRelease();\n"
    "    onGoHome();\n"
    "    return;\n"
    "  }\n\n"
    "  if (uiReady_) {\n",
    "  if ((mappedInput.hasTouchHardware() && TouchHeaderBackButton::wasTapped(mappedInput, header)) ||\n"
    "      mappedInput.wasPressed(MappedInputManager::Button::Back)) {\n"
    "    mappedInput.suppressNextBackRelease();\n"
    "    onGoHome();\n"
    "    return;\n"
    "  }\n\n"
    "  int resetTapX = 0;\n"
    "  int resetTapY = 0;\n"
    "  if (mappedInput.hasTouchHardware() && mappedInput.wasScreenTapped(resetTapX, resetTapY) &&\n"
    "      pointInRect(missileScoreResetButtonRect(renderer, mappedInput), resetTapX, resetTapY)) {\n"
    "    startActivityForResult(\n"
    "        std::make_unique<ConfirmationActivity>(renderer, mappedInput, \"Réinitialiser les scores ?\", \"\"),\n"
    "        [this](const ActivityResult& result) {\n"
    "          if (!result.isCancelled) {\n"
    "            highScores_.fill(0);\n"
    "            highScore_ = 0;\n"
    "            if (Storage.exists(SCORE_PATH)) Storage.remove(SCORE_PATH);\n"
    "          }\n"
    "          requestUpdate();\n"
    "        });\n"
    "    return;\n"
    "  }\n\n"
    "  if (uiReady_) {\n",
    "reset touch handler",
)

# Draw the same rounded action control used by Minesweeper directly below the
# six-record table.
replace_once(
    "  const auto labels =\n"
    "      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));\n",
    "  const Rect resetButton = missileScoreResetButtonRect(renderer, mappedInput);\n"
    "  renderer.fillRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, false);\n"
    "  renderer.drawRoundedRect(resetButton.x, resetButton.y, resetButton.width, resetButton.height, 1, 6, true);\n"
    "  drawCenteredText(renderer, UI_10_FONT_ID, resetButton, \"Reinitialiser les scores\");\n\n"
    "  const auto labels =\n"
    "      mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), tr(STR_SELECT), tr(STR_DIR_UP), tr(STR_DIR_DOWN));\n",
    "reset button rendering",
)

# Distinct bench/trace names; gameplay/display behaviour is otherwise unchanged.
text = text.replace("/missile-command-bm5-polyscores-bench.csv", "/missile-command-bm6-reset-bench.csv")
text = text.replace("/missile-command-bm5-polyscores-trace.csv", "/missile-command-bm6-reset-trace.csv")
text = text.replace("bm5-polyscores-started", "bm6-reset-started")
text = text.replace("bm5-polyscores,%lu,%lu,%lu,%lu,%lu", "bm6-reset,%lu,%lu,%lu,%lu,%lu")
text = text.replace("MISSILE-BM5-POLYSCORES", "MISSILE-BM6-RESET")

CPP.write_text(text)
print("Missile BaseMode6: Minesweeper-style score reset button + confirmation applied")
