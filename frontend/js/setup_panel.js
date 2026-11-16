/**
 * setup_panel.js
 * The folder-pair card shows ONE of two views in the same spot:
 *
 *   "overview"  the list of all folder pairs (PairsView)
 *   "editor"    the setup of a single pair (SetupView)
 *
 * This class only switches between them. The CSS (components.css, section 8)
 * does the rest: the card never changes size when you switch, and the views slide.
 */

export class SetupPanel {
  constructor() {
    this.element = document.getElementById("setup-panel");
  }

  showOverview() {
    this.element.dataset.view = "overview";
  }

  showEditor() {
    this.element.dataset.view = "editor";
  }
}
