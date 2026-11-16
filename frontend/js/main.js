/**
 * main.js
 * Entry point. Creates the views and the API client, connects them and runs
 * the polling loop that keeps the page up to date.
 *
 * Data flow:   backend --(poll)--> App --> views
 *              user click --> view callback --> App --> backend
 *
 * The folder-pair card has two views in one spot (see setup_panel.js):
 * the overview (PairsView) and the setup of one pair (SetupView).
 */

import { ApiClient, ApiError } from "./api.js";
import { ControlsView } from "./controls_view.js";
import { LogView } from "./log_view.js";
import { PairsView } from "./pairs_view.js";
import { SetupPanel } from "./setup_panel.js";
import { SetupView } from "./setup_view.js";
import { StatusView } from "./status_view.js";

/** How often the page asks the backend for news. */
const POLL_INTERVAL_MS = 1000;

class App {
  constructor() {
    this.api = new ApiClient();
    this.statusView = new StatusView();
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

    /** Id of the newest log line already shown. */
    this.lastLogId = 0;
    /** The newest status from the backend (null until the first answer). */
    this.status = null;
  }

  start() {
    this.#pollLoop();
  }

  // ------------------------------------------------------------------
  // Polling
  // ------------------------------------------------------------------

  /** Poll, wait, poll again. Waiting AFTER each round avoids overlapping requests. */
  async #pollLoop() {
    await this.#refresh();
    setTimeout(() => this.#pollLoop(), POLL_INTERVAL_MS);
  }

  async #refresh() {
    try {
      const status = await this.api.getStatus();
      const isBusy = status.state === "running" || status.state === "stopping";
      this.status = status;

      this.statusView.render(status);
      this.controlsView.render(status);
      this.pairsView.render(status.pairs, isBusy);
      this.setupView.setLocked(isBusy);

      const log = await this.api.getLog(this.lastLogId);
      this.logView.append(log.entries);
      this.lastLogId = log.last_id;
    } catch (error) {
      this.statusView.renderOffline(this.#messageOf(error));
    }
  }

  // ------------------------------------------------------------------
  // Folder pairs: overview
  // ------------------------------------------------------------------

  async #addPair() {
    this.pairsView.clearMessage();
    try {
      const defaults = await this.api.getDefaultSetup();
      this.setupView.open({ ...defaults, name: this.#suggestName() }, null);
      this.setupPanel.showEditor();
      this.setupView.focusName();
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
  }

  async #editPair(pairId) {
    this.pairsView.clearMessage();
    try {
      this.setupView.open(await this.api.getPair(pairId), pairId);
      this.setupPanel.showEditor();
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
  }

  /** Delete a pair (already confirmed in the overview). Never throws: a failure is shown instead. */
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

  /** Switch a pair on or off. Never throws: a failure is shown in the overview instead. */
  async #togglePair(pairId, enabled) {
    this.pairsView.clearMessage();
    try {
      await this.api.setPairEnabled(pairId, enabled);
    } catch (error) {
      this.pairsView.showMessage(this.#messageOf(error), "error");
    }
    await this.#refresh();  // the switch shows what the backend says, not what was clicked
  }

  // ------------------------------------------------------------------
  // Folder pairs: setup of one pair
  // ------------------------------------------------------------------

  async #savePair(pair) {
    try {
      const saved = this.setupView.pairId === null
        ? await this.api.createPair(pair)
        : await this.api.updatePair(this.setupView.pairId, pair);
      this.setupView.markSaved(saved, saved.id);  // shows what the backend actually stored
      this.setupView.showMessage("Folder pair saved.", "success");
      await this.#refresh();
    } catch (error) {
      this.setupView.showMessage(this.#messageOf(error), "error");
    }
  }

  async #resetSetup() {
    try {
      this.setupView.applyDefaults(await this.api.getDefaultSetup());
    } catch (error) {
      this.setupView.showMessage(this.#messageOf(error), "error");
    }
  }

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

  #backToOverview() {
    this.setupPanel.showOverview();
    this.pairsView.clearMessage();
  }

  /** "Folder pair 1", "Folder pair 2", ... : the first number no pair uses yet. */
  #suggestName() {
    const taken = new Set((this.status?.pairs ?? []).map((pair) => pair.name.toLowerCase()));
    let number = 1;
    while (taken.has(`folder pair ${number}`)) number += 1;
    return `Folder pair ${number}`;
  }

  // ------------------------------------------------------------------
  // Running
  // ------------------------------------------------------------------

  async #startSync(options) {
    this.controlsView.clearMessage();
    try {
      await this.api.startSync(options);
      await this.#refresh();  // show the new state immediately, do not wait for the next poll
    } catch (error) {
      this.controlsView.showMessage(this.#messageOf(error), "error");
    }
  }

  async #stopSync() {
    this.controlsView.clearMessage();
    try {
      await this.api.stopSync();
      await this.#refresh();
    } catch (error) {
      this.controlsView.showMessage(this.#messageOf(error), "error");
    }
  }

  #messageOf(error) {
    return error instanceof ApiError ? error.message : `Unexpected error: ${error}`;
  }
}

new App().start();
