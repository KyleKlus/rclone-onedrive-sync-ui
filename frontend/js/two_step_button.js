/**
 * two_step_button.js
 * Protects a button against accidental clicks: the first click only "arms" it
 * (the label changes, e.g. to "Discard changes?"), and only a second click
 * within a few seconds counts as confirmed. Used for small questions; for bigger
 * ones (deleting) there is a popup, see confirm_dialog.js.
 *
 * The button is also marked with data-armed="true" while armed, so the CSS can
 * make it stand out.
 */

export class TwoStepButton {
  /**
   * @param {HTMLElement} button      The button itself.
   * @param {HTMLElement} label       The element inside the button that holds its text.
   * @param {string} armedText        The text shown while the button is armed.
   * @param {number} [timeoutMs]      How long the button stays armed.
   */
  constructor(button, label, armedText, timeoutMs = 4000) {
    this.button = button;
    this.label = label;
    this.idleText = label.textContent;
    this.armedText = armedText;
    this.timeoutMs = timeoutMs;
    this.timer = null;
  }

  /**
   * Call this on every click.
   * @returns {boolean} true if this click confirms the action,
   *                    false if it only armed the button.
   */
  confirmed() {
    if (this.timer !== null) {
      this.reset();
      return true;
    }
    this.label.textContent = this.armedText;
    this.button.dataset.armed = "true";
    this.timer = setTimeout(() => this.reset(), this.timeoutMs);
    return false;
  }

  /** Back to the normal, unarmed button. */
  reset() {
    clearTimeout(this.timer);
    this.timer = null;
    this.label.textContent = this.idleText;
    delete this.button.dataset.armed;
  }
}
