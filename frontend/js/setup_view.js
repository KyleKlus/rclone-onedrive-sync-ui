/**
 * setup_view.js
 * The setup of ONE folder pair: a header row (back button + renameable name)
 * and below it local folder, remote, max file size and the exclusion list.
 *
 * The same form is used to create a new pair and to edit an existing one:
 * `open()` is told which of the two it is. Saving, resetting, deleting and going
 * back are delegated to callbacks.
 */

import { TwoStepButton } from "./two_step_button.js";

export class SetupView {
  /**
   * @param {{
   *   onSave: (pair: object) => void,
   *   onReset: () => void,
   *   onDelete: () => void,
   *   onBack: () => void,
   * }} callbacks
   */
  constructor({ onSave, onReset, onDelete, onBack }) {
    this.form = document.getElementById("setup-form");
    this.name = document.getElementById("pair-name");
    this.localPath = document.getElementById("setup-local-path");
    this.remote = document.getElementById("setup-remote");
    this.maxSize = document.getElementById("setup-max-size");
    this.exclusionList = document.getElementById("exclusion-list");
    this.exclusionEmpty = document.getElementById("exclusion-empty");
    this.exclusionInput = document.getElementById("exclusion-input");
    this.exclusionAddButton = document.getElementById("exclusion-add-button");
    this.backButton = document.getElementById("pair-back-button");
    this.backLabel = document.getElementById("pair-back-label");
    this.saveButton = document.getElementById("save-button");
    this.resetButton = document.getElementById("reset-button");
    this.deleteButton = document.getElementById("delete-button");
    this.message = document.getElementById("setup-message");
    this.lockNote = document.getElementById("setup-lock-note");

    /** The exclusion patterns currently shown (edited locally until saved). */
    this.exclusions = [];
    this.isLocked = false;

    /** Id of the pair being edited, or null while a new pair is being created. */
    this.pairId = null;
    /** The form as it was when loaded or last saved; used to tell if something was changed. */
    this.savedSnapshot = "";

    this.deleteConfirm = new TwoStepButton(
      this.deleteButton,
      document.getElementById("delete-label"),
      "Click again to delete",
    );
    this.backConfirm = new TwoStepButton(
      this.backButton,
      this.backLabel,
      "Discard changes?",
    );

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      onSave(this.collect());
    });

    this.backButton.addEventListener("click", () => {
      // Leaving with unsaved changes needs a second click, so nothing is lost by accident.
      if (!this.hasUnsavedChanges() || this.backConfirm.confirmed()) onBack();
    });
    this.deleteButton.addEventListener("click", () => {
      if (this.deleteConfirm.confirmed()) onDelete();
    });
    this.resetButton.addEventListener("click", () => onReset());
    this.exclusionAddButton.addEventListener("click", () => this.#addFromInput());
    this.exclusionInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();  // Enter adds the pattern instead of saving the form.
        this.#addFromInput();
      }
    });
    // Same for the name field: Enter keeps the text and does nothing else surprising.
    this.name.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.localPath.focus();
      }
    });
  }

  /**
   * Fill the form with a pair from the backend (an existing pair) or with the
   * default setup (a new pair, `pairId` = null and `pair.name` = "").
   *
   * @param {object} pair     {name, local_path, remote, max_size, exclusions}
   * @param {string|null} pairId
   */
  open(pair, pairId) {
    this.pairId = pairId;
    this.#fill(pair);
    this.showMessage("", "");
    this.#resetConfirmations();

    const isNew = pairId === null;
    this.deleteButton.hidden = isNew;
    this.saveButton.lastChild.textContent = isNew ? "Create folder pair" : "Save folder pair";
    this.backLabel.textContent = "Back";  // idle text of the back button
    this.backConfirm.idleText = "Back";
  }

  /**
   * After a successful save: show what the backend really stored (it cleans values
   * up) and remember that this is the new saved state. The form may now belong to
   * a pair that did not exist before, hence the new id.
   */
  markSaved(pair, pairId) {
    this.pairId = pairId;
    this.#fill(pair);
    this.deleteButton.hidden = false;
    this.saveButton.lastChild.textContent = "Save folder pair";
    this.#resetConfirmations();
  }

  /**
   * Put the default values into the form, WITHOUT saving them (the user still
   * has to click Save). Name and local folder are kept: they are specific to
   * this pair and have no meaningful default.
   */
  applyDefaults(defaults) {
    this.remote.value = defaults.remote;
    this.maxSize.value = defaults.max_size;
    this.exclusions = [...defaults.exclusions];
    this.#renderExclusions();
    this.showMessage("Defaults loaded (name and local folder were kept). Click Save to keep them.", "success");
  }

  /** Read the form back into a pair object for the backend. */
  collect() {
    return {
      name: this.name.value,
      local_path: this.localPath.value,
      remote: this.remote.value,
      max_size: this.maxSize.value,
      exclusions: [...this.exclusions],
    };
  }

  /** True if the form differs from what was loaded or last saved. */
  hasUnsavedChanges() {
    return JSON.stringify(this.collect()) !== this.savedSnapshot;
  }

  /** Lock the whole form while a sync is running. */
  setLocked(isLocked) {
    if (isLocked === this.isLocked) return;
    this.isLocked = isLocked;

    for (const element of [this.name, this.localPath, this.remote, this.maxSize, this.exclusionInput,
                           this.exclusionAddButton, this.saveButton, this.resetButton, this.deleteButton]) {
      element.disabled = isLocked;
    }
    this.lockNote.hidden = !isLocked;
    this.#renderExclusions();  // redraws the remove buttons in the right state
  }

  showMessage(text, kind = "success") {
    this.message.textContent = text;
    this.message.dataset.kind = kind;
  }

  /** Put the cursor in the name field (used right after "Add folder pair"). */
  focusName() {
    this.name.focus();
  }

  // ------------------------------------------------------------------

  #fill(pair) {
    this.name.value = pair.name;
    this.localPath.value = pair.local_path;
    this.remote.value = pair.remote;
    this.maxSize.value = pair.max_size;
    this.exclusions = [...pair.exclusions];
    this.#renderExclusions();
    this.savedSnapshot = JSON.stringify(this.collect());
  }

  #resetConfirmations() {
    this.deleteConfirm.reset();
    this.backConfirm.reset();
  }

  #addFromInput() {
    const typed = this.exclusionInput.value.trim();
    if (!typed) return;

    const pattern = this.#relativeToSyncFolder(typed);
    if (!this.exclusions.includes(pattern)) {
      this.exclusions.push(pattern);
      this.#renderExclusions();
      this.showMessage(
        pattern === typed
          ? "Exclusion added. Click Save to keep it."
          : `Patterns are relative to the synced folder, so "${typed}" was shortened to "${pattern}". Click Save to keep it.`,
        "success"
      );
    }
    this.exclusionInput.value = "";
    this.exclusionInput.focus();
  }

  /**
   * rclone matches exclusions against paths INSIDE the synced folder, so a full
   * path such as "/Docs/Vault/Archive" (when the remote is "onedrive:Docs/Vault")
   * would never match anything. If the pattern starts with the remote's folder or
   * the local folder, cut that part off and anchor the rest at the top: "/Archive".
   * Anything else is returned unchanged.
   */
  #relativeToSyncFolder(pattern) {
    const clean = (text) => text.replaceAll("\\", "/").replace(/^\/+|\/+$/g, "");
    const remoteFolder = this.remote.value.includes(":")
      ? this.remote.value.slice(this.remote.value.indexOf(":") + 1)
      : "";
    const wanted = clean(pattern).toLowerCase();

    for (const base of [remoteFolder, this.localPath.value]) {
      const prefix = clean(base).toLowerCase();
      if (prefix && wanted.startsWith(prefix + "/")) {
        const rest = clean(pattern).slice(prefix.length + 1);
        return "/" + rest + (/[\\/]$/.test(pattern) ? "/" : "");
      }
    }
    return pattern;
  }

  #removeExclusion(pattern) {
    this.exclusions = this.exclusions.filter((existing) => existing !== pattern);
    this.#renderExclusions();
    this.showMessage("Exclusion removed. Click Save to keep it.", "success");
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
      remove.textContent = "×";
      remove.title = `Remove ${pattern}`;
      remove.setAttribute("aria-label", `Remove exclusion ${pattern}`);
      remove.disabled = this.isLocked;
      remove.addEventListener("click", () => this.#removeExclusion(pattern));

      item.append(text, remove);
      this.exclusionList.append(item);
    }
  }
}
