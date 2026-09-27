// Notes keeps its established storage/vault implementation in NotesActivityCore.inc.
// Multiline entry is decorated here with a read-only-first viewer; ordinary
// title/search KeyboardEntryActivity uses still delegate to the original keyboard.
#include <I18n.h>

#include "NotesViewerKeyboardBase.h"

#define KeyboardEntryActivity NotesViewerKeyboardBase
#define drawHeaderAction drawNotesHeaderAction
#include "NotesActivityCore.inc"
#undef drawHeaderAction
#undef KeyboardEntryActivity
