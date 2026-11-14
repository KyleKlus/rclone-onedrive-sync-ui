/**
 * api.js
 * The ONLY place in the frontend that talks to the backend.
 * If an endpoint changes, this is the single file to update.
 */

/** An error returned by (or while reaching) the backend. */
export class ApiError extends Error {
  /**
   * @param {string} message  Human-readable text, safe to show to the user.
   * @param {number} status   HTTP status, or 0 if the backend was unreachable.
   */
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class ApiClient {
  /** @returns {Promise<object>} Current system state. */
  getStatus() {
    return this.#request("GET", "/api/status");
  }

  /** @returns {Promise<object>} The saved user settings. */
  getSettings() {
    return this.#request("GET", "/api/settings");
  }

  /** @returns {Promise<object>} The default settings (the backend owns them). */
  getDefaultSettings() {
    return this.#request("GET", "/api/settings/defaults");
  }

  /**
   * @param {object} settings  {local_path, remote, max_size, exclusions}
   * @returns {Promise<object>} The settings as saved (cleaned up by the backend).
   */
  saveSettings(settings) {
    return this.#request("PUT", "/api/settings", settings);
  }

  /**
   * @param {{mode: string, resync?: boolean, dryRun?: boolean}} options
   * @returns {Promise<object>} The new system state.
   */
  startSync({ mode, resync = false, dryRun = false }) {
    return this.#request("POST", "/api/sync", { mode, resync, dry_run: dryRun });
  }

  /** @returns {Promise<object>} The new system state. */
  stopSync() {
    return this.#request("POST", "/api/stop");
  }

  /**
   * @param {number} afterId  Id of the last log line the UI already has (0 = from the start).
   * @returns {Promise<{entries: object[], last_id: number}>}
   */
  getLog(afterId) {
    return this.#request("GET", `/api/log?after=${encodeURIComponent(afterId)}`);
  }

  // ------------------------------------------------------------------

  async #request(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(path, options);
    } catch {
      throw new ApiError("Cannot reach the backend. Is run.py still running?", 0);
    }

    let data = {};
    try {
      data = await response.json();
    } catch {
      // Non-JSON answer: fall through to the generic message below.
    }

    if (!response.ok) {
      throw new ApiError(data.error || `The backend answered with HTTP ${response.status}.`, response.status);
    }
    return data;
  }
}
