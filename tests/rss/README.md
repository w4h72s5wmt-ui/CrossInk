# RSS article extraction/cache regression tests

Run `sh tests/rss/run.sh` **after** all application integration steps from
`.github/workflows/notes-build.yml`. The test includes the generated production
`RssArticleCache.cpp`, including the app-local HTML and cache-policy files.
Only network, SD storage and allocation are doubled on the host. No embedded
code is altered and these files are not part of the X4 Pro binary.

The suite checks preservation of layout containers, scoped class/id matching,
noise subtree removal, quoted attributes, raw scripts, nested article tags,
body-size bounds, summary-only retry, cache invalidation, cancellation,
allocation failures, SD failures, and strict Figaro AUTH behavior.
It also executes 500 deterministic malformed-HTML cases and all prefixes of a
quoted-attribute fixture under AddressSanitizer/UndefinedBehaviorSanitizer.

Optional local reproduction with an HTML document supplied separately:

```sh
sh tests/rss/run.sh /path/to/article.html /path/to/feeds.txt /path/to/title.txt
```

This writes `frandroid-extracted.txt` and `frandroid-fixed.txt` in the working
directory. The user's HTML, screenshots, feed settings and authentication
material are not stored in this repository. The network doubles do not prove
what a publisher serves to the real X4 Pro, nor validate TLS on hardware.
