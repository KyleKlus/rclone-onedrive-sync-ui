/**
 * setup_view.js
 * The "SETUP" panel: local folder, remote, max file size and the
 * exclusion list. Saving and resetting are delegated to callbacks.
 */

export class SetupView {
  /**
   * @param {{onSave: (setup: object) => void, onReset: () => void}} callbacks
   */
  constructor({ onSave, onReset }) {
    this.form = document.getElementById("setup-form");
    this.localPath = document.getElementById("setup-local-path");
    this.remote = document.getElementById("setup-remote");
    this.maxSize = document.getElementById("setup-max-size");
    this.exclusionList = document.getElementById("exclusion-list");
    this.exclusionEmpty = document.getElementById("exclusion-empty");
    this.exclusionInput = document.getElementById("exclusion-input");
    this.exclusionAddButton = document.getElementById("exclusion-add-button");
    this.saveButton = document.getElementById("save-button");
    this.resetButton = document.getElementById("reset-button");
    this.message = document.getElementById("setup-message");
    this.lockNote = document.getElementById("setup-lock-note");

    /** The exclusion patterns currently shown (edited locally until saved). */
    this.exclusions = [];
    this.isLocked = false;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      onSave(this.collect());
    });

    this.resetButton.addEventListener("click", () => onReset());
    this.exclusionAddButton.addEventListener("click", () => this.#addFromInput());
    this.exclusionInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();  // Enter adds the pattern instead of saving the form.
        this.#addFromInput();
      }
    });
  }

  /** Fill the form with setup from the backend. */
  load(setup) {
    this.localPath.value = setup.local_path;
    this.remote.value = setup.remote;
    this.maxSize.value = setup.max_size;
    this.exclusions = [...setup.exclusions];
    this.#renderExclusions();
  }

  /**
   * Put the default values into the form, WITHOUT saving them (the user still
   * has to click Save). The local folder is kept: it is specific to this PC and
   * has no meaningful default.
   */
  applyDefaults(defaults) {
    this.remote.value = defaults.remote;
    this.maxSize.value = defaults.max_size;
    this.exclusions = [...defaults.exclusions];
    this.#renderExclusions();
    this.showMessage("Defaults loaded (your local folder was kept). Click Save setup to keep them.", "success");
  }

  /** Read the form back into a setup object for the backend. */
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
                           this.exclusionAddButton, this.saveButton, this.resetButton]) {
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
    const typed = this.exclusionInput.value.trim();
    if (!typed) return;

    const pattern = this.#relativeToSyncFolder(typed);
    if (!this.exclusions.includes(pattern)) {
      this.exclusions.push(pattern);
      this.#renderExclusions();
      this.showMessage(
        pattern === typed
          ? "Exclusion added. Click Save setup to keep it."
          : `Patterns are relative to the synced folder, so "${typed}" was shortened to "${pattern}". Click Save setup to keep it.`,
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
    this.showMessage("Exclusion removed. Click Save setup to keep it.", "success");
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
      remove.textContent = "\u00d7";
      remove.title = `Remove ${pattern}`;
      remove.setAttribute("aria-label", `Remove exclusion ${pattern}`);
      remove.disabled = this.isLocked;
      remove.addEventListener("click", () => this.#removeExclusion(pattern));

      item.append(text, remove);
      this.exclusionList.append(item);
    }
  }
}
