/**
 * @file log_view.js
 * @brief The "LIVE LOG" panel.
 *
 * Appends lines, colours them by severity and keeps the view scrolled to the bottom
 * when AUTO-SCROLL is on.
 */

/** @brief Never keep more lines in the page than this (the backend keeps its own copy). */
const MAX_VISIBLE_LINES = 5000;

/** @brief Text markers so severity is readable without relying on colour. */
const LEVEL_MARKERS = {
  error: "[ERROR] ",
  warning: "[WARN] ",
};

/**
 * @brief The scrolling list of log lines.
 */
export class LogView {
  /**
   * @brief Look up the elements and wire the Clear button.
   */
  constructor() {
    this.output = document.getElementById("log-output");
    this.emptyNotice = document.getElementById("log-empty");
    this.autoScroll = document.getElementById("log-autoscroll");
    this.clearButton = document.getElementById("log-clear-button");

    this.lineCount = 0;

    this.clearButton.addEventListener("click", () => this.clear());
  }

  /**
   * @brief Add new log entries at the bottom.
   * @param {{id: number, timestamp: string, level: string, text: string, source: string}[]} entries The new lines.
   */
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

  /**
   * @brief Empty the view.
   *
   * Only the view is emptied. The backend keeps its log; already-seen lines do not return.
   */
  clear() {
    this.output.querySelectorAll(".log-line").forEach((line) => line.remove());
    this.lineCount = 0;
    this.emptyNotice.hidden = false;
  }

  /**
   * @brief Build the element of one log line.
   * @param {{timestamp: string, level: string, text: string, source: string}} entry The log entry.
   * @return {HTMLDivElement} The line with time, optional pair tag and text.
   *
   * Pairs sync at the same time, so their lines are mixed: each line is tagged with its
   * pair's name. The tag is prepended after the severity marker has been put into the text.
   */
  #createLine(entry) {
    const line = document.createElement("div");
    line.className = `log-line log-line--${entry.level}`;

    const time = document.createElement("span");
    time.className = "log-line__time";
    time.textContent = entry.timestamp;

    const text = document.createElement("span");
    text.className = "log-line__text";
    text.textContent = (LEVEL_MARKERS[entry.level] ?? "") + entry.text;

    if (entry.source) {
      const source = document.createElement("span");
      source.className = "log-line__source";
      source.textContent = `[${entry.source}] `;
      text.prepend(source);
    }

    line.append(time, text);
    return line;
  }

  /**
   * @brief Remove the oldest lines while there are more than the allowed maximum.
   */
  #trimOldLines() {
    while (this.lineCount > MAX_VISIBLE_LINES) {
      this.output.querySelector(".log-line")?.remove();
      this.lineCount -= 1;
    }
  }
}
