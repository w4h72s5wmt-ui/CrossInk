#pragma once

#include <string>
#include <vector>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class NotesActivity final : public Activity {
 public:
  explicit NotesActivity(GfxRenderer& renderer, MappedInputManager& mappedInput);

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;

 private:
  static constexpr const char* kNotesDir = "/Notes";
  static constexpr size_t kMaxNoteBytes = 32 * 1024;

  ButtonNavigator buttonNavigator;
  std::vector<std::string> notes;
  std::vector<std::string> filteredNotes;
  std::string searchQuery;
  int selectorIndex = 0;
  int topIndex = 0;

  void reloadNotes();
  void applyFilter();
  void createNote();
  void renameNote(const std::string& filename);
  void editSearch();
  void openSelectedNote();
  void openNoteAt(int index);
  void editNote(const std::string& path, const std::string& title);
  bool loadNote(const std::string& path, std::string& text) const;
  bool saveNote(const std::string& path, const std::string& text) const;
  std::string uniquePathForTitle(const std::string& title) const;
  static std::string displayName(const std::string& filename);
  static std::string sanitizeFilename(const std::string& title);
};
