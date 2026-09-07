Import("env")

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(env.subst("$PROJECT_DIR"))
translations = root / "lib/I18n/translations"
filtered = root / ".pio/i18n-fr-en"
filtered.mkdir(parents=True, exist_ok=True)

# Keep track of every historical language code so removed languages can remain
# valid compile-time identifiers without being exposed or storing translation data.
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
for name in ("english.yaml", "french.yaml"):
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

# EN and FR are the only valid runtime languages (_COUNT remains 2). Keep the
# removed enum names after _COUNT so code that mentions e.g. Language::AR or
# Language::HE still compiles. Those values fail normal runtime range checks,
# are not listed in the language selector, and have no string blobs/tables.
unavailable_codes = [code for code in all_codes if code not in {"EN", "FR"}]
enum_tail = "  _COUNT\n};"
if enum_tail not in text:
    raise RuntimeError("Generated Language enum layout changed")
compat_tail = "  _COUNT,\n  // Compile-only identifiers for languages omitted from this X4 Pro build.\n"
compat_tail += "".join(f"  {code},\n" for code in unavailable_codes)
compat_tail += "};"
text = text.replace(enum_tail, compat_tail, 1)

# The legacy language.bin migration table references the historical language
# enum. Map removed legacy languages safely to English while preserving old
# English and French values.
v1_codes = [
    "EN", "ES", "FR", "DE", "CS", "PT", "RU", "SV", "RO", "CA", "UK",
    "BE", "IT", "PL", "FI", "DA", "NL", "TR", "KK", "HU", "LT", "SI",
]
entries = [f"Language::{code}" if code in {"EN", "FR"} else "Language::EN" for code in v1_codes]
marker = "constexpr Language V1_LANGUAGES[] = {\n"
start = text.index(marker) + len(marker)
end = text.index("};", start)
text = text[:start] + "    " + ", ".join(entries) + ",\n" + text[end:]
keys_path.write_text(text, encoding="utf-8")

layout_hash = hashlib.sha256(keys_path.read_bytes()).hexdigest()[:16]
env.Append(CPPDEFINES=[f"I18N_LAYOUT_{layout_hash}"])
