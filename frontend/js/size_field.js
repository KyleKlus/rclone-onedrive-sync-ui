/**
 * @file size_field.js
 * @brief The "Max file size" field: a number and, inside the same field, a dropdown for the unit.
 *
 * The unit is KB, MB, GB, TB or "No limit".
 * The rest of the app does not need to know about the two parts: it reads and
 * writes `value` as the text rclone expects ("50M", "2G", "off"), exactly like
 * it would with a plain text input.
 *
 * The dropdown is built by hand (a native <select> cannot be styled), so this
 * class also takes care of the keyboard: Up/Down/Home/End move, Enter or Space
 * pick, Escape closes.
 */

/** @brief The choices of the dropdown: what the user sees, and the suffix rclone expects. */
const UNITS = [
  { label: "KB", suffix: "k" },
  { label: "MB", suffix: "M" },
  { label: "GB", suffix: "G" },
  { label: "TB", suffix: "T" },
  { label: "No limit", suffix: "off" },
];

/** @brief The unit chosen when nothing else is known. */
const DEFAULT_UNIT = "M";

/** @brief Factor to convert units that are not in the dropdown into kilobytes. */
const KILOBYTES_PER = { b: 1 / 1024, p: 1024 ** 3 };

/**
 * @brief A number input with a hand-built unit dropdown that reads and writes rclone's size text.
 */
export class SizeField {
  /**
   * @brief Look up the parts of the field and wire their events.
   * @param {HTMLElement} root The element with class "size-field" (see index.html).
   */
  constructor(root) {
    this.root = root;
    this.number = root.querySelector(".size-field__number");
    this.button = root.querySelector(".size-field__button");
    this.buttonLabel = root.querySelector(".size-field__button-label");
    this.menu = root.querySelector(".size-field__menu");

    this.unit = DEFAULT_UNIT;
    this.options = [];
    this.#buildMenu();
    this.#showUnit();

    this.number.addEventListener("input", () => {
      this.number.value = this.number.value.replace(/[^\d.]/g, "").replace(/(\..*)\./g, "$1");
    });
    this.button.addEventListener("click", () => (this.#isOpen() ? this.#close() : this.#open()));
    this.button.addEventListener("keydown", (event) => this.#handleButtonKey(event));
    this.menu.addEventListener("keydown", (event) => this.#handleMenuKey(event));
    document.addEventListener("pointerdown", (event) => {
      if (this.#isOpen() && !this.root.contains(event.target)) this.#close();
    });
  }

  /** @brief The size as rclone expects it: "50M", "2G", "off" ... or "" while no number is typed. */
  get value() {
    if (this.unit === "off") return "off";
    const number = this.number.value.trim();
    return number === "" ? "" : `${number}${this.unit}`;
  }

  /** @brief Show a size given in rclone's text (see parseSize). */
  set value(text) {
    const { number, unit } = parseSize(text);
    this.number.value = number;
    this.unit = unit;
    this.#showUnit();
  }

  /** @brief Whether the number input is disabled. */
  get disabled() {
    return this.number.disabled;
  }

  /** @brief Lock or unlock the field; the number stays locked while "No limit" is chosen. */
  set disabled(isDisabled) {
    this.number.disabled = isDisabled || this.unit === "off";
    this.button.disabled = isDisabled;
    this.root.toggleAttribute("data-disabled", isDisabled);
    if (isDisabled) this.#close();
    this.isLocked = isDisabled;
  }

  /**
   * @brief Create one menu item per unit.
   */
  #buildMenu() {
    for (const { label, suffix } of UNITS) {
      const item = document.createElement("li");
      item.className = "size-field__option";
      item.setAttribute("role", "option");
      item.tabIndex = -1;
      item.dataset.suffix = suffix;
      item.textContent = label;
      item.addEventListener("click", () => this.#choose(suffix));
      this.menu.append(item);
      this.options.push(item);
    }
  }

  /**
   * @brief Show the chosen unit on the button and mark it in the menu.
   */
  #showUnit() {
    const chosen = UNITS.find((entry) => entry.suffix === this.unit) ?? UNITS[1];
    this.buttonLabel.textContent = chosen.label;
    for (const item of this.options) {
      item.setAttribute("aria-selected", String(item.dataset.suffix === this.unit));
    }
    const noLimit = this.unit === "off";
    this.number.disabled = noLimit || this.isLocked === true;
    this.number.placeholder = noLimit ? "Everything is synced" : "50";
  }

  /**
   * @brief Pick a unit, close the menu and move the focus on.
   * @param {string} suffix The suffix of the chosen unit.
   */
  #choose(suffix) {
    this.unit = suffix;
    this.#showUnit();
    this.#close();
    this.button.focus();
    if (suffix !== "off") this.number.focus();
  }

  /**
   * @brief Tell whether the menu is open.
   * @return {boolean} True if the menu is visible.
   */
  #isOpen() {
    return !this.menu.hidden;
  }

  /**
   * @brief Open the menu and focus the selected unit.
   */
  #open() {
    this.menu.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    const selected = this.options.find((item) => item.dataset.suffix === this.unit) ?? this.options[0];
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
        if (current >= 0) this.#choose(this.options[current].dataset.suffix);
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

/**
 * @brief Split rclone's size text into the number and the dropdown unit.
 * @param {string} text The size, e.g. "50M", "off" or "100".
 * @return {{number: string, unit: string}} The number text and the unit suffix.
 *
 * "50M" gives 50 + M, "off" gives no limit, "100" (rclone: kilobytes) gives 100 + k.
 * Units the dropdown does not offer (bytes, petabytes) are converted.
 */
export function parseSize(text) {
  const clean = String(text ?? "").trim();
  if (/^off$/i.test(clean)) return { number: "", unit: "off" };

  const match = /^(\d+(?:\.\d+)?)([bkmgtp]?)$/i.exec(clean);
  if (!match) return { number: "", unit: DEFAULT_UNIT };

  const [, number, letter] = match;
  const lower = letter.toLowerCase();
  if (lower === "") return { number, unit: "k" };
  if (lower in KILOBYTES_PER) {
    const kilobytes = Number(number) * KILOBYTES_PER[lower];
    return { number: String(Math.round(kilobytes * 1000) / 1000), unit: "k" };
  }
  return { number, unit: lower === "k" ? "k" : lower.toUpperCase() };
}
