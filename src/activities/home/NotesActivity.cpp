// Notes keeps its established storage/vault implementation in NotesActivityCore.inc.
// Multiline entry is decorated here with a read-only-first viewer; ordinary
// title/search KeyboardEntryActivity uses still delegate to the original keyboard.
#include <I18n.h>

#include "NotesViewerKeyboardBase.h"

namespace {
constexpr char NOTES_TITLE_LABEL[] = "Titre de la note";
constexpr char NOTES_SEARCH_LABEL[] = "Rechercher";
constexpr char NOTES_EMPTY_LABEL[] = "Aucune note";
}  // namespace

#define KeyboardEntryActivity NotesViewerKeyboardBase
#define drawHeaderAction drawNotesHeaderAction
#include "NotesActivityCore.inc"
#undef drawHeaderAction
#undef KeyboardEntryActivity
