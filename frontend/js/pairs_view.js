/**
 * pairs_view.js
 * The overview of all folder pairs: one row per pair with its on/off (power) button,
 * name, folders, current state, an Edit button and a Delete button, plus the Add button.
 *
 * It only displays what the backend reports (`status.pairs`) and calls the
 * callbacks it receives; it never talks to the backend itself.
 *
 * The status is polled every second, so rows are UPDATED IN PLACE instead of
 * being rebuilt. That keeps scroll position, focus and hover intact.
 */

import { ConfirmDialog } from "./confirm_dialog.js";

/**
 * How each state looks: [short glyph, word]. The word is always shown, so the state
 * never depends on colour alone. "inactive" is not a backend state: it is what a
 * pair that is switched off shows, whatever its last run did.
 */
const BADGES = {
  idle:      ["-",   "Ready"],
  running:   [">",   "Syncing"],
  stopping:  ["~",   "Stopping"],
  succeeded: ["OK",  "Done"],
  failed:    ["!",   "Failed"],
  cancelled: ["X",   "Stopped"],
  inactive:  ["||",  "Inactive"],
};

export class PairsView {
  /**
   * @param {{
   *   onAdd: () => void,
   *   onEdit: (pairId: string) => void,
   *   onDelete: (pairId: string) => Promise<void>,
   *   onToggle: (pairId: string, enabled: boolean) => Promise<void>,
   * }} callbacks
   */
  constructor({ onAdd, onEdit, onDelete, onToggle }) {
    this.list = document.getElementById("pair-list");
    this.emptyNotice = document.getElementById("pair-empty");
    this.count = document.getElementById("pairs-count");
    this.addButton = document.getElementById("pair-add-button");
    this.message = document.getElementById("pairs-message");
    this.lockNote = document.getElementById("pairs-lock-note");

    this.onEdit = onEdit;
    this.onDelete = onDelete;
    this.onToggle = onToggle;
    this.confirmDialog = new ConfirmDialog();

    /** The row of every pair, by pair id: {element, powerButton, name, paths, note, glyph, word, ...}. */
    this.rows = new Map();
    this.isLocked = false;

    this.addButton.addEventListener("click", () => onAdd());

    // The list fades out at an edge while it can be scrolled further that way.
    this.list.addEventListener("scroll", () => this.#updateFades(), { passive: true });
    new ResizeObserver(() => this.#updateFades()).observe(this.list);
  }

  /**
   * Show the pairs reported by the backend.
   * @param {object[]} pairs   `status.pairs`
   * @param {boolean} isLocked True while a sync runs: nothing can be changed then.
   */
  render(pairs, isLocked) {
    this.#setLocked(isLocked);

    pairs.forEach((pair, index) => {
      const row = this.rows.get(pair.id) ?? this.#createRow(pair.id);
      this.#updateRow(row, pair);
      // Keep the order of the page equal to the order of the data, moving rows only if needed.
      if (this.list.children[index] !== row.element) {
        this.list.insertBefore(row.element, this.list.children[index] ?? null);
      }
    });

    const currentIds = new Set(pairs.map((pair) => pair.id));
    for (const [id, row] of this.rows) {
      if (!currentIds.has(id)) {
        row.element.remove();
        this.rows.delete(id);
      }
    }

    this.emptyNotice.hidden = pairs.length > 0;
    this.#renderCount(pairs);
    this.#updateFades();
  }

  showMessage(text, kind = "error") {
    this.message.textContent = text;
    this.message.dataset.kind = kind;
  }

  clearMessage() {
    this.showMessage("", "");
  }

  // ------------------------------------------------------------------

  #setLocked(isLocked) {
    this.isLocked = isLocked;
    this.addButton.disabled = isLocked;
    this.lockNote.hidden = !isLocked;
    for (const row of this.rows.values()) row.deleteButton.disabled = isLocked;
  }

  /** Mark which edges of the list have more content behind them (the CSS draws the fade). */
  #updateFades() {
    const { scrollTop, scrollHeight, clientHeight } = this.list;
    const hiddenAbove = scrollTop > 1;
    const hiddenBelow = scrollTop + clientHeight < scrollHeight - 1;
    this.list.toggleAttribute("data-fade-top", hiddenAbove);
    this.list.toggleAttribute("data-fade-bottom", hiddenBelow);
  }

  #renderCount(pairs) {
    const active = pairs.filter((pair) => pair.enabled).length;
    this.count.textContent = pairs.length === 0
      ? ""
      : `${pairs.length} ${pairs.length === 1 ? "pair" : "pairs"}, ${active} active`;
  }

  /** Build the (still empty) elements of one row. The content is filled in by #updateRow. */
  #createRow(pairId) {
    const element = document.createElement("li");
    element.className = "pair-row";

    const powerButton = document.createElement("button");
    powerButton.type = "button";
    powerButton.className = "btn btn--small btn--flat btn--icon btn--power";
    // The power symbol. (Static markup, nothing from the backend goes in here.)
    powerButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3h-2v10h2V3zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12c0 3.87-3.13 7-7 7A6.995 6.995 0 0 1 7.58 6.58L6.17 5.17A8.932 8.932 0 0 0 3 12a9 9 0 0 0 18 0c0-2.74-1.23-5.18-3.17-6.83z"/></svg>';

    const body = document.createElement("div");
    body.className = "pair-row__body";
    const name = document.createElement("p");
    name.className = "pair-row__name";
    const paths = document.createElement("p");
    paths.className = "pair-row__paths";
    const note = document.createElement("p");
    note.className = "pair-row__note";
    body.append(name, paths, note);

    const badge = document.createElement("span");
    badge.className = "pair-row__badge";
    const glyph = document.createElement("span");
    glyph.className = "pair-row__glyph";
    glyph.setAttribute("aria-hidden", "true");
    const word = document.createElement("span");
    badge.append(glyph, word);

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "btn btn--small btn--flat btn--icon";
    editButton.title = "Edit";
    // A pen. (Static markup, nothing from the backend goes in here.)
    editButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "btn btn--small btn--flat btn--icon btn--danger";
    deleteButton.title = "Delete";
    // A trash can. (Static markup, nothing from the backend goes in here.)
    deleteButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';

    element.append(body, badge, powerButton, editButton, deleteButton);

    const row = {
      element, powerButton, name, paths, note, glyph, word, editButton, deleteButton,
      serverEnabled: true,   // what the backend last said; the button is put back to this after a toggle
      isToggling: false,     // while true, polling must not reset the button under the user's finger
    };
    powerButton.addEventListener("click", () => this.#handleToggle(row, pairId));
    editButton.addEventListener("click", () => this.onEdit(pairId));
    deleteButton.addEventListener("click", () => this.#handleDelete(row, pairId));

    this.rows.set(pairId, row);
    return row;
  }

  #updateRow(row, pair) {
    const displayState = pair.enabled ? pair.state : "inactive";
    row.element.dataset.state = displayState;

    setText(row.name, pair.name);
    setText(row.paths, `${pair.local_path || "(no local folder yet)"}  ↔  ${pair.remote}`);

    const note = this.#noteFor(pair);
    setText(row.note, note);
    row.note.hidden = note === "";

    const [glyph, word] = BADGES[displayState] ?? BADGES.idle;
    setText(row.glyph, glyph);
    setText(row.word, word);

    row.serverEnabled = pair.enabled;
    if (!row.isToggling) this.#showPower(row, pair.enabled);
    row.powerButton.disabled = this.isLocked;
    row.powerButton.setAttribute("aria-label", `Active: ${pair.name}`);
    row.editButton.setAttribute("aria-label", `Edit ${pair.name}`);
    row.deleteButton.setAttribute("aria-label", `Delete ${pair.name}`);
    row.deleteButton.disabled = this.isLocked;
    row.pairName = pair.name;
  }

  /** The one line of explanation under a pair's folders (empty = nothing to say). */
  #noteFor(pair) {
    if (pair.message) return pair.message;
    if (pair.skips_pairs.length > 0) {
      const names = pair.skips_pairs.map((name) => `"${name}"`).join(", ");
      return `Skips the folder of ${names}, which lies inside this pair and is synced by ${pair.skips_pairs.length === 1 ? "that pair" : "those pairs"}. `
        + "If rclone asks for a first-time setup after this changed, run it once.";
    }
    return "";
  }

  /** Ask first (a popup), then let the app delete the pair. */
  async #handleDelete(row, pairId) {
    const confirmed = await this.confirmDialog.ask({
      title: "Delete folder pair?",
      text: `"${row.pairName}" will be removed from the list. `
        + "The files in its folders, on this PC and on the remote, are not touched.",
      confirmLabel: "Delete pair",
    });
    if (confirmed) await this.onDelete(pairId);
  }

  /** The power button is "pressed" (and green) while the pair is on. */
  #showPower(row, isOn) {
    row.powerButton.setAttribute("aria-pressed", String(isOn));
    row.powerButton.title = isOn ? "On - click to switch off" : "Off - click to switch on";
  }

  async #handleToggle(row, pairId) {
    row.isToggling = true;
    try {
      await this.onToggle(pairId, !row.serverEnabled);
    } finally {
      row.isToggling = false;
      // Whatever happened, show what the backend says now (undoes the click if it failed).
      this.#showPower(row, row.serverEnabled);
    }
  }
}

/** Only touch the DOM when the text really changed (the page is refreshed every second). */
function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}
