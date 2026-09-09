#!/usr/bin/env python3
from pathlib import Path

CPP = Path("src/activities/home/HomeActivity.cpp")
H = Path("src/activities/home/HomeActivity.h")

cpp = CPP.read_text()
h = H.read_text()

replacements = [
    ('#include "MinesweeperActivity.h"\n', '#include "MinesweeperActivity.h"\n#include "Game2048Activity.h"\n'),
    ('  Minesweeper,\n  RssNews,', '  Minesweeper,\n  Game2048,\n  RssNews,'),
    ('static constexpr int kCapacity = 11;', 'static constexpr int kCapacity = 12;'),
    ('  items.push({"Demineur", MinesweeperIcon, HomeMenuAction::Minesweeper});\n  items.push({"RSS", Library, HomeMenuAction::RssNews});',
     '  items.push({"Demineur", MinesweeperIcon, HomeMenuAction::Minesweeper});\n  items.push({"2048", Chart, HomeMenuAction::Game2048});\n  items.push({"RSS", Library, HomeMenuAction::RssNews});'),
    ('  int count = 6;  // File Browser, Recents, Notes, Demineur, File transfer, Settings',
     '  int count = 7;  // File Browser, Recents, Notes, Demineur, 2048, File transfer, Settings'),
    ('          case HomeMenuAction::Minesweeper:\n            onMinesweeperOpen();\n            break;\n          case HomeMenuAction::RssNews:',
     '          case HomeMenuAction::Minesweeper:\n            onMinesweeperOpen();\n            break;\n          case HomeMenuAction::Game2048:\n            onGame2048Open();\n            break;\n          case HomeMenuAction::RssNews:'),
    ('      case HomeMenuAction::Minesweeper:\n        onMinesweeperOpen();\n        break;\n      case HomeMenuAction::RssNews:',
     '      case HomeMenuAction::Minesweeper:\n        onMinesweeperOpen();\n        break;\n      case HomeMenuAction::Game2048:\n        onGame2048Open();\n        break;\n      case HomeMenuAction::RssNews:'),
    ('void HomeActivity::onMinesweeperOpen() {\n  startActivityForResult(std::make_unique<MinesweeperActivity>(renderer, mappedInput), [](const ActivityResult&) {});\n}\n\nvoid HomeActivity::onRssNewsOpen()',
     'void HomeActivity::onMinesweeperOpen() {\n  startActivityForResult(std::make_unique<MinesweeperActivity>(renderer, mappedInput), [](const ActivityResult&) {});\n}\n\nvoid HomeActivity::onGame2048Open() {\n  startActivityForResult(std::make_unique<Game2048Activity>(renderer, mappedInput), [](const ActivityResult&) {});\n}\n\nvoid HomeActivity::onRssNewsOpen()'),
]

for old, new in replacements:
    if old not in cpp:
        raise SystemExit(f"2048 integration anchor missing in HomeActivity.cpp: {old[:80]!r}")
    cpp = cpp.replace(old, new)

old_h = '  void onMinesweeperOpen();\n  void onRssNewsOpen();'
new_h = '  void onMinesweeperOpen();\n  void onGame2048Open();\n  void onRssNewsOpen();'
if old_h not in h:
    raise SystemExit("2048 integration anchor missing in HomeActivity.h")
h = h.replace(old_h, new_h)

# Explicit validation: the app must be visible in both full and minimal menus,
# dispatched from both menu interaction paths, and have a launcher method.
checks = {
    'menu entries': cpp.count('{"2048", Chart, HomeMenuAction::Game2048}') >= 2,
    'action enum': 'Game2048,' in cpp,
    'launcher include': '#include "Game2048Activity.h"' in cpp,
    'launcher method': 'void HomeActivity::onGame2048Open()' in cpp,
    'launcher declaration': 'void onGame2048Open();' in h,
    'dispatches': cpp.count('onGame2048Open();') >= 2,
    'capacity': 'kCapacity = 12' in cpp,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('2048 integration validation failed: ' + ', '.join(failed))

CPP.write_text(cpp)
H.write_text(h)
print('Applied and validated X4 Pro 2048 menu + launcher integration.')
