/**
 * @file confirm_dialog.js
 * @brief A popup that asks the user to confirm something ("Delete this folder pair?").
 *
 * It uses the browser's own <dialog> element (in index.html): the page behind it is dimmed
 * and cannot be clicked, the keyboard stays inside the popup and Escape closes it.
 *
 * Usage:   if (await dialog.ask({ title, text, confirmLabel })) { ...do it... }
 */

/**
 * @brief Wrapper around the confirmation <dialog> of index.html.
 */
export class ConfirmDialog {
  /**
   * @brief Look up the dialog's elements.
   */
  constructor() {
    this.dialog = document.getElementById("confirm-dialog");
    this.title = document.getElementById("confirm-title");
    this.text = document.getElementById("confirm-text");
    this.confirmButton = document.getElementById("confirm-ok");
  }

  /**
   * @brief Show the popup and wait for the answer.
   * @param {{title: string, text: string, confirmLabel: string}} options Texts of the popup.
   * @return {Promise<boolean>} true if the user confirmed; false for Cancel and Escape.
   *
   * Escape closes the dialog without setting a new return value, so the old one is cleared first.
   */
  ask({ title, text, confirmLabel }) {
    this.title.textContent = title;
    this.text.textContent = text;
    this.confirmButton.textContent = confirmLabel;

    return new Promise((resolve) => {
      this.dialog.returnValue = "";
      this.dialog.addEventListener(
        "close",
        () => resolve(this.dialog.returnValue === "confirm"),
        { once: true },
      );
      this.dialog.showModal();
    });
  }
}
