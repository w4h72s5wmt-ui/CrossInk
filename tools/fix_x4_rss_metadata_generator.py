from pathlib import Path

path = Path("tools/x4_rss_metadata_opt_candidate.py")
text = path.read_text()

fixes = {
    '''  return true;\n}\n\nsize_t sanitizeFallbackMarkup(char* text, const size_t length) {\n''',\n    "cache body-state helpers")''': '''  return true;\n}\n\n''',\n    "cache body-state helpers")''',
    '''void RssNewsActivity::releaseFeedBuffer() {\n  feedItems = nullptr;\n  feedStorage.reset();\n}\n\nvoid RssNewsActivity::loadSources() {\n''',\n    "runtime RSS buffers")''': '''void RssNewsActivity::releaseFeedBuffer() {\n  feedItems = nullptr;\n  feedStorage.reset();\n}\n\n''',\n    "runtime RSS buffers")''',
    '''  for (size_t i = 0; i < addCount; ++i) articles[articleCount++] = merged[i];\n  return true;\n}\n\nvoid RssNewsActivity::rebuildDisplayOrder() {\n''',\n    "lightweight history merge")''': '''  for (size_t i = 0; i < addCount; ++i) articles[articleCount++] = merged[i];\n  return true;\n}\n\n''',\n    "lightweight history merge")''',
    '''  check(fetch(item, [&]{ return ++polls >= 3; }) == RC::CacheResult::CANCELLED && testFiles.empty(),\n        "cancellation during fetch");\n}\n\nstd::string readFile(const char* path) {\n''',\n    "cache/metadata tests")''': '''  check(fetch(item, [&]{ return ++polls >= 3; }) == RC::CacheResult::CANCELLED && testFiles.empty(),\n        "cancellation during fetch");\n}\n\n''',\n    "cache/metadata tests")''',
}

for old, new in fixes.items():
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"generator boundary fix expected one match, got {count}: {old[:60]!r}")
    text = text.replace(old, new, 1)

path.write_text(text)
print("Fixed candidate generator section boundaries.")
