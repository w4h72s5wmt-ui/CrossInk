from pathlib import Path
import runpy

patch_path = Path("tools/apply_rss_offline_patch.py")
text = patch_path.read_text()

reset_block = '''cpp = replace_once(
    cpp,
    "  articleLineOffset = 0;\\n  openArticleIndex = MAX_ARTICLES;",
    "  articleLineOffset = 0;\\n  articlePageLines = 8;\\n  openArticleIndex = MAX_ARTICLES;",
    "article page size reset",
)
'''
reset_replacement = '''reset_old = "  articleLineOffset = 0;\\n  openArticleIndex = MAX_ARTICLES;"
reset_new = "  articleLineOffset = 0;\\n  articlePageLines = 8;\\n  openArticleIndex = MAX_ARTICLES;"
if reset_old not in cpp:
    raise SystemExit("Expected at least one article page reset block")
cpp = cpp.replace(reset_old, reset_new)
'''
if reset_block not in text:
    raise SystemExit("Could not adjust RSS reset guard")
text = text.replace(reset_block, reset_replacement, 1)

paging_block = '''cpp = replace_once(
    cpp,
    "      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(static_cast<int>(articlePageLines));",
    "button next page",
)
cpp = replace_once(
    cpp,
    "      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(-static_cast<int>(articlePageLines));",
    "button previous page",
)
cpp = replace_once(
    cpp,
    "      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));\\n    } else if (swipe == MappedInputManager::SwipeDir::Down) {\\n      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));",
    "      scrollArticle(static_cast<int>(articlePageLines));\\n    } else if (swipe == MappedInputManager::SwipeDir::Down) {\\n      scrollArticle(-static_cast<int>(articlePageLines));",
    "swipe article paging",
)
'''
paging_replacement = '''paging_positive = "      scrollArticle(static_cast<int>(ARTICLE_PAGE_LINES));"
paging_negative = "      scrollArticle(-static_cast<int>(ARTICLE_PAGE_LINES));"
if paging_positive not in cpp or paging_negative not in cpp:
    raise SystemExit("Expected RSS article paging blocks")
cpp = cpp.replace(paging_positive, "      scrollArticle(static_cast<int>(articlePageLines));")
cpp = cpp.replace(paging_negative, "      scrollArticle(-static_cast<int>(articlePageLines));")
'''
if paging_block not in text:
    raise SystemExit("Could not adjust RSS paging guards")
text = text.replace(paging_block, paging_replacement, 1)

patch_path.write_text(text)
runpy.run_path(str(patch_path), run_name="__main__")
