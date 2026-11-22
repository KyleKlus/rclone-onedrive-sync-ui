"""!
@file launcher_entry.py
@brief Installs / removes the app-menu entry for the current user.

Why this exists: the dock shows the app's icon only if a ``.desktop`` file with
a matching name exists. This module writes that file (plus the icon files) into
the user's own folders (``~/.local/share``), so no root rights are needed.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .identity import APP_COMMENT, APP_ID, APP_NAME, ICON_PNG, ICON_SVG

_ENTRY_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name={name}
Comment={comment}
Exec={command}
Icon={icon}
Terminal=false
Categories=Network;FileTransfer;
StartupWMClass={wm_class}
StartupNotify=true
"""


class LauncherEntry:
    """!
    @brief Writes the .desktop file and icons below ``data_home`` (default ~/.local/share).
    """

    def __init__(self, script_path: Path, data_home: Optional[Path] = None) -> None:
        """!
        @brief Remember the script to launch and where the entry is installed.
        @param script_path The script the menu entry starts (run_desktop.py).
        @param data_home The XDG data folder. Default: $XDG_DATA_HOME or ~/.local/share.
        """
        self._script = script_path.resolve()
        self._data_home = data_home or Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )

    @property
    def desktop_file(self) -> Path:
        """!
        @brief Get the path of the .desktop file that install() writes.
        @return The path below ``data_home``/applications.
        """
        return self._data_home / "applications" / f"{APP_ID}.desktop"

    @property
    def _icon_files(self) -> dict:
        """!
        @brief Get the icon copies that install() creates.
        @return A dict mapping each target path to the source artwork it is copied from.
        """
        icons = self._data_home / "icons" / "hicolor"
        return {
            icons / "512x512" / "apps" / f"{APP_ID}.png": ICON_PNG,
            icons / "scalable" / "apps" / f"{APP_ID}.svg": ICON_SVG,
        }

    def install(self) -> Path:
        """!
        @brief Create the menu entry and copy the icons.
        @return The path of the written .desktop file.
        """
        for target, source in self._icon_files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        self.desktop_file.parent.mkdir(parents=True, exist_ok=True)
        self.desktop_file.write_text(self._render(), encoding="utf-8")
        self._refresh_caches()
        return self.desktop_file

    def uninstall(self) -> None:
        """!
        @brief Remove everything ``install`` created.
        """
        for path in [self.desktop_file, *self._icon_files]:
            path.unlink(missing_ok=True)
        self._refresh_caches()

    def _render(self) -> str:
        """!
        @brief Fill the .desktop template.
        @return The text of the .desktop file.

        shlex.join quotes paths with spaces; the interpreter is the one running
        us, so a virtualenv keeps working when started from the menu.
        """
        command = shlex.join([sys.executable, str(self._script)])
        return _ENTRY_TEMPLATE.format(
            name=APP_NAME, comment=APP_COMMENT, command=command, icon=APP_ID, wm_class=APP_ID
        )

    def _refresh_caches(self) -> None:
        """!
        @brief Ask the desktop to notice the change.

        Optional, so missing tools and failures are ignored.
        """
        for command in (
            ["update-desktop-database", str(self.desktop_file.parent)],
            ["gtk-update-icon-cache", "-f", "-t", str(self._data_home / "icons" / "hicolor")],
        ):
            if shutil.which(command[0]):
                subprocess.run(command, check=False, capture_output=True)
