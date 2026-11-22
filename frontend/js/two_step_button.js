/**
 * @file two_step_button.js
 * @brief Protects a button against accidental clicks with a second confirming click.
 *
 * The first click only "arms" the button (the label changes, e.g. to "Discard changes?"),
 * and only a second click within a few seconds counts as confirmed. Used for small
 * questions; for bigger ones (deleting) there is a popup, see confirm_dialog.js.
 *
 * The button is also marked with data-armed="true" while armed, so the CSS can
 * make it stand out.
 */

/**
 * @brief A button that needs two clicks in a row to confirm.
 */
export class TwoStepButton {
  /**
   * @brief Remember the button and its texts.
   * @param {HTMLElement} button The button itself.
   * @param {HTMLElement} label The element inside the button that holds its text.
   * @param {string} armedText The text shown while the button is armed.
   * @param {number} [timeoutMs] How long the button stays armed.
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
   * @brief Register a click and tell whether it confirms the action.
   * @return {boolean} true if this click confirms the action,
   *                   false if it only armed the button.
   *
   * Call this on every click.
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

  /**
   * @brief Go back to the normal, unarmed button.
   */
  reset() {
    clearTimeout(this.timer);
    this.timer = null;
    this.label.textContent = this.idleText;
    delete this.button.dataset.armed;
  }
}
