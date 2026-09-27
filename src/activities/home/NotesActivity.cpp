// Notes keeps its established storage/vault implementation in NotesActivityCore.inc.
// Multiline entry is decorated here with a read-only-first viewer; ordinary
// title/search KeyboardEntryActivity uses still delegate to the original keyboard.
#include <I18n.h>

#include "NotesViewerKeyboardBase.h"

// The i18n generator scans .cpp sources. The Notes implementation lives in an
// included .inc file so keep these IDs visible here, otherwise code generation
// strips them before the compiler sees NotesActivityCore.inc.
[[maybe_unused]] static void retainNotesTranslationIds() {
  (void)tr(STR_NOTE_TITLE);
  (void)tr(STR_SEARCH_NOTES);
  (void)tr(STR_NO_NOTES);
}

#define KeyboardEntryActivity NotesViewerKeyboardBase
#define drawHeaderAction drawNotesHeaderAction
#include "NotesActivityCore.inc"
#undef drawHeaderAction
#undef KeyboardEntryActivity
