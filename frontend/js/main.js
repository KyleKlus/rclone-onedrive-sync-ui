/**
 * main.js
 * Entry point. Creates the views and the API client, connects them and runs
 * the polling loop that keeps the page up to date.
 *
 * Data flow:   backend --(poll)--> App --> views
 *              user click --> view callback --> App --> backend
 */

import { ApiClient, ApiError } from "./api.js";
import { ControlsView } from "./controls_view.js";
import { LogView } from "./log_view.js";
import { SettingsView } from "./settings_view.js";
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
    this.settingsView = new SettingsView({
      onSave: (settings) => this.#saveSettings(settings),
    });

    /** Id of the newest log line already shown. */
    this.lastLogId = 0;
  }

  async start() {
    await this.#loadSettings();
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
      this.statusView.render(status);
      this.controlsView.render(status);
      this.settingsView.setLocked(status.state === "running" || status.state === "stopping");

      const log = await this.api.getLog(this.lastLogId);
      this.logView.append(log.entries);
      this.lastLogId = log.last_id;
    } catch (error) {
      this.statusView.renderOffline(this.#messageOf(error));
    }
  }

  // ------------------------------------------------------------------
  // Actions triggered by the user
  // ------------------------------------------------------------------

  async #loadSettings() {
    try {
      this.settingsView.load(await this.api.getSettings());
    } catch (error) {
      this.settingsView.showMessage(this.#messageOf(error), "error");
    }
  }

  async #saveSettings(settings) {
    try {
      const saved = await this.api.saveSettings(settings);
      this.settingsView.load(saved);  // shows what the backend actually stored
      this.settingsView.showMessage("Settings saved.", "success");
    } catch (error) {
      this.settingsView.showMessage(this.#messageOf(error), "error");
    }
  }

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
