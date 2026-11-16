/**
 * setup_panel.js
 * The folder-pair card shows ONE of two views in the same spot:
 *
 *   "overview"  the list of all folder pairs (PairsView)
 *   "editor"    the setup of a single pair (SetupView)
 *
 * This class only switches between them. The CSS (components.css, section 7b)
 * slides the views; this class additionally makes the CARD grow or shrink
 * smoothly when the two views need different heights (for example a pair with
 * many exclusions), instead of the card jumping to the new height at once.
 */

export class SetupPanel {
  constructor() {
    this.element = document.getElementById("setup-panel");

    /** The height the card had before the current change (what the animation starts from). */
    this.settledHeight = this.element.offsetHeight;
    this.isAnimating = false;

    // Keep the settled height up to date while nothing is animating (the window
    // is resized, exclusions are added, ...).
    new ResizeObserver(() => {
      if (!this.isAnimating) this.settledHeight = this.element.offsetHeight;
    }).observe(this.element);
  }

  showOverview() {
    this.#switchTo("overview");
  }

  showEditor() {
    this.#switchTo("editor");
  }

  // ------------------------------------------------------------------

  /**
   * Show a view and animate the card from its old height to the new one.
   * The caller may already have filled the views with new content: the old
   * height is the one remembered from before, the new one is measured now.
   */
  #switchTo(view) {
    const panel = this.element;
    if (panel.dataset.view === view) return;

    this.#finishAnimation();                  // a fast second click: end the first animation
    const from = this.settledHeight;
    panel.dataset.view = view;
    const to = panel.offsetHeight;            // the card's natural height with the new view
    if (from === to) return;

    // Start where the card was, then let the CSS transition run to the new height.
    this.isAnimating = true;
    panel.style.height = `${from}px`;
    panel.offsetHeight;                       // apply the start height before changing it
    panel.style.transition = "height var(--slide-duration) var(--ease)";
    panel.style.height = `${to}px`;

    const noMotion = parseFloat(getComputedStyle(panel).transitionDuration) === 0;
    if (noMotion) {
      this.#finishAnimation();
      return;
    }
    this.onEnd = (event) => {
      if (event.propertyName === "height") this.#finishAnimation();
    };
    panel.addEventListener("transitionend", this.onEnd);
    this.safetyTimer = setTimeout(() => this.#finishAnimation(), 800);   // in case no event arrives
  }

  /** Hand the height back to the CSS (the card sizes itself again). */
  #finishAnimation() {
    if (!this.isAnimating) return;
    const panel = this.element;
    clearTimeout(this.safetyTimer);
    panel.removeEventListener("transitionend", this.onEnd);
    panel.style.transition = "";
    panel.style.height = "";
    this.isAnimating = false;
    this.settledHeight = panel.offsetHeight;
  }
}
