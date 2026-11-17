# Rclone Sync

A small local web app that syncs folders on this PC with your cloud storage (OneDrive,
Google Drive, iCloud, ... any remote rclone supports) using the `rclone` you already have installed. Python backend, plain HTML/CSS/JS frontend,
no dependencies beyond the Python standard library.

## Quick start

```
python run.py --open
```

Then in the browser (default address `http://127.0.0.1:8765`):

1. **FOLDER PAIRS**: press *ADD FOLDER PAIR*, name it, enter your local folder and
   pick one of your rclone remotes from the dropdown (optionally add a folder on it), then
   *CREATE FOLDER PAIR*. The dropdown lists what `rclone config` knows; set up a remote there first.
2. **Two-way sync, first time only**: open *FIRST TIME USING TWO-WAY SYNC?* and
   press *RUN FIRST-TIME SETUP*. This places a `RCLONE_TEST` file on both sides
   (needed by `--check-access`) and builds the initial baseline.
3. From then on, press *START SYNC*.

Requires Python 3.9+ and rclone 1.66+ (for `--compare` and `--conflict-resolve`).

## Desktop app (one window, with dock icon)

Instead of the browser you can run everything as a single native window:

```
python run_desktop.py                      # open the app
python run_desktop.py --install-launcher   # once: adds it to the app menu / dock
```

Needs pywebview and the WebKitGTK system library (install commands are printed
if they are missing; see also `requirements-desktop.txt`). Notes:

- **Dock icon:** the dock finds the icon through a `.desktop` file whose name matches the
  window's application id (`onedrive-sync`, set in `desktop/identity.py`; the id is kept so that an already installed launcher still works). `--install-launcher`
  writes that file and the icons into `~/.local/share`, no root needed. Start the app from
  the app menu (or pin it) afterwards; `--uninstall-launcher` removes everything again.
- Closing the window quits the app (after asking, if a sync is running).
- Only one copy can run at a time, so two syncs can never touch the same folder.
- The window uses a random free port on `127.0.0.1`; all localhost-only protections stay active.
- `python run.py --open` (browser mode) still works unchanged.

## Modes

| Mode | rclone command | Behaviour |
|------|----------------|-----------|
| Two-way sync | `rclone bisync <local> <remote>` | Changes on both sides are merged. **The remote wins conflicts** (`--conflict-resolve path2`); the losing local copy is kept with a number suffix. |
| Download only | `rclone sync <remote> <local>` | This PC is made to match the remote. Local-only files are deleted (max 25 per run). |

The mode applies to all folder pairs. Use **DRY RUN** to preview what a run would do
without changing anything.

## Folder pairs

You can sync several local / remote folder pairs. They are managed in one card that shows
two views in the same spot:

- **Overview**: one row per pair: its name and folders, its own state
  (Ready / Syncing / Done / Failed / Stopped / Inactive), the on/off switch and a pen button to edit it.
  *Add folder pair* is always there. When there are more pairs than fit, the list scrolls
  inside the card; the card itself never grows.
- **Setup of one pair**: opens in place of the overview. The top row has the *Back* button
  and the pair's name (click it to rename). Below it are the folder, remote, max size and
  exclusions. Going back with unsaved changes asks for a second click. *Delete pair* (next to *Save*) asks in a popup first.

How a run treats the pairs:

- **Switched-off pairs are skipped.** Switch a pair off in the overview to leave it out
  temporarily without deleting it.
- **Pairs sync in parallel**, each in its own rclone process.
- **Nothing is synced twice.** How two pairs relate is decided in `backend/pair_relations.py`:
  - *Separate* folders: nothing to do.
  - *Nested* (a pair's local **and** remote folder lie inside another pair's, at the same
    position, e.g. `~/Docs/Photos` <-> `cloud:Docs/Photos` inside `~/Docs` <-> `cloud:Docs`):
    the outer pair automatically **skips** that folder (an exclusion like `/Photos/` is added to its
    filter file), the inner pair syncs it. The overview says so on the outer pair.
    A remote without a folder (`cloud:`) is the whole drive and contains every folder.
  - Anything else that touches (identical pairs, the same remote folder from two local folders,
    the same local folder with two remote folders, an inner folder at a different position on each
    side) **cannot be saved**: the message names the pair it clashes with. A run also refuses to
    start if such pairs exist anyway (e.g. from a hand-edited `pairs.json`).
- The skipped folder stays out of the outer pair even while the inner pair is switched off, so the
  outer pair's filters never change by switching. They do change when you add, remove or move a nested
  pair, and then rclone may ask for a first-time setup (resync) for the outer pair once.
- One failing pair does not stop the others; the overall state is *Failed* if any pair failed.
- **Stop** stops every pair. Pairs cannot be changed while a sync is running.
- Every log line is tagged with its pair's name, because the lines of parallel pairs mix.
- *First-time setup* runs for every active pair; switch the others off first if needed.

## Remotes

A folder pair's **Remote** field is one field with two parts: a dropdown at its start and a folder
box after it, e.g. `onedrive:` + `Documents/Work` = `onedrive:Documents/Work`.

- The dropdown lists the remotes rclone has configured (`rclone listremotes --long`, see
  `backend/command/remotes.py`), each with its type (`onedrive`, `drive`, `iclouddrive`, ...).
  The list is read every time the form opens, so a remote you just created with `rclone config` shows up
  without restarting the app.
- With exactly one remote it is chosen for you; with several you pick one. Nothing is preselected otherwise.
- A pair whose remote is not in rclone's list (renamed or deleted in `rclone config`) keeps it, marked
  *not in rclone config*, so opening the pair never changes it silently.
- If rclone has no remotes, or cannot be asked, the dropdown says *No remotes* and the hint under the
  field explains why. The API accepts any well-formed remote name regardless.
- **Which cloud is used is the only difference between pairs.** The rclone flags in `config.py`
  (`BISYNC_FLAGS`, `DOWNLOAD_FLAGS`) are the same for every remote; check that your provider supports them
  (e.g. `--metadata`, `--compare size,modtime,checksum`) before relying on a new one.

## Exclusions and max file size

Both are set per folder pair in the UI. All pairs are saved to `data/pairs.json`
(an older single `data/setup.json` is converted into a pair called "Folder pair 1" on first
start; the old file is left untouched). Each pair's exclusions are written to
`data/filters/<pair id>.txt` before every run. Two-way sync passes it as `--filters-file`
(a bisync-only flag); download mode passes the same file as `--filter-from`.

| Pattern | Meaning |
|---------|---------|
| `Folder/` | a folder with that name, anywhere |
| `/Folder/` | only the top-level folder |
| `*.iso` | files matching a pattern |
| `Docs/secret.txt` | one specific file |

> `bisync` remembers its filters. If you change the exclusions, rclone may ask
> for a first-time setup (resync) on the next two-way run. The UI tells you
> when that happens.

## Security: localhost only

Three independent checks (see `backend/server/security.py`):

1. The server only binds to `127.0.0.1`, and each request's client address must be loopback.
2. The `Host` header must be `localhost` / `127.0.0.1` (blocks DNS-rebinding).
3. An `Origin` header, if present, must be this exact server (blocks other websites and other local apps from sending commands).

## Design

The UI follows the look of kyleklus.de/printable-calendar-generator: Itim font,
soft gradient background with a noise texture, rounded cards and tactile 3D
buttons that sink when hovered and pressed.

- All colours derive from one number, `--hue`, in `frontend/css/base.css`
  (132 = green; try 210 for blue). Any element can override it, e.g. `.btn--danger`.
- Buttons, inputs and switches share one rule in `components.css` (cards are flat on purpose).
  States only change `--lift`, so adding a new 3D element means adding its selector there.
- Page layout (wide screens): status banner, then Folder pairs (left) and Run (right) at equal
  height, then the log, which is exactly one screen tall. Narrow screens use one column.
- Secondary buttons use `.btn--plain`: the same raised 3D button as the primary one, but in a
  pale colour. The primary button is the green one. The style is one line in `components.css`.
- **Reset to defaults** loads the defaults from the backend (`GET /api/setup/defaults`,
  defined in `config.py`) into the form. Nothing is saved until you click Save, and the
  pair's name, local folder and remote are kept.
- The Itim font is loaded from the jsDelivr CDN (the only external resource, allowed
  in the Content-Security-Policy in `backend/server/http_server.py`). Offline, the UI falls
  back to the system "cursive" font. The log always uses a monospace font.

## Project layout

```
run.py                     entry point (browser mode)
run_desktop.py             entry point (native window)
desktop/                   the native window, dock identity, single-instance lock
backend/
  config.py                fixed app settings + the BISYNC_FLAGS / DOWNLOAD_FLAGS lists
  errors.py  models.py     exceptions, enums, log entry type
  setup.py                 the setup of ONE folder pair: validation
  pairs.py                 folder pairs (name, on/off, setup) + the list saved as pairs.json
  pair_relations.py        how two pairs relate: separate, nested (outer skips inner) or clashing
  pair_job.py              one pair's sync in its own thread, with its own state
  sync_manager.py          runs one job per active pair; overall state idle -> running -> done/failed/stopped
  app.py                   wires all of the above together
  command/
    rclone.py              builds rclone command lines, runs rclone, can cancel
    remotes.py             asks rclone which remotes (clouds) are configured
    log_buffer.py          thread-safe in-memory log
  server/
    security.py            localhost guard
    api.py                 /api/* endpoints (no HTTP details)
    http_server.py         HTTP plumbing + static files
frontend/
  index.html               structure only
  css/base.css             design tokens (--hue ...), reset, page layout
  css/components.css       one section per component
  img/noise.svg            background texture
  img/icons/               app icons (apple-touch, 192, 512); favicon.svg/.ico and site.webmanifest sit next to index.html
  js/api.js                the only file that talks to the backend
  js/status_view.js  controls_view.js  log_view.js
  js/remote_field.js       the remote field: dropdown of rclone's remotes + folder box (like size_field.js, mirrored)
  js/pairs_view.js         overview card: the list of pairs, switches, Add
  js/setup_view.js         setup of one pair (back button, name, folders, exclusions)
  js/setup_panel.js        switches the card between overview and setup
  js/two_step_button.js    "click again to confirm" for discarding unsaved changes
  js/confirm_dialog.js     the "are you sure?" popup (used before deleting a pair)
  js/main.js               wires views to the API, polling loop
tests/                     end-to-end tests with a fake rclone
data/                      created at runtime (pairs.json, filters/)
```

## Tests

```
python -m unittest discover -s tests -v
```

## License

MIT, see [LICENSE](LICENSE).
