from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/activities/home/MissileCommandActivity.cpp"
HDR = ROOT / "src/activities/home/MissileCommandActivity.h"
HOME_CPP = ROOT / "src/activities/home/HomeActivity.cpp"
HOME_HDR = ROOT / "src/activities/home/HomeActivity.h"
PIO = ROOT / "platformio.ini"


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"origin/x4-pro-missile-command:{path}"], cwd=ROOT, text=True
    )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)


HDR.write_text(git_show("src/activities/home/MissileCommandActivity.h"))
cpp = git_show("src/activities/home/MissileCommandActivity.cpp")
cpp = replace_once(cpp, "constexpr int64_t LOGIC_TICK_US = 40000;", "constexpr int64_t LOGIC_TICK_US = 33333;", "logic 30 Hz")
cpp = replace_once(cpp, "constexpr int64_t FRAME_INTERVAL_US = 120000;", "constexpr int64_t FRAME_INTERVAL_US = 33333;", "frame target 30 Hz")
cpp = replace_once(cpp, "constexpr int MAX_CATCHUP_TICKS = 5;", "constexpr int MAX_CATCHUP_TICKS = 8;", "catchup")
cpp = replace_once(cpp, "slot->speed = 34;", "slot->speed = 46;", "interceptor speed")

full_start = cpp.index("void MissileCommandActivity::drawFullPlayingScene() {")
incr_start = cpp.index("bool MissileCommandActivity::drawIncrementalPlayingScene() {", full_start)
render_start = cpp.index("\nvoid MissileCommandActivity::renderPlaying()", incr_start)

new_renderers = r'''void MissileCommandActivity::drawFullPlayingScene() {
  renderer.clearScreen();
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);
  if (mappedInput.hasTouchHardware()) {
    TouchHeaderBackButton::draw(renderer, uiTarget_, geometry.header, "Missile Command", false);
  } else {
    GUI.drawHeader(renderer, geometry.header, "Missile Command", nullptr, false);
  }

  renderer.drawRoundedRect(geometry.status.x, geometry.status.y, geometry.status.width, geometry.status.height, 1, 6, true);
  renderer.drawRect(geometry.field.x, geometry.field.y, geometry.field.width, geometry.field.height, 1, true);
  const auto labels = mappedInput.mapLabels(mappedInput.withBackArrow(tr(STR_BACK)), "", "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4, false);
  resetRenderCaches();
  sceneNeedsFullRedraw_ = false;
}

bool MissileCommandActivity::drawIncrementalPlayingScene() {
  const GameGeometry geometry = gameGeometry(renderer, mappedInput);

  // Recompose the whole gameplay field in RAM each visible frame. This clears
  // the previous missile positions while retaining FAST differential e-ink
  // refresh. No permanent trajectory accumulation remains.
  renderer.fillRect(geometry.field.x + 1, geometry.field.y + 1,
                    std::max(1, geometry.field.width - 2), std::max(1, geometry.field.height - 2), false);
  renderer.drawLine(geometry.field.x, geometry.groundY,
                    geometry.field.x + geometry.field.width - 1, geometry.groundY, 1, true);

  for (int i = 0; i < kCityCount; ++i) {
    if (!citiesAlive_[static_cast<size_t>(i)]) continue;
    const int x = geometry.field.x + geometry.field.width * (i + 1) / (kCityCount + 1);
    renderer.drawRect(x - 10, geometry.groundY - 11, 20, 11, 1, true);
    renderer.drawLine(x - 8, geometry.groundY - 11, x, geometry.groundY - 20, 1, true);
    renderer.drawLine(x, geometry.groundY - 20, x + 8, geometry.groundY - 11, 1, true);
  }

  for (int i = 0; i < kBatteryCount; ++i) {
    const int x = geometry.field.x + geometry.field.width * (i * 2 + 1) / (kBatteryCount * 2);
    const Rect battery{x - 18, geometry.groundY + 4, 36, 27};
    renderer.drawRoundedRect(battery.x, battery.y, battery.width, battery.height, 1, 4, true);
    char ammoText[8];
    std::snprintf(ammoText, sizeof(ammoText), "%u", static_cast<unsigned>(ammo_[static_cast<size_t>(i)]));
    drawCenteredText(renderer, UI_10_FONT_ID, battery, ammoText);
  }

  for (const auto& missile : enemies_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 45 ? static_cast<uint16_t>(missile.progress - 45) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.fillRect(x - 1, y - 1, 3, 3, true);
  }

  for (const auto& missile : players_) {
    if (!missile.active) continue;
    const int x = lerpInt(missile.startX, missile.targetX, missile.progress);
    const int y = lerpInt(missile.startY, missile.targetY, missile.progress);
    const uint16_t tailProgress = missile.progress > 70 ? static_cast<uint16_t>(missile.progress - 70) : 0;
    renderer.drawLine(lerpInt(missile.startX, missile.targetX, tailProgress),
                      lerpInt(missile.startY, missile.targetY, tailProgress), x, y, 1, true);
    renderer.drawRect(x - 2, y - 2, 5, 5, 1, true);
  }

  for (const auto& explosion : explosions_) {
    if (explosion.active) drawExplosion(renderer, explosion.x, explosion.y, explosionRadius(explosion.phase));
  }

  renderer.fillRect(geometry.status.x + 2, geometry.status.y + 2,
                    geometry.status.width - 4, geometry.status.height - 4, false);
  char status[96];
  std::snprintf(status, sizeof(status), "Score %lu   Record %lu   Vague %u   Villes %d",
                static_cast<unsigned long>(score_), static_cast<unsigned long>(highScore_),
                static_cast<unsigned>(wave_), aliveCityCount());
  drawCenteredText(renderer, UI_10_FONT_ID, geometry.status, status);
  return true;
}
'''
cpp = cpp[:full_start] + new_renderers + cpp[render_start:]
CPP.write_text(cpp)

home = HOME_CPP.read_text()
home = replace_once(home, '#include "Game2048Activity.h"\n', '#include "Game2048Activity.h"\n#include "MissileCommandActivity.h"\n', "home include")
home = replace_once(home, '  Game2048,\n  RssNews,', '  Game2048,\n  MissileCommand,\n  RssNews,', "home enum")
home = replace_once(home, 'static constexpr int kCapacity = 12;', 'static constexpr int kCapacity = 13;', "menu capacity")
home = replace_once(home, 'constexpr uint16_t CAROUSEL_CACHE_VERSION = 6;', 'constexpr uint16_t CAROUSEL_CACHE_VERSION = 7;', "carousel cache version")
home = replace_once(home, 'int count = 7;  // File Browser, Recents, Notes, Demineur, 2048, File transfer, Settings',
                    'int count = 8;  // File Browser, Recents, Notes, Demineur, 2048, Missile Command, File transfer, Settings',
                    "menu count")

# Insert the menu row after every 2048 row (normal and minimal menus).
lines = []
inserted_menu_rows = 0
for line in home.splitlines(keepends=True):
    lines.append(line)
    if 'items.push({"2048", Chart, HomeMenuAction::Game2048});' in line:
        indent = line[:len(line) - len(line.lstrip())]
        lines.append(indent + 'items.push({"Missile Command", Chart, HomeMenuAction::MissileCommand});\n')
        inserted_menu_rows += 1
home = ''.join(lines)
if inserted_menu_rows < 2:
    raise RuntimeError(f"expected two Home menu insertions, got {inserted_menu_rows}")

# Build 304 has several Home dispatch switches with different indentation.
# Inject the Missile case immediately before every RSS case instead of matching
# a whole multi-line block inherited from older builds.
lines = []
inserted_switches = 0
for line in home.splitlines(keepends=True):
    if line.strip() == 'case HomeMenuAction::RssNews:':
        indent = line[:len(line) - len(line.lstrip())]
        lines.append(indent + 'case HomeMenuAction::MissileCommand:\n')
        lines.append(indent + '  onMissileCommandOpen();\n')
        lines.append(indent + '  break;\n')
        inserted_switches += 1
    lines.append(line)
home = ''.join(lines)
if inserted_switches < 2:
    raise RuntimeError(f"expected Home dispatch insertions, got {inserted_switches}")

impl_old = "void HomeActivity::onGame2048Open() {\n  startActivityForResult(std::make_unique<Game2048Activity>(renderer, mappedInput), [](const ActivityResult&) {});\n}\n"
impl_new = impl_old + "\nvoid HomeActivity::onMissileCommandOpen() {\n  startActivityForResult(std::make_unique<MissileCommandActivity>(renderer, mappedInput), [](const ActivityResult&) {});\n}\n"
home = replace_once(home, impl_old, impl_new, "launcher implementation")
HOME_CPP.write_text(home)

home_h = HOME_HDR.read_text()
home_h = replace_once(home_h, '  void onGame2048Open();\n', '  void onGame2048Open();\n  void onMissileCommandOpen();\n', "launcher declaration")
HOME_HDR.write_text(home_h)

# App-specific environment only: standard build 304 x4-pro remains unchanged.
pio = PIO.read_text()
if '[env:x4-pro-missile]' not in pio:
    pio += '''\n\n; --- Missile Command X4 Pro -------------------------------------------------\n; App-specific target. FreeInk documents this SSD1677 DU shortcut at ~77 ms.\n; UC8179/UC8279 X4 Pro batches stay on their own driver path.\n[env:x4-pro-missile]\nextends = env:x4-pro\nbuild_flags =\n  ${env:x4-pro.build_flags}\n  -DFREEINK_X4PRO_FAST_DU_SHORTCUT\n'''
PIO.write_text(pio)

print(f"Missile Command integrated on build 304; menu rows={inserted_menu_rows}, switches={inserted_switches}")
