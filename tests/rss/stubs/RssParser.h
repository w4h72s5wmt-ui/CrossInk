#pragma once
// Host model of the RSS record; these tests do not measure target ABI/RAM.
struct RssItem {
  char title[256] = {};
  char link[512] = {};
  char published[64] = {};
  char summary[4096] = {};
};
