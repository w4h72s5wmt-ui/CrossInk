from pathlib import Path

cpp_path = Path("src/activities/home/HomeActivity.cpp")
h_path = Path("src/activities/home/HomeActivity.h")
cpp = cpp_path.read_text()
h = h_path.read_text()


def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


cpp = once(
    cpp,
    '#include "Game2048Activity.h"\n',
    '#include "Game2048Activity.h"\n#include "MissileCommandActivity.h"\n',
    "Missile include",
)
cpp = once(
    cpp,
    "  Game2048,\n  RssNews,",
    "  Game2048,\n  MissileCommand,\n  RssNews,",
    "Home action enum",
)
cpp = once(
    cpp,
    "  static constexpr int kCapacity = 12;",
    "  static constexpr int kCapacity = 13;",
    "Home menu capacity",
)

old_menu = '  items.push({"2048", Chart, HomeMenuAction::Game2048});\n  items.push({"RSS", Library, HomeMenuAction::RssNews});'
new_menu = '  items.push({"2048", Chart, HomeMenuAction::Game2048});\n  items.push({"Missile Command", Chart, HomeMenuAction::MissileCommand});\n  items.push({"RSS", Library, HomeMenuAction::RssNews});'
if cpp.count(old_menu) != 2:
    raise SystemExit(f"Menu entries: expected 2 occurrences, found {cpp.count(old_menu)}")
cpp = cpp.replace(old_menu, new_menu)

cpp = once(
    cpp,
    "          case HomeMenuAction::Game2048:\n            onGame2048Open();\n            break;\n          case HomeMenuAction::RssNews:",
    "          case HomeMenuAction::Game2048:\n            onGame2048Open();\n            break;\n          case HomeMenuAction::MissileCommand:\n            onMissileCommandOpen();\n            break;\n          case HomeMenuAction::RssNews:",
    "Touch/select switch",
)
cpp = once(
    cpp,
    "      case HomeMenuAction::Game2048:\n        onGame2048Open();\n        break;\n      case HomeMenuAction::RssNews:",
    "      case HomeMenuAction::Game2048:\n        onGame2048Open();\n        break;\n      case HomeMenuAction::MissileCommand:\n        onMissileCommandOpen();\n        break;\n      case HomeMenuAction::RssNews:",
    "Button switch",
)

open_2048 = '''void HomeActivity::onGame2048Open() {
  startActivityForResult(std::make_unique<Game2048Activity>(renderer, mappedInput), [](const ActivityResult&) {});
}
'''
cpp = once(
    cpp,
    open_2048,
    open_2048
    + '''
void HomeActivity::onMissileCommandOpen() {
  startActivityForResult(std::make_unique<MissileCommandActivity>(renderer, mappedInput), [](const ActivityResult&) {});
}
''',
    "Open method",
)

h = once(
    h,
    "  void onGame2048Open();\n  void onRssNewsOpen();",
    "  void onGame2048Open();\n  void onMissileCommandOpen();\n  void onRssNewsOpen();",
    "Home header declaration",
)

cpp_path.write_text(cpp)
h_path.write_text(h)
