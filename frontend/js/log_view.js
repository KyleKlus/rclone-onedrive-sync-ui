/**
 * log_view.js
 * The "LIVE LOG" panel. Appends lines, colours them by severity and keeps the
 * view scrolled to the bottom when AUTO-SCROLL is on.
 */

/** Never keep more lines in the page than this (the backend keeps its own copy). */
const MAX_VISIBLE_LINES = 5000;

/** Text markers so severity is readable without relying on colour. */
const LEVEL_MARKERS = {
  error: "[ERROR] ",
  warning: "[WARN] ",
};

export class LogView {
  constructor() {
    this.output = document.getElementById("log-output");
    this.emptyNotice = document.getElementById("log-empty");
    this.autoScroll = document.getElementById("log-autoscroll");
    this.clearButton = document.getElementById("log-clear-button");

    this.lineCount = 0;

    this.clearButton.addEventListener("click", () => this.clear());
  }

  /** Add new log entries ({id, timestamp, level, text, source}) at the bottom. */
  append(entries) {
    if (entries.length === 0) return;

    this.emptyNotice.hidden = true;
    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      fragment.append(this.#createLine(entry));
    }
    this.output.append(fragment);
    this.lineCount += entries.length;

    this.#trimOldLines();
    if (this.autoScroll.checked) {
      this.output.scrollTop = this.output.scrollHeight;
    }
  }

  /** Empty the view only. The backend keeps its log; already-seen lines do not return. */
  clear() {
    this.output.querySelectorAll(".log-line").forEach((line) => line.remove());
    this.lineCount = 0;
    this.emptyNotice.hidden = false;
  }

  // ------------------------------------------------------------------

  #createLine(entry) {
    const line = document.createElement("div");
    line.className = `log-line log-line--${entry.level}`;

    const time = document.createElement("span");
    time.className = "log-line__time";
    time.textContent = entry.timestamp;

    const text = document.createElement("span");
    text.className = "log-line__text";
    text.textContent = (LEVEL_MARKERS[entry.level] ?? "") + entry.text;  // the tag is prepended below

    // Pairs sync at the same time, so their lines are mixed: tag each with its pair's name.
    if (entry.source) {
      const source = document.createElement("span");
      source.className = "log-line__source";
      source.textContent = `[${entry.source}] `;
      text.prepend(source);
    }

    line.append(time, text);
    return line;
  }

  #trimOldLines() {
    while (this.lineCount > MAX_VISIBLE_LINES) {
      this.output.querySelector(".log-line")?.remove();
      this.lineCount -= 1;
    }
  }
}
