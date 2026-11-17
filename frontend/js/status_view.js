/**
 * status_view.js
 * Draws the big "SYSTEM STATE" banner and the connection badge in the header.
 * It only displays; it never talks to the backend itself.
 */

/** What to show for each state the backend can report (plus "offline"). */
const STATE_DISPLAY = {
  idle:      { word: "Idle",         glyph: "-" },
  running:   { word: "Syncing",      glyph: ">" },
  stopping:  { word: "Stopping",     glyph: "~" },
  succeeded: { word: "Done",         glyph: "OK" },
  failed:    { word: "Failed",       glyph: "!" },
  cancelled: { word: "Stopped",      glyph: "X" },
  offline:   { word: "Backend offline", glyph: "?" },
};

const MODE_LABELS = {
  bisync: "Two-way",
  download: "Download only",
};

export class StatusView {
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

    // The duration of a running job ticks every second, independent of polling.
    setInterval(() => this.#renderDuration(), 1000);
  }

  /** Show a status received from the backend. */
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

  /** Show that the backend cannot be reached. */
  renderOffline(message) {
    this.lastStatus = null;
    this.#setConnected(false);
    this.#renderState("offline", message);
    this.activityBar.style.setProperty("--progress", "0");
  }

  // ------------------------------------------------------------------

  #renderState(state, message) {
    const display = STATE_DISPLAY[state] ?? STATE_DISPLAY.offline;
    this.panel.dataset.state = state;
    this.word.textContent = display.word;
    this.glyph.textContent = display.glyph;
    this.description.textContent = message;
  }

  #setConnected(isConnected) {
    this.connectionBadge.dataset.connected = String(isConnected);
    this.connectionText.textContent = isConnected ? "Backend connected" : "Backend offline";
  }

  #describeMode(status) {
    if (!status.mode) return "-";
    let label = MODE_LABELS[status.mode] ?? status.mode.toUpperCase();
    if (status.resync) label += " (first-time setup)";
    if (status.dry_run) label += " [dry run]";
    return label;
  }

  /** Progress of the run over the folder pairs, or how many pairs are active when nothing ran. */
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
   * Share of the folder pairs of the current run that are done: while running every finished
   * pair counts, afterwards only the successful ones, so a failure leaves a visible gap.
   * @param {object} status The status received from the backend.
   * @returns {number} A number from 0 to 1.
   */
  #progressOf(status) {
    const inRun = status.pairs.filter((pair) => pair.enabled && pair.state !== "idle");
    if (inRun.length === 0) return 0;
    const isBusy = status.state === "running" || status.state === "stopping";
    const counted = isBusy ? ["succeeded", "failed", "cancelled"] : ["succeeded"];
    return inRun.filter((pair) => counted.includes(pair.state)).length / inRun.length;
  }

  #renderDuration() {
    const status = this.lastStatus;
    if (!status || !status.started_at) {
      this.factDuration.textContent = "-";
      return;
    }
    // While running: time since start. Afterwards: the final duration.
    const end = status.finished_at ?? Date.now() / 1000;
    this.factDuration.textContent = this.#formatDuration(end - status.started_at);
  }

  #formatClock(epochSeconds) {
    return new Date(epochSeconds * 1000).toLocaleTimeString();
  }

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
