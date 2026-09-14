from pathlib import Path

p = Path("freeink-sdk/libs/display/FreeInkDisplay/src/FreeInkDisplay.cpp")
text = p.read_text()
old = "void FreeInkDisplay::displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows,\n                                         uint16_t tileW, uint16_t tileH, uint16_t bboxX, uint16_t bboxY,\n                                         uint16_t bboxW, uint16_t bboxH, bool turnOffScreen) {\n  cancelGrayscalePass();\n"
new = "void FreeInkDisplay::displaySparseWindow(const uint8_t* tileMask, uint16_t tileCols, uint16_t tileRows,\n                                         uint16_t tileW, uint16_t tileH, uint16_t bboxX, uint16_t bboxY,\n                                         uint16_t bboxW, uint16_t bboxH, bool turnOffScreen) {\n"
if old not in text:
    raise SystemExit("sparse facade anchor not found")
p.write_text(text.replace(old, new, 1))
print("Sparse facade aligned with pinned FreeInk SDK: removed unavailable cancelGrayscalePass()")
