/**
 * @file main.js
 * @brief Entry point that creates the views and the API client, connects them and runs the polling loop.
 *
 * Data flow:   backend --(poll)--> App --> views
 *              user click --> view callback --> App --> backend
 *
 * The folder-pair card has two views in one spot (see setup_panel.js):
 * the overview (PairsView) and the setup of one pair (SetupView).
 */

import { ApiClient, ApiError } from "./api.js";
import { ControlsView } from "./controls_view.js";
import { ExpiryView } from "./expiry_view.js";
import { LogView } from "./log_view.js";
import { PairsView } from "./pairs_view.js";
import { SetupPanel } from "./setup_panel.js";
import { SetupView } from "./setup_view.js";
import { StatusView } from "./status_view.js";

/** @brief How often the page asks the backend for news. */
const POLL_INTERVAL_MS = 1000;

/**
 * @brief The application: wires the views to the backend and keeps the page up to date.
 */
class App {
  /**
   * @brief Create the API client and all views and connect their callbacks.
   */
  constructor() {
    this.api = new ApiClient();
    this.statusView = new StatusView();
    this.expiryView = new ExpiryView({ onCheck: () => this.#checkRemotes() });
    this.logView = new LogView();
    this.controlsView = new ControlsView({
      onStart: (options) => this.#startSync(options),
      onStop: () => this.#stopSync(),
    });
    this.setupPanel = new SetupPanel();
    this.pairsView = new PairsView({
      onAdd: () => this.#addPair(),
      onEdit: (pairId) => this.#editPair(pairId),
      onDelete: (pairId) => this.#deletePairFromOverview(pairId),
      onToggle: (pairId, enabled) => this.#togglePair(pairId, enabled),
    });
    this.setupView = new SetupView({
      onSave: (pair) => this.#savePair(pair),
      onReset: () => this.#resetSetup(),
      onDelete: () => this.#deletePair(),
      onBack: () => this.#backToOverview(),
    });

    this.lastLogId = 0;
    this.status = null;
  }

  /**
   * @brief Prepare the setup form and start the polling loop.
   */
  start() {
    this.#prepareEditor();
    this.#pollLoop();
  }

  /**
   * @brief Fill the still hidden setup form with the defaults once at startup.
   *
   * An empty form is shorter than a filled one, so without this the card would grow
   * the first time a pair is opened. Failing here is harmless: the form is then
   * simply filled when a pair is opened.
   */
  async #prepareEditor() {
    try {
      this.setupView.setRemotes(await this.#loadRemotes());
      this.setupView.open({ ...(await this.api.getDefaultSetup()), name: "" }, null);
    } catch {
    }
  }

  /**
   * @brief Poll, wait, poll again.
   *
   * Waiting after each round avoids overlapping requests.
   */
  async #pollLoop() {
    await this.#refresh();
    setTimeout(() => this.#pollLoop(), POLL_INTERVAL_MS);
  }

  /**
   * @brief Fetch status and log once and show them; show the offline state on failure.
   */
  async #refresh() {
    try {
      const status = await this.api.getStatus();
      const isBusy = status.state === "running" || status.state === "stopping";
      this.status = status;

      this.statusView.render(status);
      this.expiryView.render(status.remote_health, isBusy);
      this.controlsView.render(status);
      this.pairsView.render(status.pairs, isBusy);
      this.setupView.setLocked(isBusy);

      const log = await this.api.getLog(this.lastLogId);
      this.logView.append(log.entries);
      this.lastLogId = log.last_id;
    } catch (error) {
      this.statusView.renderOffline(this.#messageOf(error));
      this.expiryView.hide();
    }
  }

  /**
   * @brief Ask the backend to check the remote logins again.
   *
   * Never throws: the next poll shows the result.
   */
  async #checkRemotes() {
    try {
      await this.api.checkRemotes();
    } catch {
    }
    await this.#refresh();
  }

  /**
   * @brief Open the setup form for a new folder pair.
   */
  async #addPair() {
    this.pairsView.clearMessage();
    try {
      const defaults = await this.api.getDefaultSetup();
      this.setupView.setRemotes(await this.#loadRemotes());
      this.setupView.open({ ...defaults, name: this.#suggestName() }, null);
      this.setupPanel.showEditor();
      this.setupView.focusName();
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Open the setup form for an existing folder pair.
   * @param {string} pairId Id of the pair.
   */
  async #editPair(pairId) {
    this.pairsView.clearMessage();
    try {
      const pair = await this.api.getPair(pairId);
      this.setupView.setRemotes(await this.#loadRemotes());
      this.setupView.open(pair, pairId);
      this.setupPanel.showEditor();
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Delete a pair from the overview.
   * @param {string} pairId Id of the pair.
   *
   * Already confirmed in the overview. Never throws: a failure is shown instead.
   */
  async #deletePairFromOverview(pairId) {
    this.pairsView.clearMessage();
    try {
      await this.api.deletePair(pairId);
      this.pairsView.showMessage("Folder pair deleted. Its files were not touched.", "success");
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
    await this.#refresh();
  }

  /**
   * @brief Switch a pair on or off.
   * @param {string} pairId Id of the pair.
   * @param {boolean} enabled True to switch the pair on.
   *
   * Never throws: a failure is shown in the overview instead. The page is refreshed
   * afterwards because the switch shows what the backend says, not what was clicked.
   */
  async #togglePair(pairId, enabled) {
    this.pairsView.clearMessage();
    try {
      await this.api.setPairEnabled(pairId, enabled);
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
    await this.#refresh();
  }

  /**
   * @brief Create or update a pair from the setup form.
   * @param {object} pair The setup read from the form.
   *
   * The form is filled with what the backend actually stored.
   */
  async #savePair(pair) {
    try {
      const saved = this.setupView.pairId === null
        ? await this.api.createPair(pair)
        : await this.api.updatePair(this.setupView.pairId, pair);
      this.setupView.markSaved(saved, saved.id);
      this.setupView.showMessage("Folder pair saved.", "success");
      await this.#refresh();
    } catch (error) {
      this.setupView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Put the defaults of a pair back into the setup form.
   */
  async #resetSetup() {
    try {
      this.setupView.applyDefaults(await this.api.getDefaultSetup());
    } catch (error) {
      this.setupView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Delete the pair open in the setup form and return to the overview.
   */
  async #deletePair() {
    const pairId = this.setupView.pairId;
    if (pairId === null) return;
    try {
      await this.api.deletePair(pairId);
      this.#backToOverview();
      this.pairsView.showMessage("Folder pair deleted. Its files were not touched.", "success");
      await this.#refresh();
    } catch (error) {
      this.setupView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Fetch the remotes rclone knows.
   * @return {Promise<{remotes: object[], error: string}>} The remotes, or an empty list with the reason.
   *
   * Asked fresh every time the form opens, so a remote added with "rclone config"
   * shows up without reloading the page. Never throws.
   */
  async #loadRemotes() {
    try {
      return await this.api.getRemotes();
    } catch (error) {
      return { remotes: [], error: this.#messageOf(error) };
    }
  }

  /**
   * @brief Show the overview of folder pairs again.
   */
  #backToOverview() {
    this.setupPanel.showOverview();
    this.pairsView.clearMessage();
  }

  /**
   * @brief Suggest a name for a new pair.
   * @return {string} "Folder pair N" with the first number no pair uses yet.
   */
  #suggestName() {
    const taken = new Set((this.status?.pairs ?? []).map((pair) => pair.name.toLowerCase()));
    let number = 1;
    while (taken.has(`folder pair ${number}`)) number += 1;
    return `Folder pair ${number}`;
  }

  /**
   * @brief Start a sync and show the new state at once.
   * @param {{mode: string, resync: boolean, dryRun: boolean}} options What kind of sync to run.
   */
  async #startSync(options) {
    this.controlsView.clearMessage();
    try {
      await this.api.startSync(options);
      await this.#refresh();
    } catch (error) {
      this.controlsView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Stop the running sync.
   */
  async #stopSync() {
    this.controlsView.clearMessage();
    try {
      await this.api.stopSync();
      await this.#refresh();
    } catch (error) {
      this.controlsView.showMessage(this.#messageOf(error), "error");
    }
  }

  /**
   * @brief Turn an error into text for the user.
   * @param {Error} error The error that was caught.
   * @return {string} The message to show.
   */
  #messageOf(error) {
    return error instanceof ApiError ? error.message : `Unexpected error: ${error}`;
  }
}

new App().start();
