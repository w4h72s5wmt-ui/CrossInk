from pathlib import Path


rss_path = Path("src/activities/home/RssNewsActivity.cpp")
rss = rss_path.read_text()

# apply_x4_rss_feed_config.py injects C++ through a Python triple-quoted string.
# In that context, \0 and \n are interpreted by Python before reaching the C++
# source. Restore the two intended C++ escape sequences explicitly.
bad_null = "buffer[static_cast<size_t>(read)] = '\0';"
good_null = "buffer[static_cast<size_t>(read)] = '\\0';"
if bad_null not in rss:
    raise RuntimeError("RSS feed config NUL escape pattern not found")
rss = rss.replace(bad_null, good_null, 1)

bad_newline = "const size_t lineEnd = config.find('\n', lineStart);"
good_newline = "const size_t lineEnd = config.find('\\n', lineStart);"
if bad_newline not in rss:
    raise RuntimeError("RSS feed config newline escape pattern not found")
rss = rss.replace(bad_newline, good_newline, 1)

if "\x00" in rss:
    raise RuntimeError("RSS generated C++ still contains an embedded NUL")
if good_newline not in rss:
    raise RuntimeError("RSS generated C++ newline delimiter is still malformed")

rss_path.write_text(rss)
print("Restored RSS feeds.txt parser C++ escape sequences.")
