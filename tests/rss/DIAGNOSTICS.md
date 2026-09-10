# RSS fetch diagnostics (X4 Pro)

This development build preserves Build 225 extraction, cache format XRSS5,
network timeouts and authentication policy. It adds a temporary report at
`/RSS/rss_diagnostic.tsv`, overwritten at each manual refresh and bounded to
128 KiB. Existing body files are not invalidated again.

Perform one manual RSS refresh, close RSS, then copy the TSV from the SD card.
Capture fresh or previously failed articles: `cache-hit` rows do not exercise
the network or extractor. The report never contains cookie/header values,
article text, URL paths or queries. Host and a non-reversible-in-practice URL
correlation hash are included; the hash is not a cryptographic anonymization.

Public transports expose only DownloadError and delivered chunks through the
unchanged shared HttpDownloader API: HTTP -1 means unknown, not HTTP failure.
Their rows distinguish fetch, html-capacity, extraction, text-capacity,
cleaner, body-write, and body-ready. Success is not proof of editorial completeness.
Figaro additionally records HTTP status, ESP-IDF/read error, errno/TLS fields,
open/header/body duration and whether the article closing marker was reached.

No cookies or browser session exports are needed. SD report errors disable
reporting and do not change the fetch result. Reporting does perform small
synchronous SD writes at attempt completion, so total synchronization time can
be slightly affected; no writes occur per downloaded chunk.

`sh tests/rss/run.sh` runs the existing generated-cache suite and the reporter
privacy, bounds, wraparound and SD-error checks with ASan/UBSan. Real network
behavior must still be checked on the X4 Pro.
