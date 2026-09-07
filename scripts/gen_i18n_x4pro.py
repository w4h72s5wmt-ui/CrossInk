Import("env")

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
translations = root / "lib/I18n/translations"
filtered = root / ".pio/i18n-x4pro-selected"
filtered.mkdir(parents=True, exist_ok=True)

# Record every historical language code before filtering. Omitted languages stay
# available as compile-only enum identifiers so existing code such as RTL checks
# can still compile, but they are not selectable and carry no translation data.
all_codes = []
for yaml_path in sorted(translations.glob("*.yaml")):
    for line in yaml_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("_language_code:"):
            code = line.split(":", 1)[1].strip().strip('"')
            if code and code not in all_codes:
                all_codes.append(code)
            break

for old in filtered.glob("*.yaml"):
    old.unlink()

# Filter directly from the full build: keep these five languages from the start.
selected_files = (
    "english.yaml",
    "french.yaml",
    "german.yaml",
    "italian.yaml",
    "spanish.yaml",
)
for name in selected_files:
    shutil.copy2(translations / name, filtered / name)

subprocess.run(
    [
        sys.executable,
        str(root / "scripts/gen_i18n.py"),
        str(filtered),
        str(root / "lib/I18n"),
        "--strip-unused",
    ],
    cwd=root,
    check=True,
)

keys_path = root / "lib/I18n/I18nKeys.h"
text = keys_path.read_text(encoding="utf-8")

runtime_codes = {"EN", "FR", "ES", "DE", "IT"}
unavailable_codes = [code for code in all_codes if code not in runtime_codes]
enum_tail = "  _COUNT\n};"
if enum_tail not in text:
    raise RuntimeError("Generated Language enum layout changed")
compat_tail = "  _COUNT,\n  // Compile-only identifiers for languages omitted from this X4 Pro build.\n"
compat_tail += "".join(f"  {code},\n" for code in unavailable_codes)
compat_tail += "};"
text = text.replace(enum_tail, compat_tail, 1)

# Preserve the selected languages when migrating the historical language.bin
# layout. Any removed language safely falls back to English.
v1_codes = [
    "EN", "ES", "FR", "DE", "CS", "PT", "RU", "SV", "RO", "CA", "UK",
    "BE", "IT", "PL", "FI", "DA", "NL", "TR", "KK", "HU", "LT", "SI",
]
entries = [f"Language::{code}" if code in runtime_codes else "Language::EN" for code in v1_codes]
marker = "constexpr Language V1_LANGUAGES[] = {\n"
start = text.index(marker) + len(marker)
end = text.index("};", start)
text = text[:start] + "    " + ", ".join(entries) + ",\n" + text[end:]
keys_path.write_text(text, encoding="utf-8")

layout_hash = hashlib.sha256(keys_path.read_bytes()).hexdigest()[:16]
env.Append(CPPDEFINES=[f"I18N_LAYOUT_{layout_hash}"])
