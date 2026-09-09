from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_pos] + replacement + text[end_pos:]


path = Path("src/activities/home/RssArticleCache.cpp")
cpp = path.read_text()

cpp = replace_once(
    cpp,
    '''enum class SourceCleanupProfile : uint8_t {
  GENERIC,
  FRANDROID,
  FUTURA,
  IPHONESOFT,
  IGENERATION,
  JEUXVIDEO,
  SCIENCE_ET_VIE,
};

''',
    '',
    "remove RSS publisher profile enum",
)

compact_rules = r'''struct BuiltInCleanupRules {
  const char* drop;
  const char* dropStart;
  const char* stop;
};

BuiltInCleanupRules builtInCleanupRules(const char* articleUrl, const bool enabled) {
  if (!enabled || !articleUrl || !articleUrl[0]) return {nullptr, nullptr, nullptr};
  const size_t length = std::strlen(articleUrl);
  if (rangeContainsInsensitive(articleUrl, 0, length, "frandroid.com")) {
    return {
        "télécharger frandroid gratuitement;telecharger frandroid gratuitement;voir tous ses articles;frandroid sur google news;signaler une erreur dans le texte",
        nullptr,
        "envie de retrouver les meilleurs articles de frandroid;signaler une erreur dans le texte",
    };
  }
  if (rangeContainsInsensitive(articleUrl, 0, length, "futura-sciences.com")) {
    return {
        "tags associés;tags associes;voir tous les tags;article rédigé par;article redige par;relu par;ajoutez futura à vos sources;ajoutez futura a vos sources;suivez-nous sur discover;suivez-nous sur google actualités;suivez-nous sur google actualites;cela vous intéressera aussi;cela vous interessera aussi;[en vidéo];[en video]",
        nullptr,
        nullptr,
    };
  }
  if (rangeContainsInsensitive(articleUrl, 0, length, "iphonesoft.fr")) {
    return {nullptr, "écouter;ecouter;réagir;reagir", nullptr};
  }
  if (rangeContainsInsensitive(articleUrl, 0, length, "igen.fr")) {
    return {nullptr, "* * *", nullptr};
  }
  return {nullptr, nullptr, nullptr};
}

'''
cpp = replace_section(
    cpp,
    "SourceCleanupProfile sourceCleanupProfile(const char* articleUrl, const bool builtInProfile) {\n",
    "bool matchesCleanupRuleList(const char* rules, const char* line, const size_t length) {\n",
    compact_rules,
    "replace RSS publisher dispatch with compact shared rule table",
)

near_start_helper = r'''bool builtInNearStartNoise(const char* articleUrl, const char* line, const size_t length,
                           const bool enabled) {
  if (!enabled || !articleUrl || !line || length == 0) return false;
  const size_t urlLength = std::strlen(articleUrl);
  if (rangeContainsInsensitive(articleUrl, 0, urlLength, "iphonesoft.fr")) {
    return (length < 100 && rangeContainsInsensitive(line, 0, length, " coms")) ||
           (length < 180 && rangeContainsInsensitive(line, 0, length, " > "));
  }
  if (rangeContainsInsensitive(articleUrl, 0, urlLength, "igen.fr")) {
    return length < 120 && rangeContainsInsensitive(line, 0, length, " • ");
  }
  return false;
}

'''
cpp = replace_section(
    cpp,
    "bool isSourceSpecificNoise(const SourceCleanupProfile profile, const char* line, const size_t length,\n",
    "bool isSourceStopLine(const SourceCleanupProfile profile, const char* line, const size_t length,\n",
    near_start_helper,
    "replace RSS source-specific switch",
)

cpp = replace_section(
    cpp,
    "bool isSourceStopLine(const SourceCleanupProfile profile, const char* line, const size_t length,\n",
    "uint64_t normalizedLineHash(const char* line, const size_t length) {\n",
    '',
    "remove RSS source stop switch",
)

cpp = replace_once(
    cpp,
    '''bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle, const char* articleSummary,
                        const char* sourceName, const SourceCleanupProfile profile, const bool nearStart) {
''',
    '''bool looksLikeNoiseLine(const char* line, const size_t length, const char* articleTitle, const char* articleSummary,
                        const char* sourceName, const bool nearStart) {
''',
    "simplify RSS generic noise signature",
)
cpp = replace_once(
    cpp,
    '''  return isSourceSpecificNoise(profile, line, length, nearStart);
''',
    '''  return false;
''',
    "remove RSS profile tail dispatch",
)

cpp = replace_once(
    cpp,
    '''  const SourceCleanupProfile profile = sourceCleanupProfile(articleUrl, builtInProfile);

  while (read < length) {
''',
    '''  const BuiltInCleanupRules builtInRules = builtInCleanupRules(articleUrl, builtInProfile);

  while (read < length) {
''',
    "use compact RSS built-in rules",
)

cpp = replace_once(
    cpp,
    '''      if (lineLength > 0 &&
          (isSourceStopLine(profile, text + start, lineLength, keptLines) ||
           (keptLines >= 2 && matchesCleanupRuleList(stopRules, text + start, lineLength)))) {
        break;
      }
      const bool fileDrop = lineLength == 0 || matchesCleanupRuleList(dropRules, text + start, lineLength) ||
                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength)) ||
                            (nearStart && isFigaroArticle(articleUrl) &&
                             isStandaloneFigaroNoise(text + start, lineLength));
      if (!fileDrop &&
          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, profile, nearStart)) {
''',
    '''      if (lineLength > 0 && keptLines >= 2 &&
          (matchesCleanupRuleList(builtInRules.stop, text + start, lineLength) ||
           matchesCleanupRuleList(stopRules, text + start, lineLength))) {
        break;
      }
      const bool fileDrop = lineLength == 0 ||
                            matchesCleanupRuleList(builtInRules.drop, text + start, lineLength) ||
                            matchesCleanupRuleList(dropRules, text + start, lineLength) ||
                            (nearStart && matchesCleanupRuleList(builtInRules.dropStart, text + start, lineLength)) ||
                            (nearStart && matchesCleanupRuleList(dropStartRules, text + start, lineLength)) ||
                            (nearStart && builtInNearStartNoise(articleUrl, text + start, lineLength, builtInProfile)) ||
                            (nearStart && isFigaroArticle(articleUrl) &&
                             isStandaloneFigaroNoise(text + start, lineLength));
      if (!fileDrop &&
          !looksLikeNoiseLine(text + start, lineLength, articleTitle, articleSummary, sourceName, nearStart)) {
''',
    "route RSS publisher and feeds.txt rules through one matcher",
)

if "SourceCleanupProfile" in cpp or "isSourceSpecificNoise" in cpp or "isSourceStopLine" in cpp:
    raise RuntimeError("RSS legacy publisher profile machinery remains")
if "builtInCleanupRules(articleUrl, builtInProfile)" not in cpp:
    raise RuntimeError("RSS compact publisher rules are not active")
if "matchesCleanupRuleList(builtInRules.drop" not in cpp:
    raise RuntimeError("RSS built-in rules are not sharing the feeds.txt matcher")
if "figaroPreamblePrefix" not in cpp or "isStandaloneFigaroNoise" not in cpp:
    raise RuntimeError("RSS Figaro structural cleanup was lost")

path.write_text(cpp)
print("Consolidated RSS publisher cleanup into the feeds.txt rule matcher while preserving Figaro structural cleanup.")
