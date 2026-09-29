// Notes keeps its storage/vault implementation in NotesActivityCore.inc.
// The editor and viewer use a Notes-local keyboard implementation so the app
// does not depend on CrossInk's private KeyboardEntryActivity internals.
#include <I18n.h>

#include "NotesViewerKeyboardBase.h"

// Keep the strings visible to the i18n generator while preserving runtime
// language selection inside the included Notes implementation.
#define NOTES_TITLE_LABEL tr(STR_NOTE_TITLE)
#define NOTES_SEARCH_LABEL tr(STR_SEARCH_NOTES)
#define NOTES_EMPTY_LABEL tr(STR_NO_NOTES)
#define drawHeaderAction drawNotesHeaderAction
#include "NotesActivityCore.inc"
#undef drawHeaderAction
#undef NOTES_EMPTY_LABEL
#undef NOTES_SEARCH_LABEL
#undef NOTES_TITLE_LABEL
