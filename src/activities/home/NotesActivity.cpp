// Notes keeps its established storage/vault implementation in NotesActivityCore.inc.
// Multiline entry is decorated here with a read-only-first viewer; ordinary
// title/search KeyboardEntryActivity uses still delegate to the original keyboard.
#include "NotesViewerKeyboardBase.h"

#define KeyboardEntryActivity NotesViewerKeyboardBase
#include "NotesActivityCore.inc"
#undef KeyboardEntryActivity
