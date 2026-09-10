#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
binary=$(mktemp /tmp/crossink-rss-test.XXXXXX)
trap 'rm -f "$binary"' EXIT HUP INT TERM
${CXX:-g++} -std=c++20 -O1 -g -Wall -Wextra -Werror -Wno-unused-function \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I"$root/tests/rss/stubs" -I"$root/src" \
  "$root/tests/rss/test_article_cache.cpp" -o "$binary"
ASAN_OPTIONS=detect_leaks=1 "$binary" "$@"
