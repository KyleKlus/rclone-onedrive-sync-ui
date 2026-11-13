/**
 * settings_view.js
 * The "SETTINGS" panel: local folder, remote, max file size and the
 * exclusion list. Saving is delegated to the onSave callback.
 */

export class SettingsView {
  /**
   * @param {{onSave: (settings: object) => void}} callbacks
   */
  constructor({ onSave }) {
    this.form = document.getElementById("settings-form");
    this.localPath = document.getElementById("setting-local-path");
    this.remote = document.getElementById("setting-remote");
    this.maxSize = document.getElementById("setting-max-size");
    this.exclusionList = document.getElementById("exclusion-list");
    this.exclusionEmpty = document.getElementById("exclusion-empty");
    this.exclusionInput = document.getElementById("exclusion-input");
    this.exclusionAddButton = document.getElementById("exclusion-add-button");
    this.saveButton = document.getElementById("save-button");
    this.message = document.getElementById("settings-message");
    this.lockNote = document.getElementById("settings-lock-note");

    /** The exclusion patterns currently shown (edited locally until saved). */
    this.exclusions = [];
    this.isLocked = false;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      onSave(this.collect());
    });

    this.exclusionAddButton.addEventListener("click", () => this.#addFromInput());
    this.exclusionInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();  // Enter adds the pattern instead of saving the form.
        this.#addFromInput();
      }
    });
  }

  /** Fill the form with settings from the backend. */
  load(settings) {
    this.localPath.value = settings.local_path;
    this.remote.value = settings.remote;
    this.maxSize.value = settings.max_size;
    this.exclusions = [...settings.exclusions];
    this.#renderExclusions();
  }

  /** Read the form back into a settings object for the backend. */
  collect() {
    return {
      local_path: this.localPath.value,
      remote: this.remote.value,
      max_size: this.maxSize.value,
      exclusions: [...this.exclusions],
    };
  }

  /** Lock the whole panel while a sync is running. */
  setLocked(isLocked) {
    if (isLocked === this.isLocked) return;
    this.isLocked = isLocked;

    for (const element of [this.localPath, this.remote, this.maxSize, this.exclusionInput,
                           this.exclusionAddButton, this.saveButton]) {
      element.disabled = isLocked;
    }
    this.lockNote.hidden = !isLocked;
    this.#renderExclusions();  // redraws the remove buttons in the right state
  }

  showMessage(text, kind = "success") {
    this.message.textContent = text;
    this.message.dataset.kind = kind;
  }

  // ------------------------------------------------------------------

  #addFromInput() {
    const pattern = this.exclusionInput.value.trim();
    if (!pattern) return;
    if (!this.exclusions.includes(pattern)) {
      this.exclusions.push(pattern);
      this.#renderExclusions();
      this.showMessage("Exclusion added. Click SAVE SETTINGS to keep it.", "success");
    }
    this.exclusionInput.value = "";
    this.exclusionInput.focus();
  }

  #removeExclusion(pattern) {
    this.exclusions = this.exclusions.filter((existing) => existing !== pattern);
    this.#renderExclusions();
    this.showMessage("Exclusion removed. Click SAVE SETTINGS to keep it.", "success");
  }

  #renderExclusions() {
    this.exclusionList.replaceChildren();
    this.exclusionEmpty.hidden = this.exclusions.length > 0;

    for (const pattern of this.exclusions) {
      const item = document.createElement("li");
      item.className = "exclusion-item";

      const text = document.createElement("span");
      text.className = "exclusion-item__pattern";
      text.textContent = pattern;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "exclusion-item__remove";
      remove.textContent = "X";
      remove.title = `Remove ${pattern}`;
      remove.setAttribute("aria-label", `Remove exclusion ${pattern}`);
      remove.disabled = this.isLocked;
      remove.addEventListener("click", () => this.#removeExclusion(pattern));

      item.append(text, remove);
      this.exclusionList.append(item);
    }
  }
}
