from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")
text = CPP.read_text()

old_exit = '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  renderer.displayBuffer(HalDisplay::HALF_REFRESH);
  releaseWindowShadow();
  Activity::onExit();
}
'''
new_exit = '''void MissileCommandActivity::onExit() {
  if (viewMode_ == ViewMode::Playing && aliveCityCount() > 0) saveGame();
  saveHighScore();
  releaseWindowShadow();
  Activity::onExit();
}
'''
if old_exit not in text:
    raise SystemExit("onExit HALF scrub anchor not found")
text = text.replace(old_exit, new_exit, 1)

old_menu = '''void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();
  viewMode_ = ViewMode::Menu;
  selectedIndex_ = difficulty_;
'''
new_menu = '''void MissileCommandActivity::returnToMenu() {
  if (aliveCityCount() > 0) saveGame();
  viewMode_ = ViewMode::Menu;
  menuScrubPending_ = true;
  selectedIndex_ = difficulty_;
'''
if old_menu not in text:
    raise SystemExit("returnToMenu anchor not found")
text = text.replace(old_menu, new_menu, 1)

CPP.write_text(text)
print("Missile menu-return HALF scrub fixed; app exit restored to normal lifecycle")
