#pragma once

#include <cstddef>

constexpr size_t RSS_TITLE_CAPACITY = 144;
constexpr size_t RSS_LINK_CAPACITY = 384;
constexpr size_t RSS_SUMMARY_CAPACITY = 4096;
constexpr size_t RSS_PUBLISHED_CAPACITY = 56;

struct RssItem {
  char title[RSS_TITLE_CAPACITY + 1] = {};
  char link[RSS_LINK_CAPACITY + 1] = {};
  char summary[RSS_SUMMARY_CAPACITY + 1] = {};
  char published[RSS_PUBLISHED_CAPACITY + 1] = {};
};
