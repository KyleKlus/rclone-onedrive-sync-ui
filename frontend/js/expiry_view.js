/**
 * @file expiry_view.js
 * @brief The "login expired" badge in the header and the popover that explains how to fix it.
 *
 * The badge is only visible while at least one remote used by an active folder pair has
 * an expired login. Clicking it opens a list of those remotes, each with the command that
 * signs in again (`rclone config reconnect <remote>:`) and a button that copies it.
 * It only displays; it never talks to the backend itself.
 */

/** How long the "Copied" confirmation stays on a copy button. */
const COPIED_LABEL_MS = 1500;

export class ExpiryView {
  /**
   * @param {{onCheck: function(): void}} callbacks `onCheck` runs when "Check again" is pressed.
   */
  constructor({ onCheck }) {
    this.root = document.getElementById("expiry");
    this.badge = document.getElementById("expiry-badge");
    this.text = document.getElementById("expiry-text");
    this.popover = document.getElementById("expiry-popover");
    this.intro = document.getElementById("expiry-intro");
    this.list = document.getElementById("expiry-list");
    this.checkButton = document.getElementById("expiry-check");
    this.checked = document.getElementById("expiry-checked");
    this.onCheck = onCheck;
    this.signature = "";

    this.badge.addEventListener("click", () => (this.#isOpen() ? this.#close() : this.#open()));
    this.checkButton.addEventListener("click", () => this.onCheck());
    this.root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.#isOpen()) {
        this.#close();
        this.badge.focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (this.#isOpen() && !this.root.contains(event.target)) this.#close();
    });
  }

  /**
   * Show the expired logins of a status, or hide the badge when there are none.
   * @param {{expired: object[], checking: boolean, checked_at: ?number}} health The `remote_health` of a status.
   * @param {boolean} isBusy True while a sync runs; checks are paused then.
   */
  render(health, isBusy) {
    const expired = health?.expired ?? [];
    this.root.hidden = expired.length === 0;
    if (expired.length === 0) {
      this.#close();
      this.signature = "";
      return;
    }

    this.text.textContent = expired.length === 1
      ? `Login expired: ${expired[0].name}`
      : `${expired.length} logins expired`;

    const signature = JSON.stringify(expired.map((item) => [item.name, item.reason, item.command]));
    if (signature !== this.signature) {
      this.signature = signature;
      this.#renderList(expired);
    }

    this.intro.textContent = expired.length === 1
      ? "rclone can no longer log in to this remote. Sign in again by running the command below in a terminal, then press Check again."
      : "rclone can no longer log in to these remotes. Sign in again by running the commands below in a terminal, then press Check again.";

    this.checkButton.disabled = health.checking || isBusy;
    this.checkButton.textContent = health.checking ? "Checking ..." : "Check again";
    this.checked.textContent = this.#describeCheck(health, isBusy);
  }

  /** Hide everything, e.g. while the backend cannot be reached. */
  hide() {
    this.root.hidden = true;
    this.#close();
  }

  #describeCheck(health, isBusy) {
    if (isBusy) return "Checking is paused while a sync runs.";
    if (!health.checked_at) return "";
    return `Last checked ${new Date(health.checked_at * 1000).toLocaleTimeString()}`;
  }

  #renderList(expired) {
    this.list.replaceChildren(...expired.map((item) => this.#createItem(item)));
  }

  #createItem(item) {
    const entry = document.createElement("li");
    entry.className = "expiry__item";

    const name = document.createElement("strong");
    name.className = "expiry__name";
    name.textContent = `${item.name}:`;

    const command = document.createElement("code");
    command.className = "expiry__command";
    command.textContent = item.command;

    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "btn expiry__copy";
    copy.textContent = "Copy";
    copy.setAttribute("aria-label", `Copy the command to reconnect ${item.name}`);
    copy.addEventListener("click", () => this.#copy(item.command, copy));

    const reason = document.createElement("p");
    reason.className = "expiry__reason";
    reason.textContent = item.reason;

    const row = document.createElement("div");
    row.className = "expiry__row";
    row.append(command, copy);

    entry.append(name, row, reason);
    return entry;
  }

  /**
   * Copy a command to the clipboard and say so on its button.
   * @param {string} command The text to copy.
   * @param {HTMLButtonElement} button The button that was pressed.
   */
  async #copy(command, button) {
    let label = "Copied";
    try {
      await navigator.clipboard.writeText(command);
    } catch {
      label = "Select it";
      const range = document.createRange();
      range.selectNodeContents(button.parentElement.querySelector(".expiry__command"));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
    }
    button.textContent = label;
    setTimeout(() => { button.textContent = "Copy"; }, COPIED_LABEL_MS);
  }

  #isOpen() {
    return !this.popover.hidden;
  }

  #open() {
    this.popover.hidden = false;
    this.badge.setAttribute("aria-expanded", "true");
  }

  #close() {
    this.popover.hidden = true;
    this.badge.setAttribute("aria-expanded", "false");
  }
}
