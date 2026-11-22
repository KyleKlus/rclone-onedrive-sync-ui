/**
 * @file status_view.js
 * @brief The big "SYSTEM STATE" banner and the connection badge in the header.
 *
 * It only displays; it never talks to the backend itself.
 */

/** @brief What to show for each state the backend can report (plus "offline"). */
const STATE_DISPLAY = {
  idle:      { word: "Idle",         glyph: "-" },
  running:   { word: "Syncing",      glyph: ">" },
  stopping:  { word: "Stopping",     glyph: "~" },
  succeeded: { word: "Done",         glyph: "OK" },
  failed:    { word: "Failed",       glyph: "!" },
  cancelled: { word: "Stopped",      glyph: "X" },
  offline:   { word: "Backend offline", glyph: "?" },
};

/** @brief Readable names of the sync modes. */
const MODE_LABELS = {
  bisync: "Two-way",
  download: "Download only",
};

/**
 * @brief Draws the system state, the facts about the current run and the notices.
 */
export class StatusView {
  /**
   * @brief Look up the elements and start the once-per-second duration ticker.
   *
   * The duration of a running job ticks every second, independent of polling.
   */
  constructor() {
    this.panel = document.getElementById("status-panel");
    this.word = document.getElementById("state-word");
    this.glyph = document.getElementById("state-glyph");
    this.description = document.getElementById("state-description");
    this.resyncNotice = document.getElementById("resync-notice");
    this.rcloneNotice = document.getElementById("rclone-notice");
    this.factMode = document.getElementById("fact-mode");
    this.factStarted = document.getElementById("fact-started");
    this.factDuration = document.getElementById("fact-duration");
    this.factPairs = document.getElementById("fact-pairs");
    this.resyncPairs = document.getElementById("resync-pairs");
    this.activityBar = document.getElementById("activity-bar");
    this.connectionBadge = document.getElementById("connection-badge");
    this.connectionText = document.getElementById("connection-text");

    this.lastStatus = null;

    setInterval(() => this.#renderDuration(), 1000);
  }

  /**
   * @brief Show a status received from the backend.
   * @param {object} status The status received from the backend.
   */
  render(status) {
    this.lastStatus = status;
    this.#setConnected(true);
    this.#renderState(status.state, status.message);

    this.factMode.textContent = this.#describeMode(status);
    this.factStarted.textContent = status.started_at ? this.#formatClock(status.started_at) : "-";
    this.factPairs.textContent = this.#describePairs(status);
    this.activityBar.style.setProperty("--progress", String(this.#progressOf(status)));
    this.#renderDuration();

    const needResync = status.pairs.filter((pair) => pair.needs_resync).map((pair) => `"${pair.name}"`);
    this.resyncPairs.textContent = needResync.join(", ");
    this.resyncNotice.hidden = !(status.needs_resync && status.state === "failed");
    this.rcloneNotice.hidden = status.rclone_available;
  }

  /**
   * @brief Show that the backend cannot be reached.
   * @param {string} message Why, in words for the user.
   */
  renderOffline(message) {
    this.lastStatus = null;
    this.#setConnected(false);
    this.#renderState("offline", message);
    this.activityBar.style.setProperty("--progress", "0");
  }

  /**
   * @brief Show the state word, glyph and description.
   * @param {string} state One of the keys of STATE_DISPLAY.
   * @param {string} message The description under the state word.
   */
  #renderState(state, message) {
    const display = STATE_DISPLAY[state] ?? STATE_DISPLAY.offline;
    this.panel.dataset.state = state;
    this.word.textContent = display.word;
    this.glyph.textContent = display.glyph;
    this.description.textContent = message;
  }

  /**
   * @brief Show the connection badge of the header.
   * @param {boolean} isConnected True if the backend answered.
   */
  #setConnected(isConnected) {
    this.connectionBadge.dataset.connected = String(isConnected);
    this.connectionText.textContent = isConnected ? "Backend connected" : "Backend offline";
  }

  /**
   * @brief Build the text for the mode fact.
   * @param {object} status The status received from the backend.
   * @return {string} Mode, with first-time setup and dry run marked.
   */
  #describeMode(status) {
    if (!status.mode) return "-";
    let label = MODE_LABELS[status.mode] ?? status.mode.toUpperCase();
    if (status.resync) label += " (first-time setup)";
    if (status.dry_run) label += " [dry run]";
    return label;
  }

  /**
   * @brief Build the text for the folder-pairs fact.
   * @param {object} status The status received from the backend.
   * @return {string} Progress of the run, or how many pairs are active when nothing ran.
   */
  #describePairs(status) {
    const inRun = status.pairs.filter((pair) => pair.enabled && pair.state !== "idle");
    if (inRun.length === 0) {
      const active = status.pairs.filter((pair) => pair.enabled).length;
      return `${active} active`;
    }
    const isBusy = status.state === "running" || status.state === "stopping";
    const finished = inRun.filter((pair) => ["succeeded", "failed", "cancelled"].includes(pair.state));
    const succeeded = inRun.filter((pair) => pair.state === "succeeded");
    return isBusy
      ? `${finished.length} of ${inRun.length} done`
      : `${succeeded.length} of ${inRun.length} OK`;
  }

  /**
   * @brief Compute the share of the folder pairs of the current run that are done.
   * @param {object} status The status received from the backend.
   * @return {number} A number from 0 to 1.
   *
   * While running every finished pair counts, afterwards only the successful ones,
   * so a failure leaves a visible gap.
   */
  #progressOf(status) {
    const inRun = status.pairs.filter((pair) => pair.enabled && pair.state !== "idle");
    if (inRun.length === 0) return 0;
    const isBusy = status.state === "running" || status.state === "stopping";
    const counted = isBusy ? ["succeeded", "failed", "cancelled"] : ["succeeded"];
    return inRun.filter((pair) => counted.includes(pair.state)).length / inRun.length;
  }

  /**
   * @brief Show the elapsed time of the run.
   *
   * While running: time since start. Afterwards: the final duration.
   */
  #renderDuration() {
    const status = this.lastStatus;
    if (!status || !status.started_at) {
      this.factDuration.textContent = "-";
      return;
    }
    const end = status.finished_at ?? Date.now() / 1000;
    this.factDuration.textContent = this.#formatDuration(end - status.started_at);
  }

  /**
   * @brief Format a time of day.
   * @param {number} epochSeconds Unix time in seconds.
   * @return {string} The local time of day.
   */
  #formatClock(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString();
  }

  /**
   * @brief Format a duration as mm:ss or h:mm:ss.
   * @param {number} totalSeconds Length of the duration.
   * @return {string} The formatted duration.
   */
  #formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const pad = (n) => String(n).padStart(2, "0");
    return hours > 0
      ? `${hours}:${pad(minutes % 60)}:${pad(seconds % 60)}`
      : `${pad(minutes)}:${pad(seconds % 60)}`;
  }
}
