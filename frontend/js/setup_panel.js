/**
 * @file setup_panel.js
 * @brief Switches the folder-pair card between its overview and its editor and animates the height.
 *
 * The folder-pair card shows ONE of two views in the same spot:
 *
 *   "overview"  the list of all folder pairs (PairsView)
 *   "editor"    the setup of a single pair (SetupView)
 *
 * This class only switches between them. The CSS (components.css)
 * slides the views; this class additionally makes the CARD grow or shrink
 * smoothly when the two views need different heights (for example a pair with
 * many exclusions), instead of the card jumping to the new height at once.
 */

/**
 * @brief The folder-pair card with its two views.
 */
export class SetupPanel {
  /**
   * @brief Remember the card's height and watch it for changes.
   *
   * Keeps the settled height up to date while nothing is animating (the window
   * is resized, exclusions are added, ...).
   */
  constructor() {
    this.element = document.getElementById("setup-panel");

    this.settledHeight = this.element.offsetHeight;
    this.isAnimating = false;

    new ResizeObserver(() => {
      if (!this.isAnimating) this.settledHeight = this.element.offsetHeight;
    }).observe(this.element);
  }

  /**
   * @brief Show the list of all folder pairs.
   */
  showOverview() {
    this.#switchTo("overview");
  }

  /**
   * @brief Show the setup of a single pair.
   */
  showEditor() {
    this.#switchTo("editor");
  }

  /**
   * @brief Show a view and animate the card from its old height to the new one.
   * @param {string} view "overview" or "editor".
   *
   * The caller may already have filled the views with new content: the old
   * height is the one remembered from before, the new one is measured now.
   * The start height is applied before the target height is set, so the CSS
   * transition has something to run from. A safety timer ends the animation in
   * case no transitionend event arrives. A fast second click ends the first
   * animation first.
   */
  #switchTo(view) {
    const panel = this.element;
    if (panel.dataset.view === view) return;

    this.#finishAnimation();
    const from = this.settledHeight;
    panel.dataset.view = view;
    const to = panel.offsetHeight;
    if (from === to) return;

    this.isAnimating = true;
    panel.style.height = `${from}px`;
    panel.offsetHeight;
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
    this.safetyTimer = setTimeout(() => this.#finishAnimation(), 800);
  }

  /**
   * @brief Hand the height back to the CSS so the card sizes itself again.
   */
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
