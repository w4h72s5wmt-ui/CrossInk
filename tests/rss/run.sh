#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
binary=$(mktemp /tmp/crossink-rss-test.XXXXXX)
trap 'rm -f "$binary"' EXIT HUP INT TERM
for source in test_article_cache test_fetch_diagnostics; do
  ${CXX:-g++} -std=c++20 -O1 -g -Wall -Wextra -Werror -Wno-unused-function \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    -I"$root/tests/rss/stubs" -I"$root/src" \
    "$root/tests/rss/$source.cpp" "$root/src/activities/home/RssFetchDiagnostics.cpp" -o "$binary"
  ASAN_OPTIONS=detect_leaks=1 "$binary" "$@"
done
