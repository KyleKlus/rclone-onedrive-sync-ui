# OneDrive Sync

A small local web app that syncs a folder on this PC with OneDrive using the
`rclone` you already have installed. Python backend, plain HTML/CSS/JS frontend,
no dependencies beyond the Python standard library.

## Quick start

```
python run.py --open
```

Then in the browser (default address `http://127.0.0.1:8765`):

1. **03 / SETTINGS**: enter your local folder and your rclone remote
   (e.g. `onedrive:`), then *SAVE SETTINGS*.
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
  window's application id (`onedrive-sync`, set in `desktop/identity.py`). `--install-launcher`
  writes that file and the icons into `~/.local/share`, no root needed. Start the app from
  the app menu (or pin it) afterwards; `--uninstall-launcher` removes everything again.
- Closing the window quits the app (after asking, if a sync is running).
- Only one copy can run at a time, so two syncs can never touch the same folder.
- The window uses a random free port on `127.0.0.1`; all localhost-only protections stay active.
- `python run.py --open` (browser mode) still works unchanged.

## Modes

| Mode | rclone command | Behaviour |
|------|----------------|-----------|
| Two-way sync | `rclone bisync <local> <remote>` | Changes on both sides are merged. **OneDrive wins conflicts** (`--conflict-resolve path2`); the losing local copy is kept with a number suffix. |
| Download only | `rclone sync <remote> <local>` | This PC is made to match OneDrive. Local-only files are deleted (max 25 per run). |

Use **DRY RUN** to preview what a run would do without changing anything.

## Exclusions and max file size

Both are set in the UI and saved to `data/settings.json`. Exclusions are written
to `data/filters.txt` before every run. Two-way sync passes it as `--filters-file` (a bisync-only flag); download mode passes the same file as `--filter-from`.

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

Three independent checks (see `backend/security.py`):

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
- Page layout (wide screens): status banner, then Settings (left) and Run (right) at equal
  height, then the log, which is exactly one screen tall. Narrow screens use one column.
- Secondary buttons use `.btn--secondary` (flat outline). The primary button is the raised
  green one. To try another secondary style, only that one CSS block changes.
- **Reset to defaults** loads the defaults from the backend (`GET /api/settings/defaults`,
  defined in `config.py`) into the form. Nothing is saved until you click Save settings,
  and your local folder is kept.
- The Itim font is loaded from the jsDelivr CDN (the only external resource, allowed
  in the Content-Security-Policy in `backend/http_server.py`). Offline, the UI falls
  back to the system "cursive" font. The log always uses a monospace font.

## Project layout

```
run.py                     entry point (browser mode)
run_desktop.py             entry point (native window)
desktop/                   the native window, dock identity, single-instance lock
backend/
  config.py                fixed settings + the BISYNC_FLAGS / DOWNLOAD_FLAGS lists
  errors.py  models.py     exceptions, enums, log entry type
  settings.py              user settings + validation
  settings_store.py        load/save settings.json
  log_buffer.py            thread-safe in-memory log
  rclone_command.py        builds rclone command lines (no execution)
  rclone_runner.py         runs rclone, streams output, can cancel
  sync_manager.py          state machine: idle -> running -> done/failed/stopped
  security.py              localhost guard
  api.py                   /api/* endpoints (no HTTP details)
  http_server.py           HTTP plumbing + static files
  app.py                   wires all of the above together
frontend/
  index.html               structure only
  css/base.css             design tokens (--hue ...), reset, page layout
  css/components.css       one section per component
  img/noise.svg            background texture
  img/icons/               app icons (apple-touch, 192, 512); favicon.svg/.ico and site.webmanifest sit next to index.html
  js/api.js                the only file that talks to the backend
  js/status_view.js  controls_view.js  settings_view.js  log_view.js
  js/main.js               wires views to the API, polling loop
tests/                     end-to-end tests with a fake rclone
data/                      created at runtime (settings, filter file)
```

## Where to change things

| I want to... | Edit |
|--------------|------|
| change rclone flags | `backend/config.py` |
| change how commands are assembled | `backend/rclone_command.py` |
| add a setting | `settings.py` (+ the field in `index.html` and `settings_view.js`) |
| restyle the UI | `frontend/css/` |
| add an API endpoint | `api.py` (+ a method in `frontend/js/api.js`) |

## Tests

```
python -m unittest discover -s tests -v
```

## License

MIT, see [LICENSE](LICENSE).
