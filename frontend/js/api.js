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
  /**
   * @returns {Promise<object>} Current system state, including `pairs`: every folder
   *   pair with its name, on/off switch, paths and its own sync state.
   */
  getStatus() {
    return this.#request("GET", "/api/status");
  }

  /** @returns {Promise<object>} The default setup of a pair (the backend owns them). */
  getDefaultSetup() {
    return this.#request("GET", "/api/setup/defaults");
  }

  /** @returns {Promise<object>} One folder pair with its full setup (exclusions etc.). */
  getPair(pairId) {
    return this.#request("GET", this.#pairPath(pairId));
  }

  /**
   * @param {object} pair  {name, local_path, remote, max_size, exclusions}
   * @returns {Promise<object>} The pair as created (cleaned up by the backend, with its id).
   */
  createPair(pair) {
    return this.#request("POST", "/api/pairs", pair);
  }

  /**
   * @param {string} pairId
   * @param {object} pair  {name, local_path, remote, max_size, exclusions}
   * @returns {Promise<object>} The pair as saved (cleaned up by the backend).
   */
  updatePair(pairId, pair) {
    return this.#request("PUT", this.#pairPath(pairId), pair);
  }

  /** Switch a folder pair on (it is synced) or off (it is skipped). */
  setPairEnabled(pairId, enabled) {
    return this.#request("PUT", `${this.#pairPath(pairId)}/enabled`, { enabled });
  }

  /** Remove a folder pair for good. */
  deletePair(pairId) {
    return this.#request("DELETE", this.#pairPath(pairId));
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

  #pairPath(pairId) {
    return `/api/pairs/${encodeURIComponent(pairId)}`;
  }

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
