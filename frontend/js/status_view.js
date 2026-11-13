/**
 * status_view.js
 * Draws the big "SYSTEM STATE" banner and the connection badge in the header.
 * It only displays; it never talks to the backend itself.
 */

/** What to show for each state the backend can report (plus "offline"). */
const STATE_DISPLAY = {
  idle:      { word: "IDLE",         glyph: "-" },
  running:   { word: "SYNCING",      glyph: ">" },
  stopping:  { word: "STOPPING",     glyph: "~" },
  succeeded: { word: "DONE",         glyph: "OK" },
  failed:    { word: "FAILED",       glyph: "!" },
  cancelled: { word: "STOPPED",      glyph: "X" },
  offline:   { word: "BACKEND OFFLINE", glyph: "?" },
};

const MODE_LABELS = {
  bisync: "TWO-WAY",
  download: "DOWNLOAD ONLY",
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
    this.factExit = document.getElementById("fact-exit");
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
    this.factExit.textContent = status.exit_code === null || status.exit_code === undefined ? "-" : String(status.exit_code);
    this.#renderDuration();

    this.resyncNotice.hidden = !(status.needs_resync && status.state === "failed");
    this.rcloneNotice.hidden = status.rclone_available;
  }

  /** Show that the backend cannot be reached. */
  renderOffline(message) {
    this.lastStatus = null;
    this.#setConnected(false);
    this.#renderState("offline", message);
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
    this.connectionText.textContent = isConnected ? "BACKEND CONNECTED" : "BACKEND OFFLINE";
  }

  #describeMode(status) {
    if (!status.mode) return "-";
    let label = MODE_LABELS[status.mode] ?? status.mode.toUpperCase();
    if (status.resync) label += " (FIRST-TIME SETUP)";
    if (status.dry_run) label += " [DRY RUN]";
    return label;
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
