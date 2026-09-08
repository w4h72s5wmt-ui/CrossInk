from pathlib import Path
import runpy

patch_path = Path("tools/apply_rss_offline_patch.py")
text = patch_path.read_text()
old = '''cpp = replace_once(
    cpp,
    "  articleLineOffset = 0;\\n  openArticleIndex = MAX_ARTICLES;",
    "  articleLineOffset = 0;\\n  articlePageLines = 8;\\n  openArticleIndex = MAX_ARTICLES;",
    "article page size reset",
)
'''
new = '''reset_old = "  articleLineOffset = 0;\\n  openArticleIndex = MAX_ARTICLES;"
reset_new = "  articleLineOffset = 0;\\n  articlePageLines = 8;\\n  openArticleIndex = MAX_ARTICLES;"
reset_count = cpp.count(reset_old)
if reset_count < 1:
    raise SystemExit("Expected at least one article page reset block")
cpp = cpp.replace(reset_old, reset_new)
'''
if old not in text:
    raise SystemExit("Could not adjust RSS patch guard")
patch_path.write_text(text.replace(old, new, 1))
runpy.run_path(str(patch_path), run_name="__main__")
