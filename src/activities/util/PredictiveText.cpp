#include "PredictiveText.h"

#include <HalStorage.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>

namespace {
constexpr const char kPersonalDir[] = "/.crosspoint";
constexpr const char kPersonalPath[] = "/.crosspoint/notes-predictive.txt";
constexpr size_t kMaxPersonalWords = 128;
constexpr size_t kMaxPersonalFileBytes = 16384;

// Ordered roughly by usefulness/frequency. Matching is accent-insensitive, so
// typing "etr" can still propose "être".
constexpr const char* kFrenchWords[] = {
    "bonjour", "bonsoir", "bonne", "bon", "merci", "oui", "non", "avec", "sans", "pour", "dans", "sur", "sous",
    "entre", "vers", "chez", "depuis", "avant", "après", "pendant", "comme", "mais", "donc", "car", "parce", "que",
    "qui", "quoi", "quand", "comment", "pourquoi", "où", "quel", "quelle", "quels", "quelles", "un", "une", "des",
    "le", "la", "les", "du", "de", "au", "aux", "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta",
    "tes", "son", "sa", "ses", "notre", "nos", "votre", "vos", "leur", "leurs", "je", "tu", "il", "elle", "on",
    "nous", "vous", "ils", "elles", "me", "te", "se", "moi", "toi", "lui", "eux", "être", "avoir", "faire", "aller",
    "venir", "voir", "dire", "prendre", "mettre", "pouvoir", "vouloir", "devoir", "savoir", "penser", "croire", "trouver",
    "donner", "demander", "répondre", "parler", "écrire", "lire", "ouvrir", "fermer", "ajouter", "supprimer", "modifier",
    "enregistrer", "sauvegarder", "chercher", "rechercher", "utiliser", "essayer", "tester", "commencer", "continuer", "finir",
    "arrêter", "attendre", "revenir", "partir", "arriver", "passer", "rester", "laisser", "garder", "changer", "choisir",
    "aimer", "préférer", "besoin", "envie", "possible", "impossible", "facile", "difficile", "simple", "rapide", "lent",
    "petit", "petite", "grand", "grande", "nouveau", "nouvelle", "ancien", "ancienne", "premier", "première", "dernier",
    "dernière", "autre", "même", "beaucoup", "peu", "plus", "moins", "très", "trop", "assez", "encore", "déjà", "toujours",
    "jamais", "souvent", "parfois", "maintenant", "aujourd'hui", "demain", "hier", "matin", "midi", "soir", "nuit", "jour",
    "semaine", "mois", "année", "heure", "minute", "temps", "moment", "fois", "fois-ci", "date", "rendez-vous", "travail",
    "maison", "école", "bureau", "famille", "ami", "amie", "enfant", "enfants", "personne", "gens", "homme", "femme",
    "nom", "prénom", "adresse", "téléphone", "message", "mail", "email", "réponse", "question", "idée", "information",
    "important", "importante", "urgent", "urgente", "problème", "solution", "erreur", "résultat", "exemple", "liste", "texte",
    "note", "notes", "titre", "mot", "mots", "phrase", "page", "document", "fichier", "dossier", "écran", "clavier", "bouton",
    "retour", "menu", "application", "version", "mise", "jour", "réglage", "option", "mode", "grille", "score", "points",
    "mine", "mines", "drapeau", "drapeaux", "partie", "jeu", "jouer", "gagner", "perdre", "annuler", "continuer", "nouvelle",
    "ordinateur", "ordinateurs", "internet", "réseau", "wifi", "connexion", "serveur", "système", "logiciel", "programme",
    "code", "projet", "build", "compilation", "firmware", "binaire", "fichier", "télécharger", "installer", "copier", "coller",
    "photo", "image", "vidéo", "musique", "livre", "lecture", "liseuse", "chapitre", "auteur", "histoire", "français",
    "française", "langue", "mot", "dictionnaire", "prédiction", "suggestion", "correction", "écriture", "écrire", "lire",
    "manger", "boire", "acheter", "vendre", "payer", "prix", "argent", "magasin", "commande", "livraison", "voiture", "train",
    "avion", "route", "ville", "pays", "voyage", "vacances", "hôtel", "restaurant", "café", "eau", "pain", "repas",
    "santé", "médecin", "sport", "marcher", "courir", "dormir", "réveiller", "fatigué", "content", "contente", "heureux",
    "heureuse", "désolé", "désolée", "d'accord", "certain", "certaine", "peut-être", "vraiment", "exactement", "simplement",
    "rapidement", "normalement", "finalement", "ensemble", "seul", "seule", "tout", "toute", "tous", "toutes", "rien",
    "quelque", "quelques", "chaque", "aucun", "aucune", "plusieurs", "premièrement", "ensuite", "puis", "enfin", "voici",
    "voilà", "ici", "là", "dessus", "dessous", "dedans", "dehors", "gauche", "droite", "haut", "bas", "centre", "centrer",
    "aligner", "vertical", "verticalement", "horizontal", "horizontalement", "clair", "claire", "foncé", "foncée", "gris", "noir",
    "blanc", "afficher", "affichage", "interface", "sélection", "sélectionner", "toucher", "tactile", "appuyer", "ouvrir", "fermer",
    "créer", "création", "modifier", "modification", "supprimer", "suppression", "sauvegarde", "recherche", "résultat", "meilleur",
    "meilleure", "meilleurs", "score", "scores", "compteur", "nombre", "taille", "ligne", "colonne", "tableau", "entête",
    "dessiner", "rendre", "rafraîchir", "rafraîchissement", "mémoire", "stockage", "personnel", "personnelle", "fréquent", "fréquente",
    "utilisateur", "utilisatrice", "fonction", "fonctionner", "propre", "correct", "correcte", "bien", "mal", "mieux", "parfait",
    "parfaite", "super", "ok", "salut", "coucou", "bientôt", "probablement", "certainement", "également", "concernant", "rapport",
    "attention", "rappel", "objectif", "priorité", "prochaine", "prochain", "étape", "tâche", "faire", "fait", "faite", "faits",
    "prévoir", "prévu", "prévue", "terminé", "terminée", "disponible", "disponibles", "actuel", "actuelle", "actuellement",
};
constexpr size_t kFrenchWordCount = sizeof(kFrenchWords) / sizeof(kFrenchWords[0]);

bool asciiUpper(const unsigned char c) { return c >= 'A' && c <= 'Z'; }

char foldedInitial(const char* word) {
  if (!word || !*word) return '\0';
  const unsigned char c = static_cast<unsigned char>(word[0]);
  if (c < 0x80) {
    char ch = static_cast<char>(c);
    if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    return ch;
  }
  if (c == 0xC3 && word[1]) {
    switch (static_cast<unsigned char>(word[1])) {
      case 0x80: case 0x81: case 0x82: case 0x83: case 0x84: case 0x85:
      case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5: return 'a';
      case 0x87: case 0xA7: return 'c';
      case 0x88: case 0x89: case 0x8A: case 0x8B:
      case 0xA8: case 0xA9: case 0xAA: case 0xAB: return 'e';
      case 0x8C: case 0x8D: case 0x8E: case 0x8F:
      case 0xAC: case 0xAD: case 0xAE: case 0xAF: return 'i';
      case 0x92: case 0x93: case 0x94: case 0x95: case 0x96:
      case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: return 'o';
      case 0x99: case 0x9A: case 0x9B: case 0x9C:
      case 0xB9: case 0xBA: case 0xBB: case 0xBC: return 'u';
      case 0x9D: case 0xBD: case 0xBF: return 'y';
      default: break;
    }
  }
  return '\0';
}

}  // namespace

void PredictiveText::invalidateSuggestionCache() {
  ++revision_;
  if (revision_ == 0) revision_ = 1;
  cachedRevision_ = 0;
  cachedKey_.clear();
  cachedSuggestions_ = {};
}

bool PredictiveText::isWordByte(const unsigned char c) {
  return c >= 0x80 || (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

std::string PredictiveText::normalizeWord(std::string word) {
  size_t start = 0;
  while (start < word.size() && !isWordByte(static_cast<unsigned char>(word[start]))) ++start;
  size_t end = word.size();
  while (end > start && !isWordByte(static_cast<unsigned char>(word[end - 1]))) --end;
  word = word.substr(start, end - start);
  for (char& c : word) {
    const unsigned char uc = static_cast<unsigned char>(c);
    if (uc >= 'A' && uc <= 'Z') c = static_cast<char>(uc - 'A' + 'a');
  }
  if (word.size() > 40) word.resize(40);
  return word;
}

std::string PredictiveText::foldForMatch(const std::string& word) {
  std::string out;
  out.reserve(word.size());
  for (size_t i = 0; i < word.size();) {
    const unsigned char c = static_cast<unsigned char>(word[i]);
    if (c < 0x80) {
      char ch = static_cast<char>(c);
      if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
      out.push_back(ch);
      ++i;
      continue;
    }
    if (c == 0xC3 && i + 1 < word.size()) {
      const unsigned char n = static_cast<unsigned char>(word[i + 1]);
      switch (n) {
        case 0x80: case 0x81: case 0x82: case 0x83: case 0x84: case 0x85:
        case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5: out.push_back('a'); break;
        case 0x87: case 0xA7: out.push_back('c'); break;
        case 0x88: case 0x89: case 0x8A: case 0x8B:
        case 0xA8: case 0xA9: case 0xAA: case 0xAB: out.push_back('e'); break;
        case 0x8C: case 0x8D: case 0x8E: case 0x8F:
        case 0xAC: case 0xAD: case 0xAE: case 0xAF: out.push_back('i'); break;
        case 0x92: case 0x93: case 0x94: case 0x95: case 0x96:
        case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: out.push_back('o'); break;
        case 0x99: case 0x9A: case 0x9B: case 0x9C:
        case 0xB9: case 0xBA: case 0xBB: case 0xBC: out.push_back('u'); break;
        case 0x9D: case 0xBD: case 0xBF: out.push_back('y'); break;
        default: out.push_back(static_cast<char>(c)); out.push_back(static_cast<char>(n)); break;
      }
      i += 2;
      continue;
    }
    if (c == 0xC5 && i + 1 < word.size()) {
      const unsigned char n = static_cast<unsigned char>(word[i + 1]);
      if (n == 0x92 || n == 0x93) {
        out += "oe";
      } else {
        out.push_back(static_cast<char>(c));
        out.push_back(static_cast<char>(n));
      }
      i += 2;
      continue;
    }
    out.push_back(static_cast<char>(c));
    ++i;
  }
  return out;
}

void PredictiveText::currentWordRange(const std::string& text, size_t cursorPos, size_t& start, size_t& end) {
  cursorPos = std::min(cursorPos, text.size());
  start = cursorPos;
  while (start > 0 && isWordByte(static_cast<unsigned char>(text[start - 1]))) --start;
  end = cursorPos;
  while (end < text.size() && isWordByte(static_cast<unsigned char>(text[end]))) ++end;
}

bool PredictiveText::startsWithFolded(const std::string& word, const std::string& foldedPrefix) {
  const std::string folded = foldForMatch(word);
  return folded.size() >= foldedPrefix.size() && folded.compare(0, foldedPrefix.size(), foldedPrefix) == 0;
}

bool PredictiveText::isBuiltinWord(const std::string& normalizedWord) {
  const std::string folded = foldForMatch(normalizedWord);
  for (size_t i = 0; i < kFrenchWordCount; ++i) {
    if (foldForMatch(kFrenchWords[i]) == folded) return true;
  }
  return false;
}

void PredictiveText::addPersonalWord(const std::string& word, const uint16_t increment, const bool allowBuiltin) {
  const std::string normalized = normalizeWord(word);
  if (normalized.size() < 3 || normalized.size() > 40) return;
  bool hasLetter = false;
  for (const unsigned char c : normalized) {
    if (c >= 0x80 || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) {
      hasLetter = true;
      break;
    }
  }
  if (!hasLetter || (!allowBuiltin && isBuiltinWord(normalized))) return;

  const std::string folded = foldForMatch(normalized);
  for (auto& item : personal_) {
    if (foldForMatch(item.word) == folded) {
      if (increment > 0) {
        const uint32_t next = static_cast<uint32_t>(item.count) + increment;
        item.count = static_cast<uint16_t>(std::min<uint32_t>(next, 65535));
        dirty_ = true;
        invalidateSuggestionCache();
      }
      return;
    }
  }
  if (personal_.size() >= kMaxPersonalWords) return;
  personal_.push_back(PersonalWord{normalized, static_cast<uint16_t>(std::max<uint16_t>(1, increment))});
  dirty_ = true;
  invalidateSuggestionCache();
}

void PredictiveText::load() {
  personal_.clear();
  dirty_ = false;
  invalidateSuggestionCache();
  if (!Storage.exists(kPersonalPath)) return;

  FsFile file;
  if (!Storage.openFileForRead("PRED", std::string(kPersonalPath), file)) return;
  const uint32_t size = file.size();
  if (size == 0 || size > kMaxPersonalFileBytes) {
    file.close();
    return;
  }
  std::string data(size, '\0');
  if (file.read(data.data(), size) != static_cast<int>(size)) {
    file.close();
    return;
  }
  file.close();

  size_t pos = 0;
  while (pos < data.size() && personal_.size() < kMaxPersonalWords) {
    const size_t end = data.find('\n', pos);
    const std::string line = data.substr(pos, end == std::string::npos ? std::string::npos : end - pos);
    const size_t tab = line.find('\t');
    if (tab != std::string::npos && tab + 1 < line.size()) {
      const unsigned long parsed = std::strtoul(line.substr(0, tab).c_str(), nullptr, 10);
      addPersonalWord(line.substr(tab + 1), static_cast<uint16_t>(std::min<unsigned long>(65535, std::max<unsigned long>(1, parsed))), true);
    }
    if (end == std::string::npos) break;
    pos = end + 1;
  }
  dirty_ = false;
}

void PredictiveText::save() {
  if (!dirty_) return;
  Storage.mkdir(kPersonalDir);
  FsFile file = Storage.open(kPersonalPath, O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return;

  std::vector<PersonalWord> rows = personal_;
  std::sort(rows.begin(), rows.end(), [](const PersonalWord& a, const PersonalWord& b) {
    if (a.count != b.count) return a.count > b.count;
    return a.word < b.word;
  });
  std::string data;
  data.reserve(rows.size() * 18);
  for (const auto& item : rows) {
    data += std::to_string(item.count);
    data.push_back('\t');
    data += item.word;
    data.push_back('\n');
  }
  const size_t written = data.empty() ? 0 : file.write(reinterpret_cast<const uint8_t*>(data.data()), data.size());
  file.close();
  if (written == data.size()) dirty_ = false;
}

void PredictiveText::seedFromText(const std::string& text) {
  size_t start = 0;
  while (start < text.size()) {
    while (start < text.size() && !isWordByte(static_cast<unsigned char>(text[start]))) ++start;
    size_t end = start;
    while (end < text.size() && isWordByte(static_cast<unsigned char>(text[end]))) ++end;
    if (end > start) addPersonalWord(text.substr(start, end - start), 0, false);
    start = end + (end < text.size() ? 1 : 0);
  }
}

void PredictiveText::learnWordBefore(const std::string& text, size_t endPos) {
  endPos = std::min(endPos, text.size());
  size_t end = endPos;
  while (end > 0 && !isWordByte(static_cast<unsigned char>(text[end - 1]))) --end;
  size_t start = end;
  while (start > 0 && isWordByte(static_cast<unsigned char>(text[start - 1]))) --start;
  if (end > start) addPersonalWord(text.substr(start, end - start), 1, true);
}

void PredictiveText::learnCurrentWord(const std::string& text, const size_t cursorPos) {
  size_t start = 0;
  size_t end = 0;
  currentWordRange(text, cursorPos, start, end);
  if (end > start) addPersonalWord(text.substr(start, end - start), 1, true);
}

std::array<std::string, 3> PredictiveText::suggestions(const std::string& text, const size_t cursorPos) const {
  std::array<std::string, 3> result{};
  size_t start = 0;
  size_t end = 0;
  currentWordRange(text, cursorPos, start, end);
  if (cursorPos <= start) return result;

  const std::string typed = normalizeWord(text.substr(start, cursorPos - start));
  const std::string foldedPrefix = foldForMatch(typed);
  if (foldedPrefix.size() < 2) return result;

  std::string cacheKey = foldedPrefix;
  cacheKey.push_back(!typed.empty() && asciiUpper(static_cast<unsigned char>(text[start])) ? 'U' : 'L');
  if (cachedRevision_ == revision_ && cachedKey_ == cacheKey) return cachedSuggestions_;

  std::vector<const PersonalWord*> matches;
  matches.reserve(personal_.size());
  for (const auto& item : personal_) {
    if (foldedInitial(item.word.c_str()) != foldedPrefix[0]) continue;
    const std::string foldedWord = foldForMatch(item.word);
    if (foldedWord.size() >= foldedPrefix.size() &&
        foldedWord.compare(0, foldedPrefix.size(), foldedPrefix) == 0 && foldedWord != foldedPrefix) {
      matches.push_back(&item);
    }
  }
  std::sort(matches.begin(), matches.end(), [](const PersonalWord* a, const PersonalWord* b) {
    if (a->count != b->count) return a->count > b->count;
    return a->word < b->word;
  });

  size_t slot = 0;
  auto add = [&](std::string candidate) {
    if (slot >= result.size()) return;
    const std::string foldedCandidate = foldForMatch(candidate);
    for (size_t i = 0; i < slot; ++i) {
      if (foldForMatch(result[i]) == foldedCandidate) return;
    }
    if (!typed.empty() && asciiUpper(static_cast<unsigned char>(text[start])) && !candidate.empty() &&
        candidate[0] >= 'a' && candidate[0] <= 'z') {
      candidate[0] = static_cast<char>(candidate[0] - 'a' + 'A');
    }
    result[slot++] = std::move(candidate);
  };

  for (const PersonalWord* item : matches) {
    add(item->word);
    if (slot >= result.size()) break;
  }
  for (size_t i = 0; i < kFrenchWordCount && slot < result.size(); ++i) {
    if (foldedInitial(kFrenchWords[i]) != foldedPrefix[0]) continue;
    const std::string word = kFrenchWords[i];
    const std::string foldedWord = foldForMatch(word);
    if (foldedWord.size() >= foldedPrefix.size() &&
        foldedWord.compare(0, foldedPrefix.size(), foldedPrefix) == 0 && foldedWord != foldedPrefix) {
      add(word);
    }
  }

  cachedKey_ = std::move(cacheKey);
  cachedSuggestions_ = result;
  cachedRevision_ = revision_;
  return cachedSuggestions_;
}

bool PredictiveText::applySuggestion(std::string& text, size_t& cursorPos, const size_t maxLength,
                                     const std::string& suggestion) {
  if (suggestion.empty()) return false;
  size_t start = 0;
  size_t end = 0;
  currentWordRange(text, cursorPos, start, end);
  if (cursorPos <= start) return false;

  const bool addSpace = end >= text.size();
  const size_t replacementSize = suggestion.size() + (addSpace ? 1 : 0);
  const size_t newSize = text.size() - (end - start) + replacementSize;
  if (maxLength != 0 && newSize > maxLength) return false;

  std::string replacement = suggestion;
  if (addSpace) replacement.push_back(' ');
  text.replace(start, end - start, replacement);
  cursorPos = start + replacement.size();
  addPersonalWord(suggestion, 1, true);
  return true;
}
