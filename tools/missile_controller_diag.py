from pathlib import Path

CPP = Path("src/activities/home/MissileCommandActivity.cpp")


def one(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)


cpp = CPP.read_text()

cpp = one(
    cpp,
    '#include <GfxRenderer.h>\n',
    '#include <BoardConfig.h>\n#include <GfxRenderer.h>\n',
    'BoardConfig include',
)

cpp = one(
    cpp,
    'constexpr const char BENCHMARK_PATH[] = "/missile-command-benchmark.csv";\n',
    'constexpr const char BENCHMARK_PATH[] = "/missile-command-benchmark.csv";\n'
    'constexpr const char CONTROLLER_DIAG_PATH[] = "/missile-command-controller.txt";\n',
    'controller diag path',
)

helper = r'''
const char* activeDisplayControllerName() {
  switch (BoardConfig::ACTIVE.displayController) {
    case BoardConfig::DisplayController::SSD1677: return "SSD1677";
    case BoardConfig::DisplayController::UC8179: return "UC8179";
    case BoardConfig::DisplayController::UC8279: return "UC8279";
    default: return "OTHER";
  }
}

void writeControllerDiagnostic() {
  FsFile file;
  if (!Storage.openFileForWrite("MISSILE CTRL", CONTROLLER_DIAG_PATH, file)) return;

#ifdef FREEINK_X4PRO_FAST_DU_SHORTCUT
  constexpr unsigned fastDuShortcut = 1;
#else
  constexpr unsigned fastDuShortcut = 0;
#endif
#if FREEINK_DRIVER_SSD1677
  constexpr unsigned ssd1677Compiled = 1;
#else
  constexpr unsigned ssd1677Compiled = 0;
#endif
#if FREEINK_DRIVER_UC8179
  constexpr unsigned uc8179Compiled = 1;
#else
  constexpr unsigned uc8179Compiled = 0;
#endif
#if FREEINK_DRIVER_UC8279_X4
  constexpr unsigned uc8279Compiled = 1;
#else
  constexpr unsigned uc8279Compiled = 0;
#endif

  char text[320];
  const int length = std::snprintf(
      text, sizeof(text),
      "controller=%s\ncontroller_id=%u\nboard_id=%u\nwidth=%u\nheight=%u\nspi_hz=%lu\n"
      "x4pro_fast_du_shortcut=%u\nssd1677_compiled=%u\nuc8179_compiled=%u\nuc8279_x4_compiled=%u\n",
      activeDisplayControllerName(), static_cast<unsigned>(BoardConfig::ACTIVE.displayController),
      static_cast<unsigned>(BoardConfig::ACTIVE.board), static_cast<unsigned>(BoardConfig::ACTIVE.displayWidth),
      static_cast<unsigned>(BoardConfig::ACTIVE.displayHeight),
      static_cast<unsigned long>(BoardConfig::ACTIVE.displaySpiHz), fastDuShortcut, ssd1677Compiled,
      uc8179Compiled, uc8279Compiled);

  if (length > 0 && length < static_cast<int>(sizeof(text))) {
    file.write(reinterpret_cast<const uint8_t*>(text), static_cast<size_t>(length));
    file.sync();
  }
  file.close();
}

'''

cpp = one(
    cpp,
    'Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n',
    helper + 'Rect headerRect(const GfxRenderer& renderer, const MappedInputManager& mappedInput) {\n',
    'controller helper',
)

cpp = one(
    cpp,
    '  benchmarkSessionStartUs_ = esp_timer_get_time();\n  openBenchmarkLog();\n',
    '  benchmarkSessionStartUs_ = esp_timer_get_time();\n  writeControllerDiagnostic();\n  openBenchmarkLog();\n',
    'write controller diagnostic on enter',
)

CPP.write_text(cpp)
print("Missile Command controller diagnostic staged")
