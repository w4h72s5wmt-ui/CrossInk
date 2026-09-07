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

# The legacy language.bin migration table references the historical language
# enum. This personal X4 Pro build only compiles EN/FR, so map removed legacy
# languages safely to English while preserving old English and French values.
keys_path = root / "lib/I18n/I18nKeys.h"
text = keys_path.read_text(encoding="utf-8")
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
