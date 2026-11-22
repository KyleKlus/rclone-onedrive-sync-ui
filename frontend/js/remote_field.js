/**
 * @file remote_field.js
 * @brief The "Remote" field of a folder pair: a remote dropdown followed by a text box for the folder.
 *
 * The dropdown lists the remotes ("clouds") that rclone knows and sits inside the
 * same field at the START.
 *
 *     [ mycloud:  v | Documents/Work                ]
 *       ^ dropdown     ^ optional folder on the remote
 *
 * The rest of the app does not need to know about the two parts: it reads and
 * writes `value` as the text rclone expects ("mycloud:Documents/Work"), exactly
 * like it would with a plain text input. It is the mirror image of the size
 * field (size_field.js), which has its dropdown at the end.
 *
 * The dropdown is built by hand (a native <select> cannot be styled), so this
 * class also takes care of the keyboard: Up/Down/Home/End move, Enter or Space
 * pick, Escape closes.
 *
 * Which remotes exist is not decided here: `setRemotes()` is told. A remote that
 * is saved in a pair but is not (or no longer) in that list stays selectable, so
 * opening an old pair never silently changes it.
 */

/** @brief Shown in the menu next to a remote that rclone does not list. */
const UNKNOWN_REMOTE_TYPE = "not in rclone config";

/**
 * @brief A remote dropdown plus folder text box that reads and writes rclone's remote text.
 */
export class RemoteField {
  /**
   * @brief Look up the parts of the field and wire their events.
   * @param {HTMLElement} root The element with class "remote-field" (see index.html).
   */
  constructor(root) {
    this.root = root;
    this.button = root.querySelector(".remote-field__button");
    this.buttonLabel = root.querySelector(".remote-field__button-label");
    this.menu = root.querySelector(".remote-field__menu");
    this.folder = root.querySelector(".remote-field__folder");

    this.remotes = [];
    this.name = "";
    this.options = [];
    this.isLocked = false;

    this.#render();

    this.button.addEventListener("click", () => (this.#isOpen() ? this.#close() : this.#open()));
    this.button.addEventListener("keydown", (event) => this.#handleButtonKey(event));
    this.menu.addEventListener("keydown", (event) => this.#handleMenuKey(event));
    document.addEventListener("pointerdown", (event) => {
      if (this.#isOpen() && !this.root.contains(event.target)) this.#close();
    });
  }

  /** @brief The remote as rclone expects it: "mycloud:", "mycloud:Documents" ... or "" while none is chosen. */
  get value() {
    return this.name ? `${this.name}:${this.folder.value.trim()}` : "";
  }

  /** @brief Show a remote given in rclone's text: everything before the first colon is the remote. */
  set value(text) {
    const clean = String(text ?? "").trim();
    const colon = clean.indexOf(":");
    if (colon > 0) {
      this.name = clean.slice(0, colon);
      this.folder.value = clean.slice(colon + 1);
    } else {
      this.name = "";
      this.folder.value = clean;
    }
    this.#chooseTheOnlyRemote();
    this.#render();
  }

  /** @brief Whether the field is locked. */
  get disabled() {
    return this.isLocked;
  }

  /** @brief Lock or unlock the field. */
  set disabled(isDisabled) {
    this.isLocked = isDisabled;
    this.root.toggleAttribute("data-disabled", isDisabled);
    if (isDisabled) this.#close();
    this.#render();
  }

  /**
   * @brief Tell the field which remotes exist.
   * @param {{name: string, type: string}[]} remotes The remotes rclone has configured, names without the colon.
   *
   * Call it before setting `value`: when there is exactly one remote and none is
   * chosen, that one is chosen for the user, and doing it in this order keeps the
   * form from looking edited.
   */
  setRemotes(remotes) {
    this.remotes = [...remotes];
    this.#chooseTheOnlyRemote();
    this.#close();
    this.#render();
  }

  /**
   * @brief Choose the remote automatically when there is only one.
   *
   * With a single remote there is nothing to decide, so the user does not have to click.
   */
  #chooseTheOnlyRemote() {
    if (!this.name && this.remotes.length === 1) this.name = this.remotes[0].name;
  }

  /**
   * @brief List what the menu offers.
   * @return {{name: string, type: string}[]} Every known remote, plus the chosen one if rclone does not know it.
   */
  #choices() {
    const choices = [...this.remotes];
    if (this.name && !choices.some((remote) => remote.name === this.name)) {
      choices.unshift({ name: this.name, type: UNKNOWN_REMOTE_TYPE });
    }
    return choices;
  }

  /**
   * @brief Redraw the button and the menu from the current state.
   *
   * With nothing to choose from the button has no purpose; the hint under the field says what to do.
   */
  #render() {
    const choices = this.#choices();
    this.options = choices.map((choice) => this.#createOption(choice));
    this.menu.replaceChildren(...this.options);

    this.buttonLabel.textContent = this.name
      ? `${this.name}:`
      : (choices.length > 0 ? "Select remote" : "No remotes");
    this.button.disabled = this.isLocked || choices.length === 0;
    this.folder.disabled = this.isLocked;
  }

  /**
   * @brief Build the menu item of one remote.
   * @param {{name: string, type: string}} choice The remote to show.
   * @return {HTMLLIElement} The menu item.
   */
  #createOption({ name, type }) {
    const item = document.createElement("li");
    item.className = "remote-field__option";
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", String(name === this.name));
    item.tabIndex = -1;
    item.dataset.name = name;

    const label = document.createElement("span");
    label.className = "remote-field__option-name";
    label.textContent = `${name}:`;

    const kind = document.createElement("span");
    kind.className = "remote-field__option-type";
    kind.textContent = type;

    item.append(label, kind);
    item.addEventListener("click", () => this.#choose(name));
    return item;
  }

  /**
   * @brief Pick a remote, close the menu and focus the folder box.
   * @param {string} name The remote, without the colon.
   *
   * The folder is the next thing to fill in.
   */
  #choose(name) {
    this.name = name;
    this.#render();
    this.#close();
    this.folder.focus();
  }

  /**
   * @brief Tell whether the menu is open.
   * @return {boolean} True if the menu is visible.
   */
  #isOpen() {
    return !this.menu.hidden;
  }

  /**
   * @brief Open the menu and focus the chosen remote.
   */
  #open() {
    if (this.options.length === 0) return;
    this.menu.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    const selected = this.options.find((item) => item.dataset.name === this.name) ?? this.options[0];
    selected.focus();
  }

  /**
   * @brief Close the menu.
   */
  #close() {
    this.menu.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  /**
   * @brief Open the menu on Up or Down.
   * @param {KeyboardEvent} event The key event of the button.
   */
  #handleButtonKey(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      this.#open();
    }
  }

  /**
   * @brief Handle Up/Down/Home/End to move, Enter or Space to pick, Escape to close.
   * @param {KeyboardEvent} event The key event of the menu.
   */
  #handleMenuKey(event) {
    const current = this.options.indexOf(document.activeElement);
    const move = (index) => this.options[(index + this.options.length) % this.options.length].focus();

    switch (event.key) {
      case "ArrowDown": event.preventDefault(); move(current + 1); break;
      case "ArrowUp":   event.preventDefault(); move(current - 1); break;
      case "Home":      event.preventDefault(); move(0); break;
      case "End":       event.preventDefault(); move(this.options.length - 1); break;
      case "Enter":
      case " ":
        event.preventDefault();
        if (current >= 0) this.#choose(this.options[current].dataset.name);
        break;
      case "Escape":
        event.preventDefault();
        this.#close();
        this.button.focus();
        break;
      case "Tab":
        this.#close();
        break;
    }
  }
}
