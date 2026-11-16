/**
 * pairs_view.js
 * The overview of all folder pairs: one row per pair with its on/off switch,
 * name, folders, current state and an Edit button, plus the Add button.
 *
 * It only displays what the backend reports (`status.pairs`) and calls the
 * callbacks it receives; it never talks to the backend itself.
 *
 * The status is polled every second, so rows are UPDATED IN PLACE instead of
 * being rebuilt. That keeps scroll position, focus and hover intact.
 */

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
   *   onToggle: (pairId: string, enabled: boolean) => Promise<void>,
   * }} callbacks
   */
  constructor({ onAdd, onEdit, onToggle }) {
    this.list = document.getElementById("pair-list");
    this.emptyNotice = document.getElementById("pair-empty");
    this.count = document.getElementById("pairs-count");
    this.addButton = document.getElementById("pair-add-button");
    this.message = document.getElementById("pairs-message");
    this.lockNote = document.getElementById("pairs-lock-note");

    this.onEdit = onEdit;
    this.onToggle = onToggle;

    /** The row of every pair, by pair id: {element, switchInput, name, paths, note, glyph, word, ...}. */
    this.rows = new Map();
    this.isLocked = false;

    this.addButton.addEventListener("click", () => onAdd());
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

    const switchLabel = document.createElement("label");
    switchLabel.className = "switch";
    const switchInput = document.createElement("input");
    switchInput.type = "checkbox";
    const slider = document.createElement("span");
    slider.className = "slider";
    switchLabel.append(switchInput, slider);

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
    editButton.className = "btn btn--small btn--plain";
    editButton.textContent = "Edit";

    element.append(switchLabel, body, badge, editButton);

    const row = {
      element, switchInput, name, paths, note, glyph, word, editButton,
      serverEnabled: true,   // what the backend last said; the switch is put back to this after a toggle
      isToggling: false,     // while true, polling must not reset the switch under the user's finger
    };
    switchInput.addEventListener("change", () => this.#handleToggle(row, pairId));
    editButton.addEventListener("click", () => this.onEdit(pairId));

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
    if (!row.isToggling) row.switchInput.checked = pair.enabled;
    row.switchInput.disabled = this.isLocked;
    row.switchInput.setAttribute("aria-label", `Active: ${pair.name}`);
    row.editButton.setAttribute("aria-label", `Edit ${pair.name}`);
  }

  /** The one line of explanation under a pair's folders (empty = nothing to say). */
  #noteFor(pair) {
    if (!pair.enabled) return "Switched off. It is skipped when you start a sync.";
    if (pair.message) return pair.message;
    if (pair.skips_pairs.length > 0) {
      const names = pair.skips_pairs.map((name) => `"${name}"`).join(", ");
      return `Skips the folder of ${names}, which lies inside this pair and is synced by ${pair.skips_pairs.length === 1 ? "that pair" : "those pairs"}. `
        + "If rclone asks for a first-time setup after this changed, run it once.";
    }
    return "";
  }

  async #handleToggle(row, pairId) {
    row.isToggling = true;
    try {
      await this.onToggle(pairId, row.switchInput.checked);
    } finally {
      row.isToggling = false;
      // Whatever happened, show what the backend says now (undoes the click if it failed).
      row.switchInput.checked = row.serverEnabled;
    }
  }
}

/** Only touch the DOM when the text really changed (the page is refreshed every second). */
function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}
