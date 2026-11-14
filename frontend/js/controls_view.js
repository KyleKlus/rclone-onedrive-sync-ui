/**
 * controls_view.js
 * The "RUN" panel: mode selection, dry-run checkbox, Start / Stop / First-time setup.
 *
 * The view does not decide what happens on a click. It calls the callbacks it
 * receives (onStart, onStop), which keeps this file free of backend logic.
 */

export class ControlsView {
  /**
   * @param {{
   *   onStart: (options: {mode: string, dryRun: boolean, resync: boolean}) => void,
   *   onStop: () => void,
   * }} callbacks
   */
  constructor({ onStart, onStop }) {
    this.modeInputs = document.querySelectorAll('input[name="sync-mode"]');
    this.modePicker = document.querySelector(".mode-picker");
    this.dryRun = document.getElementById("dry-run");
    this.startButton = document.getElementById("start-button");
    this.startLabel = document.getElementById("start-label");
    this.stopButton = document.getElementById("stop-button");
    this.resyncButton = document.getElementById("resync-button");
    this.message = document.getElementById("control-message");

    this.startButton.addEventListener("click", () =>
      onStart({ mode: this.#selectedMode(), dryRun: this.dryRun.checked, resync: false })
    );
    this.resyncButton.addEventListener("click", () =>
      onStart({ mode: "bisync", dryRun: this.dryRun.checked, resync: true })
    );
    this.stopButton.addEventListener("click", () => onStop());
  }

  /** Enable / disable controls to match the system state. */
  render(status) {
    const isBusy = status.state === "running" || status.state === "stopping";

    this.startButton.disabled = isBusy;
    this.resyncButton.disabled = isBusy;
    this.stopButton.disabled = status.state !== "running";
    this.dryRun.disabled = isBusy;
    this.modePicker.disabled = isBusy;
    this.modeInputs.forEach((input) => { input.disabled = isBusy; });

    this.startLabel.textContent = isBusy ? "Sync in progress ..." : "Start sync";
  }

  /** Show a short message under the buttons (e.g. why a start was refused). */
  showMessage(text, kind = "error") {
    this.message.textContent = text;
    this.message.dataset.kind = kind;
  }

  clearMessage() {
    this.showMessage("", "");
  }

  #selectedMode() {
    return [...this.modeInputs].find((input) => input.checked).value;
  }
}
