from pathlib import Path
p = Path('tests/rss/test_article_cache.cpp')
s = p.read_text()
old = '''<figcaption>iStock</figcaption>Jusqu'à présent.'''
new = '''<data>iStock</data>Jusqu'à présent.'''
if s.count(old) != 1:
    raise SystemExit(f'fixture match count: {s.count(old)}')
p.write_text(s.replace(old, new, 1))
print('RSS spacing validation fixture refined')
