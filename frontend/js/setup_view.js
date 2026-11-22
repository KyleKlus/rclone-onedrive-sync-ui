/**
 * @file setup_view.js
 * @brief The setup form of ONE folder pair.
 *
 * A header row (back button + renameable name) and below it local folder, remote,
 * max file size and the exclusion list.
 *
 * The same form is used to create a new pair and to edit an existing one:
 * `open()` is told which of the two it is. Saving, resetting, deleting and going
 * back are delegated to callbacks.
 */

import { ConfirmDialog } from "./confirm_dialog.js";
import { RemoteField } from "./remote_field.js";
import { SizeField } from "./size_field.js";
import { TwoStepButton } from "./two_step_button.js";

/**
 * @brief The form for creating or editing a folder pair.
 */
export class SetupView {
  /**
   * @brief Look up the elements and wire the buttons and keys.
   * @param {{
   *   onSave: (pair: object) => void,
   *   onReset: () => void,
   *   onDelete: () => void,
   *   onBack: () => void,
   * }} callbacks Called when the user saves, resets, deletes or goes back.
   *
   * `this.remote` and `this.maxSize` have .value and .disabled like an input. `this.pairId`
   * is the id of the pair being edited, or null while a new pair is created. `this.savedSnapshot`
   * is the form as it was when loaded or last saved, used to tell if something was changed.
   * Leaving with unsaved changes needs a second click, so nothing is lost by accident.
   * Enter in the exclusion box adds the pattern instead of saving the form; Enter in the
   * name field moves on to the local folder.
   */
  constructor({ onSave, onReset, onDelete, onBack }) {
    this.form = document.getElementById("setup-form");
    this.name = document.getElementById("pair-name");
    this.localPath = document.getElementById("setup-local-path");
    this.remote = new RemoteField(document.getElementById("remote-field"));
    this.remoteHint = document.getElementById("setup-remote-hint");
    this.maxSize = new SizeField(document.getElementById("size-field"));
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

    this.exclusions = [];
    this.isLocked = false;

    this.pairId = null;
    this.savedSnapshot = "";
    this.savedName = "";

    this.confirmDialog = new ConfirmDialog();
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
      if (!this.hasUnsavedChanges() || this.backConfirm.confirmed()) onBack();
    });
    this.deleteButton.addEventListener("click", async () => {
      const confirmed = await this.confirmDialog.ask({
        title: "Delete folder pair?",
        text: `"${this.savedName}" will be removed from the list. `
          + "The files in its folders, on this PC and on the remote, are not touched.",
        confirmLabel: "Delete pair",
      });
      if (confirmed) onDelete();
    });
    this.resetButton.addEventListener("click", () => onReset());
    this.exclusionAddButton.addEventListener("click", () => this.#addFromInput());
    this.exclusionInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.#addFromInput();
      }
    });
    this.name.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.localPath.focus();
      }
    });
  }

  /**
   * @brief Tell the form which remotes rclone knows and explain the situation in the hint under the field.
   * @param {{remotes: {name: string, type: string}[], error: string}} listing From `ApiClient.getRemotes()`.
   *
   * Call it before `open()`, so the pair that is opened is shown against the right list.
   */
  setRemotes({ remotes, error }) {
    this.remote.setRemotes(remotes);

    if (error) {
      this.remoteHint.textContent = error;
    } else if (remotes.length === 0) {
      this.remoteHint.textContent = "rclone has no remotes yet. Create one with \"rclone config\", then open this form again.";
    } else {
      this.remoteHint.textContent = "One of your rclone remotes (the cloud), optionally followed by a folder on it, e.g. Documents.";
    }
  }

  /**
   * @brief Fill the form with an existing pair or with the default setup of a new pair.
   * @param {object} pair {name, local_path, remote, max_size, exclusions}
   * @param {string|null} pairId Id of the pair, or null for a new pair (with `pair.name` = "").
   */
  open(pair, pairId) {
    this.pairId = pairId;
    this.#fill(pair);
    this.showMessage("", "");
    this.#resetConfirmations();

    const isNew = pairId === null;
    this.deleteButton.hidden = isNew;
    this.saveButton.lastChild.textContent = isNew ? "Create folder pair" : "Save folder pair";
    this.backLabel.textContent = "Back";
    this.backConfirm.idleText = "Back";
  }

  /**
   * @brief Show what the backend really stored and remember it as the saved state.
   * @param {object} pair The pair as saved.
   * @param {string} pairId Id of the pair.
   *
   * Used after a successful save. The backend cleans values up. The form may now
   * belong to a pair that did not exist before, hence the new id.
   */
  markSaved(pair, pairId) {
    this.pairId = pairId;
    this.#fill(pair);
    this.deleteButton.hidden = false;
    this.saveButton.lastChild.textContent = "Save folder pair";
    this.#resetConfirmations();
  }

  /**
   * @brief Put the default values into the form without saving them.
   * @param {{max_size: string, exclusions: string[]}} defaults The default setup.
   *
   * The user still has to click Save. Name, local folder and remote are kept: they
   * are specific to this pair and have no meaningful default.
   */
  applyDefaults(defaults) {
    this.maxSize.value = defaults.max_size;
    this.exclusions = [...defaults.exclusions];
    this.#renderExclusions();
    this.showMessage("Defaults loaded (name, local folder and remote were kept). Click Save to keep them.", "success");
  }

  /**
   * @brief Read the form back into a pair object for the backend.
   * @return {object} {name, local_path, remote, max_size, exclusions}
   */
  collect() {
    return {
      name: this.name.value,
      local_path: this.localPath.value,
      remote: this.remote.value,
      max_size: this.maxSize.value,
      exclusions: [...this.exclusions],
    };
  }

  /**
   * @brief Tell whether the form differs from what was loaded or last saved.
   * @return {boolean} True if there are unsaved changes.
   */
  hasUnsavedChanges() {
    return JSON.stringify(this.collect()) !== this.savedSnapshot;
  }

  /**
   * @brief Lock the whole form while a sync is running.
   * @param {boolean} isLocked True while a sync runs.
   */
  setLocked(isLocked) {
    if (isLocked === this.isLocked) return;
    this.isLocked = isLocked;

    for (const element of [this.name, this.localPath, this.remote, this.maxSize, this.exclusionInput,
                           this.exclusionAddButton, this.saveButton, this.resetButton, this.deleteButton]) {
      element.disabled = isLocked;
    }
    this.lockNote.hidden = !isLocked;
    this.#renderExclusions();
  }

  /**
   * @brief Show a short message in the form.
   * @param {string} text The message.
   * @param {string} [kind] "error" or "success"; picks the colour.
   */
  showMessage(text, kind = "success") {
    this.message.textContent = text;
    this.message.dataset.kind = kind;
  }

  /**
   * @brief Put the cursor in the name field, used right after "Add folder pair".
   */
  focusName() {
    this.name.focus();
  }

  /**
   * @brief Put a pair into the form and remember it as the saved state.
   * @param {object} pair {name, local_path, remote, max_size, exclusions}
   *
   * The saved name is what the popup calls the pair, even if the name field was edited since.
   */
  #fill(pair) {
    this.name.value = pair.name;
    this.localPath.value = pair.local_path;
    this.remote.value = pair.remote;
    this.maxSize.value = pair.max_size;
    this.exclusions = [...pair.exclusions];
    this.#renderExclusions();
    this.savedSnapshot = JSON.stringify(this.collect());
    this.savedName = pair.name;
  }

  /**
   * @brief Disarm the two-step back button.
   */
  #resetConfirmations() {
    this.backConfirm.reset();
  }

  /**
   * @brief Add the pattern typed in the exclusion box to the list.
   */
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
   * @brief Turn a full path into a pattern relative to the synced folder.
   * @param {string} pattern The pattern as typed.
   * @return {string} The shortened pattern, or the input unchanged.
   *
   * rclone matches exclusions against paths inside the synced folder, so a full
   * path such as "/Docs/Vault/Archive" (when the remote is "mycloud:Docs/Vault")
   * would never match anything. If the pattern starts with the remote's folder or
   * the local folder, that part is cut off and the rest is anchored at the top:
   * "/Archive".
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

  /**
   * @brief Remove one pattern from the list.
   * @param {string} pattern The pattern to remove.
   */
  #removeExclusion(pattern) {
    this.exclusions = this.exclusions.filter((existing) => existing !== pattern);
    this.#renderExclusions();
    this.showMessage("Exclusion removed. Click Save to keep it.", "success");
  }

  /**
   * @brief Redraw the exclusion list, with remove buttons locked while a sync runs.
   */
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
