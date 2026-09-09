from pathlib import Path

path = Path("src/activities/home/RssArticleCache.cpp")
text = path.read_text()
duplicate = '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\nbool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n'''
replacement = '''bool isFollowCallToAction(const char* line, const size_t length, const char* sourceName) {\n'''
count = text.count(duplicate)
if count != 1:
    raise RuntimeError(f"RSS duplicated helper signature: expected 1 match, found {count}")
path.write_text(text.replace(duplicate, replacement, 1))
print("Removed duplicated RSS cleanup helper signature.")
