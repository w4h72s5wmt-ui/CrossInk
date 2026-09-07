#include "PredictiveText.h"

#include <HalStorage.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {
constexpr const char kPersonalDir[] = "/.crosspoint";
constexpr const char kPersonalPath[] = "/.crosspoint/notes-predictive.txt";
constexpr size_t kMaxPersonalWords = 512;
constexpr size_t kMaxPersonalFileBytes = 65536;

// The list is deliberately ordered by general usefulness. PredictiveText adds
// contextual and personal-frequency bonuses on top of this base ordering.
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
    "retour", "menu", "application", "version", "mise", "réglage", "option", "mode", "grille", "score", "points", "mine",
    "mines", "drapeau", "drapeaux", "partie", "jeu", "jouer", "gagner", "perdre", "annuler", "ordinateur", "ordinateurs",
    "internet", "réseau", "wifi", "connexion", "serveur", "système", "logiciel", "programme", "code", "projet", "build",
    "compilation", "firmware", "binaire", "télécharger", "installer", "copier", "coller", "photo", "image", "vidéo", "musique",
    "livre", "lecture", "liseuse", "chapitre", "auteur", "histoire", "français", "française", "langue", "dictionnaire",
    "prédiction", "suggestion", "correction", "écriture", "manger", "boire", "acheter", "vendre", "payer", "prix", "argent",
    "magasin", "commande", "livraison", "voiture", "train", "avion", "route", "ville", "pays", "voyage", "vacances", "hôtel",
    "restaurant", "café", "eau", "pain", "repas", "santé", "médecin", "sport", "marcher", "courir", "dormir", "réveiller",
    "fatigué", "content", "contente", "heureux", "heureuse", "désolé", "désolée", "d'accord", "certain", "certaine",
    "peut-être", "vraiment", "exactement", "simplement", "rapidement", "normalement", "finalement", "ensemble", "seul", "seule",
    "tout", "toute", "tous", "toutes", "rien", "quelque", "quelques", "chaque", "aucun", "aucune", "plusieurs", "ensuite",
    "puis", "enfin", "voici", "voilà", "ici", "là", "dessus", "dessous", "dedans", "dehors", "gauche", "droite", "haut",
    "bas", "centre", "centrer", "aligner", "vertical", "verticalement", "horizontal", "horizontalement", "clair", "claire",
    "foncé", "foncée", "gris", "noir", "blanc", "afficher", "affichage", "interface", "sélection", "sélectionner", "toucher",
    "tactile", "appuyer", "créer", "création", "modification", "suppression", "sauvegarde", "recherche", "meilleur", "meilleure",
    "meilleurs", "compteur", "nombre", "taille", "ligne", "colonne", "tableau", "entête", "dessiner", "rendre", "rafraîchir",
    "rafraîchissement", "mémoire", "stockage", "personnel", "personnelle", "fréquent", "fréquente", "utilisateur", "utilisatrice",
    "fonction", "fonctionner", "propre", "correct", "correcte", "bien", "mal", "mieux", "parfait", "parfaite", "super", "ok",
    "salut", "coucou", "bientôt", "probablement", "certainement", "également", "concernant", "rapport", "attention", "rappel",
    "objectif", "priorité", "prochaine", "prochain", "étape", "tâche", "fait", "faite", "faits", "prévoir", "prévu", "prévue",
    "terminé", "terminée", "disponible", "disponibles", "actuel", "actuelle", "actuellement",

    // Frequent everyday French, common forms and useful writing vocabulary.
    "à", "a", "ai", "as", "avons", "avez", "ont", "suis", "es", "est", "sommes", "êtes", "sont", "étais", "était",
    "étions", "étiez", "étaient", "serai", "seras", "sera", "serons", "serez", "seront", "été", "serait", "seraient",
    "j'ai", "j'aime", "j'espère", "j'aimerais", "j'avais", "j'étais", "j'irai", "j'arrive", "j'attends", "j'utilise",
    "c'est", "c'était", "cette", "ça", "cela", "ceci", "n'est", "n'ai", "n'a", "n'ont", "n'était", "n'est-ce", "qu'il",
    "qu'elle", "qu'on", "qu'ils", "qu'elles", "qu'un", "qu'une", "quand-même", "l'écran", "l'application", "l'appareil",
    "l'idée", "l'heure", "l'autre", "l'état", "l'écriture", "l'utilisateur", "l'ordinateur", "l'information", "d'abord",
    "d'ailleurs", "d'autres", "d'une", "d'un", "d'accord", "s'il", "s'ils", "surtout", "jusqu'à", "presque", "plutôt",
    "afin", "ainsi", "alors", "aussi", "autant", "autour", "ailleurs", "cependant", "pourtant", "néanmoins", "sinon",
    "donc", "or", "ni", "et", "ou", "où", "dont", "lorsque", "puisque", "tandis", "malgré", "selon", "contre", "parmi",
    "près", "loin", "devant", "derrière", "autour", "côté", "milieu", "intérieur", "extérieur", "général", "générale",
    "principal", "principale", "suivant", "suivante", "précédent", "précédente", "suivre", "précéder", "début", "fin",
    "débuter", "terminer", "continuité", "suite", "prochaine", "prochainement", "immédiatement", "directement", "automatiquement",
    "manuellement", "facilement", "difficilement", "correctement", "complètement", "partiellement", "uniquement", "seulement",
    "notamment", "noter", "notamment", "vérifier", "vérification", "valider", "validation", "confirmer", "confirmation",
    "corriger", "corrigé", "corrigée", "améliorer", "amélioration", "optimiser", "optimisation", "adapter", "adaptation",
    "ajout", "retirer", "retrait", "remplacer", "remplacement", "déplacer", "déplacement", "position", "positionner", "centrage",
    "largeur", "hauteur", "dimension", "dimensions", "espace", "espaces", "marge", "marges", "zone", "zones", "case", "cases",
    "champ", "champs", "barre", "icône", "icônes", "thème", "thèmes", "couleur", "couleurs", "police", "polices", "caractère",
    "caractères", "lettre", "lettres", "accent", "accents", "apostrophe", "tiret", "ponctuation", "majuscule", "minuscule",
    "saisie", "prédictif", "prédictive", "prédire", "proposer", "proposition", "propositions", "apprendre", "apprentissage",
    "fréquence", "contexte", "habitude", "habitudes", "préfixe", "phrase", "phrases", "paragraphe", "paragraphes", "mot-clé",
    "reconnaître", "reconnu", "reconnue", "choix", "sélecteur", "sélectionné", "sélectionnée", "coché", "cochée", "activer",
    "désactiver", "activé", "activée", "désactivé", "désactivée", "fonctionnalité", "fonctionnalités", "paramètre", "paramètres",
    "préférence", "préférences", "configuration", "configurer", "réglages", "valeur", "valeurs", "donnée", "données", "état",
    "états", "historique", "statistique", "statistiques", "record", "records", "niveau", "niveaux", "débutant", "intermédiaire",
    "expert", "difficulté", "facilité", "parties", "joueur", "joueuse", "victoire", "défaite", "temps", "chrono", "seconde",
    "secondes", "minutes", "heures", "total", "totale", "restant", "restante", "restants", "restantes", "compter", "compte",
    "calcul", "calculer", "valide", "invalide", "vrai", "faux", "possible", "nécessaire", "nécessaires", "utile", "utiles",
    "pratique", "agréable", "confortable", "fluide", "stable", "fiable", "léger", "légère", "lourde", "performant",
    "performante", "performance", "vitesse", "latence", "instantané", "instantanée", "lentement", "rapidité", "qualité",
    "meilleure", "bonne", "mauvaise", "excellent", "excellente", "génial", "géniale", "sympa", "joli", "jolie", "beau",
    "belle", "design", "style", "visuel", "visuelle", "proprement", "lisible", "lisibilité", "centré", "centrée", "aligné",
    "alignée", "haut", "bas", "gauche", "droite", "milieu", "dessiner", "dessiné", "dessinée", "rafraîchi", "rafraîchie",
    "écran", "écrans", "pixel", "pixels", "tactile", "toucher", "touché", "appui", "appuyer", "boutons", "physique", "physiques",
    "navigation", "naviguer", "ouvrir", "fermer", "quitter", "sortir", "entrée", "sortie", "retourner", "revenir", "accueil",
    "démarrer", "démarrage", "lancer", "lancement", "relancer", "reprendre", "continuer", "nouveau", "nouvelle", "existant",
    "existante", "existe", "existait", "sauvé", "sauvée", "sauvegardé", "sauvegardée", "charger", "chargement", "chargé",
    "stocké", "stockée", "carte", "sd", "flash", "mémoire", "fichier", "fichiers", "répertoire", "dossiers", "format",
    "formats", "texte", "contenu", "contenus", "nommer", "renommer", "renommage", "effacer", "effacement", "rechercher",
    "trouver", "trouvé", "trouvée", "filtrer", "filtre", "résultats", "afficher", "cacher", "masquer", "visible", "invisible",
    "ligne", "lignes", "retour", "retours", "clavier", "claviers", "touche", "touches", "entrée", "espace", "suppr", "shift",
    "langue", "français", "anglais", "allemand", "espagnol", "italien", "portugais", "azerty", "qwerty", "lettres", "chiffres",
    "symbole", "symboles", "adresse", "url", "lien", "liens", "site", "sites", "web", "http", "https", "serveur", "client",
    "réseau", "wifi", "mot-de-passe", "identifiant", "compte", "connexion", "connecter", "déconnecter", "téléchargement",
    "téléchargé", "envoi", "envoyer", "recevoir", "reçu", "reçue", "partager", "partage", "synchroniser", "synchronisation",
    "mise-à-jour", "version", "versions", "branche", "branches", "commit", "commits", "dépôt", "github", "action", "actions",
    "workflow", "build", "builds", "compiler", "compilé", "compilée", "erreurs", "bug", "bugs", "corrigé", "correctif", "patch",
    "source", "sources", "fonction", "classe", "méthode", "variable", "variables", "constante", "table", "liste", "vecteur",
    "chaîne", "chaînes", "octet", "octets", "utf-8", "unicode", "accentué", "accentuée", "compatible", "compatibilité",
    "ancien", "ancienne", "migration", "migrer", "conserver", "préserver", "perdre", "perdu", "perdue", "réinitialiser",
    "réinitialisation", "restaurer", "restauration", "copie", "copier", "coller", "déplacer", "exporter", "importer", "archive",
    "sauvegarde", "sécurité", "test", "tests", "tester", "essayé", "essai", "fonctionne", "fonctionnait", "fonctionnera",
    "marche", "marcher", "bloqué", "bloquée", "plantage", "redémarrage", "redémarrer", "redémarré", "batterie", "charge",
    "charger", "autonomie", "énergie", "veille", "réveil", "luminosité", "contraste", "rotation", "orientation", "portrait",
    "paysage", "page", "pages", "livres", "bibliothèque", "lecture", "lecteur", "lectrice", "chapitres", "marque-page",
    "surligner", "surlignage", "police", "taille", "zoom", "sommaire", "couverture", "auteurs", "titre", "titres", "éditeur",
    "édition", "epub", "pdf", "document", "documents", "notes", "note", "écrire", "écrit", "écrite", "écriture", "brouillon",
    "idées", "rappel", "rappels", "agenda", "calendrier", "réunion", "réunions", "rendez-vous", "événement", "événements",
    "aujourd'hui", "demain", "après-demain", "hier", "avant-hier", "lundi", "mardi", "mercredi", "jeudi", "vendredi",
    "samedi", "dimanche", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
    "novembre", "décembre", "matin", "matinée", "midi", "après-midi", "soir", "soirée", "nuit", "week-end", "weekend",
    "maintenant", "bientôt", "tard", "tôt", "déjà", "encore", "toujours", "jamais", "souvent", "rarement", "parfois",
    "quotidien", "quotidienne", "hebdomadaire", "mensuel", "mensuelle", "annuel", "annuelle", "prochain", "prochaine",
    "dernier", "dernière", "prochainement", "immédiat", "immédiate", "durée", "durer", "attente", "attendre", "retard",
    "avance", "prévu", "prévue", "prévision", "planning", "programme", "organisation", "organiser", "préparer", "préparation",
    "commencer", "terminer", "continuer", "reprendre", "arrêter", "pause", "priorité", "urgent", "urgente", "important",
    "importante", "secondaire", "principal", "principale", "objectif", "objectifs", "projet", "projets", "tâche", "tâches",
    "travail", "travailler", "bureau", "équipe", "équipes", "collègue", "collègues", "responsable", "client", "clients",
    "service", "services", "produit", "produits", "vente", "ventes", "achat", "achats", "commande", "commandes", "facture",
    "factures", "paiement", "payer", "budget", "coût", "coûts", "prix", "gratuit", "gratuite", "payant", "payante",
    "maison", "appartement", "pièce", "chambre", "salon", "cuisine", "salle", "porte", "fenêtre", "table", "chaise", "lit",
    "jardin", "garage", "clé", "clés", "sac", "boîte", "boite", "papier", "stylo", "crayon", "lampe", "lumière", "eau",
    "café", "thé", "lait", "sucre", "sel", "pain", "fromage", "viande", "poisson", "légume", "légumes", "fruit", "fruits",
    "déjeuner", "dîner", "petit-déjeuner", "restaurant", "repas", "manger", "boire", "faim", "soif", "recette", "courses",
    "magasin", "supermarché", "marché", "acheter", "vendre", "payer", "carte", "espèces", "argent", "euro", "euros",
    "famille", "parent", "parents", "père", "mère", "papa", "maman", "frère", "sœur", "soeur", "fils", "fille", "enfant",
    "enfants", "ami", "amie", "amis", "amies", "personne", "personnes", "voisin", "voisine", "homme", "femme", "monsieur",
    "madame", "nom", "prénom", "âge", "adresse", "téléphone", "portable", "message", "messages", "email", "mail", "réponse",
    "répondre", "appeler", "appel", "conversation", "discussion", "parler", "dire", "demander", "question", "questions", "bonjour",
    "salut", "coucou", "merci", "bienvenue", "désolé", "désolée", "pardon", "excuse", "excuser", "félicitations", "bravo",
    "plaisir", "heureux", "heureuse", "content", "contente", "triste", "fatigué", "fatiguée", "calme", "stressé", "stressée",
    "peur", "envie", "besoin", "préférence", "aimer", "adorer", "détester", "vouloir", "souhaiter", "espérer", "penser",
    "croire", "savoir", "comprendre", "compris", "connaître", "connais", "apprendre", "oublier", "souvenir", "rappeler",
    "expliquer", "explication", "montrer", "regarder", "voir", "écouter", "entendre", "sentir", "lire", "écrire", "parler",
    "choisir", "décider", "décision", "accepter", "refuser", "proposer", "essayer", "réussir", "échouer", "aider", "aide",
    "changer", "garder", "laisser", "prendre", "mettre", "donner", "recevoir", "envoyer", "porter", "apporter", "ramener",
    "aller", "venir", "partir", "arriver", "entrer", "sortir", "monter", "descendre", "marcher", "courir", "rouler", "conduire",
    "voiture", "vélo", "bus", "métro", "train", "avion", "bateau", "route", "rue", "chemin", "gare", "station", "aéroport",
    "ville", "village", "pays", "France", "Europe", "voyage", "voyager", "vacances", "hôtel", "réservation", "réserver",
    "place", "places", "billet", "billets", "départ", "arrivée", "destination", "distance", "kilomètre", "kilomètres",
    "météo", "soleil", "pluie", "neige", "vent", "chaud", "chaude", "froid", "froide", "température", "degré", "degrés",
    "printemps", "été", "automne", "hiver", "ciel", "nuage", "nuages", "orage", "beau", "mauvais", "mauvaise",
    "santé", "médecin", "docteur", "pharmacie", "médicament", "douleur", "malade", "maladie", "rendez-vous", "urgence",
    "sport", "marche", "course", "courir", "vélo", "natation", "football", "tennis", "musculation", "entraînement", "repos",
    "dormir", "sommeil", "réveiller", "réveil", "fatigue", "énergie", "forme", "bien-être", "musique", "film", "films",
    "série", "séries", "photo", "photos", "vidéo", "vidéos", "image", "images", "livre", "livres", "histoire", "histoires",
    "jeu", "jeux", "jouer", "partie", "parties", "score", "scores", "point", "points", "niveau", "niveaux", "gagner",
    "perdre", "victoire", "défaite", "mine", "mines", "drapeau", "drapeaux", "grille", "grilles", "démineur", "case", "cases"
};
constexpr size_t kFrenchWordCount = sizeof(kFrenchWords) / sizeof(kFrenchWords[0]);

struct ContextEntry {
  const char* previous;
  const char* next1;
  const char* next2;
  const char* next3;
};

constexpr ContextEntry kContexts[] = {
    {"je", "suis", "veux", "pense"}, {"j'ai", "besoin", "envie", "déjà"}, {"j'aimerais", "avoir", "faire", "savoir"},
    {"tu", "peux", "es", "veux"}, {"il", "est", "faut", "peut"}, {"elle", "est", "peut", "a"},
    {"on", "peut", "va", "est"}, {"nous", "avons", "sommes", "pouvons"}, {"vous", "pouvez", "avez", "êtes"},
    {"ils", "sont", "ont", "peuvent"}, {"elles", "sont", "ont", "peuvent"}, {"c'est", "bien", "possible", "fait"},
    {"ce", "sera", "n'est", "que"}, {"ça", "marche", "fonctionne", "va"}, {"merci", "pour", "beaucoup", "encore"},
    {"très", "bien", "important", "simple"}, {"plus", "de", "simple", "rapide"}, {"moins", "de", "important", "rapide"},
    {"avec", "le", "la", "un"}, {"sans", "le", "la", "problème"}, {"dans", "le", "la", "les"},
    {"sur", "le", "la", "les"}, {"pour", "le", "la", "les"}, {"de", "la", "le", "plus"},
    {"du", "coup", "tout", "temps"}, {"une", "nouvelle", "bonne", "autre"}, {"un", "nouveau", "bon", "autre"},
    {"bonne", "idée", "journée", "nouvelle"}, {"nouvelle", "version", "partie", "note"}, {"nouveau", "fichier", "projet", "jeu"},
    {"mise", "à", "en", "du"}, {"à", "jour", "la", "partir"}, {"mot", "de", "suivant", "précédent"},
    {"mot-de-passe", "est", "wifi", "oublié"}, {"écriture", "prédictive", "rapide", "fluide"},
    {"écran", "tactile", "d'accueil", "de"}, {"clavier", "virtuel", "tactile", "français"},
    {"note", "suivante", "existante", "rapide"}, {"notes", "existantes", "personnelles", "rapides"},
    {"build", "réussie", "suivante", "actuelle"}, {"compilation", "réussie", "terminée", "en"},
    {"firmware", "CrossInk", "actuel", "installé"}, {"démineur", "fonctionne", "tactile", "rapide"},
    {"score", "maximum", "actuel", "final"}, {"partie", "en", "terminée", "suivante"},
    {"rendez-vous", "demain", "à", "avec"}, {"aujourd'hui", "je", "nous", "c'est"}, {"demain", "je", "nous", "matin"},
    {"bonjour", "je", "à", "tout"}, {"bonsoir", "je", "à", "tout"}, {"salut", "ça", "je", "comment"},
    {"comment", "faire", "ça", "est"}, {"pourquoi", "le", "ça", "ne"}, {"parce", "que", "qu'il", "qu'elle"},
    {"peut-être", "que", "demain", "plus"}, {"d'accord", "avec", "pour", "merci"}
};
constexpr size_t kContextCount = sizeof(kContexts) / sizeof(kContexts[0]);

bool asciiUpper(const unsigned char c) { return c >= 'A' && c <= 'Z'; }
bool asciiLetterOrDigit(const unsigned char c) {
  return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}
bool wordByte(const unsigned char c) { return c >= 0x80 || asciiLetterOrDigit(c) || c == '\'' || c == '-'; }
bool coreWordByte(const unsigned char c) { return c >= 0x80 || asciiLetterOrDigit(c); }

struct FoldStream {
  const unsigned char* cursor;
  unsigned char pending = 0;
};

bool nextFolded(FoldStream& stream, char& out) {
  if (stream.pending != 0) {
    out = static_cast<char>(stream.pending);
    stream.pending = 0;
    return true;
  }

  const unsigned char c = *stream.cursor;
  if (c == 0) return false;
  if (c < 0x80) {
    ++stream.cursor;
    out = static_cast<char>((c >= 'A' && c <= 'Z') ? c - 'A' + 'a' : c);
    return true;
  }

  const unsigned char n = stream.cursor[1];
  if (c == 0xC3 && n != 0) {
    stream.cursor += 2;
    switch (n) {
      case 0x80: case 0x81: case 0x82: case 0x83: case 0x84: case 0x85:
      case 0xA0: case 0xA1: case 0xA2: case 0xA3: case 0xA4: case 0xA5: out = 'a'; return true;
      case 0x87: case 0xA7: out = 'c'; return true;
      case 0x88: case 0x89: case 0x8A: case 0x8B:
      case 0xA8: case 0xA9: case 0xAA: case 0xAB: out = 'e'; return true;
      case 0x8C: case 0x8D: case 0x8E: case 0x8F:
      case 0xAC: case 0xAD: case 0xAE: case 0xAF: out = 'i'; return true;
      case 0x92: case 0x93: case 0x94: case 0x95: case 0x96:
      case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: out = 'o'; return true;
      case 0x99: case 0x9A: case 0x9B: case 0x9C:
      case 0xB9: case 0xBA: case 0xBB: case 0xBC: out = 'u'; return true;
      case 0x9D: case 0xBD: case 0xBF: out = 'y'; return true;
      default:
        out = static_cast<char>(c);
        stream.pending = n;
        return true;
    }
  }

  if (c == 0xC5 && n != 0) {
    stream.cursor += 2;
    if (n == 0x92 || n == 0x93) {
      out = 'o';
      stream.pending = 'e';
      return true;
    }
    out = static_cast<char>(c);
    stream.pending = n;
    return true;
  }

  ++stream.cursor;
  out = static_cast<char>(c);
  return true;
}

char foldedInitial(const char* word) {
  if (!word || !*word) return '\0';
  FoldStream stream{reinterpret_cast<const unsigned char*>(word)};
  char out = '\0';
  return nextFolded(stream, out) ? out : '\0';
}

bool foldedMatchesPrefix(const char* word, const std::string& prefix, size_t& foldedLength) {
  foldedLength = 0;
  if (!word) return prefix.empty();
  FoldStream stream{reinterpret_cast<const unsigned char*>(word)};
  char c = '\0';
  while (nextFolded(stream, c)) {
    if (foldedLength < prefix.size() && c != prefix[foldedLength]) return false;
    ++foldedLength;
  }
  return foldedLength >= prefix.size();
}

bool foldedEqualsTarget(const char* word, const std::string& folded) {
  size_t length = 0;
  return foldedMatchesPrefix(word, folded, length) && length == folded.size();
}

bool foldedEquivalent(const char* a, const char* b) {
  if (!a || !b) return a == b;
  FoldStream left{reinterpret_cast<const unsigned char*>(a)};
  FoldStream right{reinterpret_cast<const unsigned char*>(b)};
  char lc = '\0';
  char rc = '\0';
  while (true) {
    const bool hasLeft = nextFolded(left, lc);
    const bool hasRight = nextFolded(right, rc);
    if (hasLeft != hasRight) return false;
    if (!hasLeft) return true;
    if (lc != rc) return false;
  }
}

std::string previousWordBefore(const std::string& text, size_t pos) {
  pos = std::min(pos, text.size());
  while (pos > 0 && !wordByte(static_cast<unsigned char>(text[pos - 1]))) --pos;
  const size_t end = pos;
  while (pos > 0 && wordByte(static_cast<unsigned char>(text[pos - 1]))) --pos;
  size_t start = pos;
  while (start < end && !coreWordByte(static_cast<unsigned char>(text[start]))) ++start;
  size_t cleanEnd = end;
  while (cleanEnd > start && !coreWordByte(static_cast<unsigned char>(text[cleanEnd - 1]))) --cleanEnd;
  return text.substr(start, cleanEnd - start);
}

bool isSentenceStart(const std::string& text, size_t wordStart) {
  size_t pos = std::min(wordStart, text.size());
  while (pos > 0) {
    const unsigned char c = static_cast<unsigned char>(text[pos - 1]);
    if (c == ' ' || c == '\t' || c == '\r' || c == '"' || c == '\'' || c == '(' || c == '[') {
      --pos;
      continue;
    }
    return c == '\n' || c == '.' || c == '!' || c == '?';
  }
  return true;
}

void capitalizeFirstAscii(std::string& word) {
  for (char& c : word) {
    if (c >= 'a' && c <= 'z') {
      c = static_cast<char>(c - 'a' + 'A');
      return;
    }
    const unsigned char uc = static_cast<unsigned char>(c);
    if (uc >= 0x80) return;
  }
}

}  // namespace

void PredictiveText::invalidateSuggestionCache() {
  ++revision_;
  if (revision_ == 0) revision_ = 1;
  cachedRevision_ = 0;
  cachedKey_.clear();
  cachedSuggestions_ = {};
}

bool PredictiveText::isWordByte(const unsigned char c) { return wordByte(c); }

std::string PredictiveText::normalizeWord(std::string word) {
  size_t start = 0;
  while (start < word.size() && !coreWordByte(static_cast<unsigned char>(word[start]))) ++start;
  size_t end = word.size();
  while (end > start && !coreWordByte(static_cast<unsigned char>(word[end - 1]))) --end;
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
  FoldStream stream{reinterpret_cast<const unsigned char*>(word.c_str())};
  char c = '\0';
  while (nextFolded(stream, c)) out.push_back(c);
  return out;
}

void PredictiveText::currentWordRange(const std::string& text, size_t cursorPos, size_t& start, size_t& end) {
  cursorPos = std::min(cursorPos, text.size());
  start = cursorPos;
  while (start > 0 && isWordByte(static_cast<unsigned char>(text[start - 1]))) --start;
  end = cursorPos;
  while (end < text.size() && isWordByte(static_cast<unsigned char>(text[end]))) ++end;
  while (start < end && !coreWordByte(static_cast<unsigned char>(text[start]))) ++start;
  while (end > start && !coreWordByte(static_cast<unsigned char>(text[end - 1]))) --end;
}

bool PredictiveText::startsWithFolded(const std::string& word, const std::string& foldedPrefix) {
  size_t foldedLength = 0;
  return foldedMatchesPrefix(word.c_str(), foldedPrefix, foldedLength);
}

bool PredictiveText::isBuiltinWord(const std::string& normalizedWord) {
  const std::string folded = foldForMatch(normalizedWord);
  for (size_t i = 0; i < kFrenchWordCount; ++i) {
    if (foldedInitial(kFrenchWords[i]) != foldedInitial(normalizedWord.c_str())) continue;
    if (foldedEqualsTarget(kFrenchWords[i], folded)) return true;
  }
  return false;
}

void PredictiveText::addPersonalWord(const std::string& word, const uint16_t increment, const bool allowBuiltin) {
  const std::string normalized = normalizeWord(word);
  if (normalized.size() < 2 || normalized.size() > 40) return;
  bool hasLetter = false;
  for (const unsigned char c : normalized) {
    if (c >= 0x80 || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')) { hasLetter = true; break; }
  }
  if (!hasLetter || (!allowBuiltin && isBuiltinWord(normalized))) return;

  const std::string folded = foldForMatch(normalized);
  for (auto& item : personal_) {
    if (foldedInitial(item.word.c_str()) == foldedInitial(normalized.c_str()) &&
        foldedEqualsTarget(item.word.c_str(), folded)) {
      if (increment > 0) {
        const uint32_t next = static_cast<uint32_t>(item.count) + increment;
        item.count = static_cast<uint16_t>(std::min<uint32_t>(next, 65535));
        dirty_ = true;
        invalidateSuggestionCache();
      }
      return;
    }
  }

  if (personal_.size() >= kMaxPersonalWords) {
    if (increment == 0) return;
    auto victim = std::min_element(personal_.begin(), personal_.end(), [](const PersonalWord& a, const PersonalWord& b) {
      return a.count < b.count;
    });
    if (victim == personal_.end() || victim->count > std::max<uint16_t>(1, increment)) return;
    *victim = PersonalWord{normalized, static_cast<uint16_t>(std::max<uint16_t>(1, increment))};
  } else {
    personal_.push_back(PersonalWord{normalized, static_cast<uint16_t>(std::max<uint16_t>(1, increment))});
  }
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

  std::array<uint8_t, 256> input{};
  std::array<char, 64> line{};
  size_t lineLength = 0;
  bool overflow = false;

  const auto consumeLine = [&]() {
    if (!overflow && lineLength > 0) {
      line[lineLength] = '\0';
      char* tab = std::strchr(line.data(), '\t');
      if (tab && tab[1] != '\0') {
        *tab = '\0';
        const unsigned long parsed = std::strtoul(line.data(), nullptr, 10);
        addPersonalWord(std::string(tab + 1),
                        static_cast<uint16_t>(std::min<unsigned long>(65535, std::max<unsigned long>(1, parsed))),
                        true);
      }
    }
    lineLength = 0;
    overflow = false;
  };

  while (personal_.size() < kMaxPersonalWords) {
    const int count = file.read(input.data(), input.size());
    if (count <= 0) break;
    for (int i = 0; i < count; ++i) {
      const char c = static_cast<char>(input[static_cast<size_t>(i)]);
      if (c == '\n') {
        consumeLine();
        if (personal_.size() >= kMaxPersonalWords) break;
        continue;
      }
      if (lineLength + 1 < line.size()) {
        line[lineLength++] = c;
      } else {
        overflow = true;
      }
    }
  }
  if (personal_.size() < kMaxPersonalWords && (lineLength > 0 || overflow)) consumeLine();
  file.close();
  dirty_ = false;
}

void PredictiveText::save() {
  if (!dirty_) return;
  Storage.mkdir(kPersonalDir);
  FsFile file = Storage.open(kPersonalPath, O_WRONLY | O_CREAT | O_TRUNC);
  if (!file) return;

  const size_t count = std::min(personal_.size(), kMaxPersonalWords);
  std::array<uint16_t, kMaxPersonalWords> order{};
  for (size_t i = 0; i < count; ++i) order[i] = static_cast<uint16_t>(i);
  std::sort(order.begin(), order.begin() + count, [this](const uint16_t a, const uint16_t b) {
    const auto& left = personal_[a];
    const auto& right = personal_[b];
    if (left.count != right.count) return left.count > right.count;
    return left.word < right.word;
  });

  std::array<char, 64> line{};
  bool ok = true;
  for (size_t i = 0; i < count; ++i) {
    const auto& item = personal_[order[i]];
    const int lineSize = std::snprintf(line.data(), line.size(), "%u\t%s\n",
                                       static_cast<unsigned>(item.count), item.word.c_str());
    if (lineSize <= 0 || static_cast<size_t>(lineSize) >= line.size() ||
        file.write(reinterpret_cast<const uint8_t*>(line.data()), static_cast<size_t>(lineSize)) !=
            static_cast<size_t>(lineSize)) {
      ok = false;
      break;
    }
  }
  file.close();
  if (ok) dirty_ = false;
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
  size_t start = 0, end = 0;
  currentWordRange(text, cursorPos, start, end);
  if (end > start) addPersonalWord(text.substr(start, end - start), 1, true);
}

std::array<std::string, 3> PredictiveText::suggestions(const std::string& text, const size_t cursorPos) const {
  std::array<std::string, 3> result{};
  size_t start = 0, end = 0;
  currentWordRange(text, cursorPos, start, end);
  const bool hasPrefix = cursorPos > start;
  const std::string typed = hasPrefix ? normalizeWord(text.substr(start, cursorPos - start)) : std::string();
  const std::string foldedPrefix = foldForMatch(typed);
  const std::string previous = normalizeWord(previousWordBefore(text, start));
  const std::string foldedPrevious = foldForMatch(previous);

  if (foldedPrefix.empty() && foldedPrevious.empty()) return result;

  const bool sentenceStart = isSentenceStart(text, start);
  std::string cacheKey = foldedPrevious + "|" + foldedPrefix;
  cacheKey.push_back(sentenceStart ? 'S' : 'N');
  if (cachedRevision_ == revision_ && cachedKey_ == cacheKey) return cachedSuggestions_;

  struct RankedCandidate {
    const char* word = nullptr;
    int score = 0;
  };
  std::array<RankedCandidate, 3> best{};
  size_t bestCount = 0;

  auto better = [](const RankedCandidate& a, const RankedCandidate& b) {
    if (a.score != b.score) return a.score > b.score;
    const size_t aLength = std::strlen(a.word);
    const size_t bLength = std::strlen(b.word);
    if (aLength != bLength) return aLength < bLength;
    return std::strcmp(a.word, b.word) < 0;
  };

  auto bubbleUp = [&](size_t index) {
    while (index > 0 && better(best[index], best[index - 1])) {
      std::swap(best[index], best[index - 1]);
      --index;
    }
  };

  auto addRanked = [&](const char* word, const int score) {
    if (!word || !*word) return;
    for (size_t i = 0; i < bestCount; ++i) {
      if (!foldedEquivalent(best[i].word, word)) continue;
      if (score > best[i].score) {
        best[i].score = score;
        bubbleUp(i);
      }
      return;
    }

    RankedCandidate candidate{word, score};
    if (bestCount < best.size()) {
      const size_t index = bestCount++;
      best[index] = candidate;
      bubbleUp(index);
    } else if (better(candidate, best.back())) {
      best.back() = candidate;
      bubbleUp(best.size() - 1);
    }
  };

  auto addFiltered = [&](const char* word, const int score) {
    size_t foldedLength = 0;
    if (!foldedPrefix.empty() &&
        (!foldedMatchesPrefix(word, foldedPrefix, foldedLength) || foldedLength == foldedPrefix.size())) {
      return;
    }
    addRanked(word, score);
  };

  if (!foldedPrevious.empty()) {
    for (size_t i = 0; i < kContextCount; ++i) {
      if (foldedInitial(kContexts[i].previous) != foldedPrevious[0]) continue;
      if (!foldedEqualsTarget(kContexts[i].previous, foldedPrevious)) continue;
      addFiltered(kContexts[i].next1, 9000);
      addFiltered(kContexts[i].next2, 8600);
      addFiltered(kContexts[i].next3, 8200);
      break;
    }
  }

  if (!foldedPrefix.empty()) {
    for (const auto& item : personal_) {
      if (foldedInitial(item.word.c_str()) != foldedPrefix[0]) continue;
      size_t foldedLength = 0;
      if (!foldedMatchesPrefix(item.word.c_str(), foldedPrefix, foldedLength) || foldedLength == foldedPrefix.size()) continue;
      const int completionPenalty = static_cast<int>(foldedLength - foldedPrefix.size());
      addRanked(item.word.c_str(), 5000 + std::min<int>(2500, item.count * 40) - completionPenalty * 4);
    }

    if (foldedPrefix.size() >= 2) {
      for (size_t i = 0; i < kFrenchWordCount; ++i) {
        if (foldedInitial(kFrenchWords[i]) != foldedPrefix[0]) continue;
        size_t foldedLength = 0;
        if (!foldedMatchesPrefix(kFrenchWords[i], foldedPrefix, foldedLength) || foldedLength == foldedPrefix.size()) continue;
        const int completionPenalty = static_cast<int>(foldedLength - foldedPrefix.size());
        const int frequencyScore = std::max(0, 3000 - static_cast<int>(i / 2));
        addRanked(kFrenchWords[i], frequencyScore - completionPenalty * 3);
      }
    }
  }

  const bool capitalize = sentenceStart || (!typed.empty() && asciiUpper(static_cast<unsigned char>(text[start])));
  for (size_t i = 0; i < bestCount; ++i) {
    result[i] = best[i].word;
    if (capitalize) capitalizeFirstAscii(result[i]);
  }

  cachedKey_ = std::move(cacheKey);
  cachedSuggestions_ = result;
  cachedRevision_ = revision_;
  return cachedSuggestions_;
}

bool PredictiveText::applySuggestion(std::string& text, size_t& cursorPos, const size_t maxLength,
                                     const std::string& suggestion) {
  if (suggestion.empty()) return false;
  cursorPos = std::min(cursorPos, text.size());
  size_t start = 0, end = 0;
  currentWordRange(text, cursorPos, start, end);

  // If the cursor is between words (typically just after a space), insert a
  // contextual next-word suggestion instead of requiring a typed prefix.
  if (cursorPos <= start) {
    start = end = cursorPos;
  }

  const bool nextIsPunctuation = end < text.size() && (text[end] == '.' || text[end] == ',' || text[end] == ';' ||
                                                        text[end] == ':' || text[end] == '!' || text[end] == '?');
  const bool addSpace = end >= text.size() || (!nextIsPunctuation && text[end] != ' ' && text[end] != '\n' && text[end] != '\t');
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
