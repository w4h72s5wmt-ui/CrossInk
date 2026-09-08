from pathlib import Path

path = Path("src/activities/home/MinesweeperActivity.cpp")
text = path.read_text()
old = "  const bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n"
new = "  bool ok = readValue(file, magic) && readValue(file, grid) && readValue(file, stateFlags) &&\n"
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Minesweeper MSW5 loader mutability fix: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))
print("Applied MSW5 loader mutability compile fix.")
