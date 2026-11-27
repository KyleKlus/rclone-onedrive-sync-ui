"""!
@file status_icons.py
@brief The tray icon in the colour of the current sync state.

green  = ready for a sync, or the last one went well
yellow = syncing (also while stopping)
red    = the last sync failed

All three are made from the app icon (dark symbol on a green tile) by swapping
the colour of the tile, so there is only one piece of artwork to maintain.
"""

from pathlib import Path

from backend.models import SyncState

ICON_SIZE = (64, 64)

YELLOW = (255, 214, 51)
RED = (255, 107, 96)

# States that are not listed keep the green of the original artwork.
_STATE_COLOURS = {
    SyncState.RUNNING: YELLOW,
    SyncState.STOPPING: YELLOW,
    SyncState.FAILED: RED,
}

# The two main colours of the artwork: the symbol and the tile behind it.
_SYMBOL_COLOUR = (25, 23, 20)
_SYMBOL_BRIGHTNESS = 23
_TILE_BRIGHTNESS = 190


class StatusIcons:
    """!
    @brief Provides one picture per colour, each created once.
    """

    def __init__(self, icon_path: Path) -> None:
        """!
        @brief Load the app icon.
        @param icon_path The PNG with the green app icon.
        @throws ImportError If Pillow is not installed.
        @throws OSError If the file cannot be read.
        """
        from PIL import Image

        self._image_module = Image
        original = Image.open(icon_path).convert("RGBA")
        original.thumbnail(ICON_SIZE)
        self._original = original
        self._cache: dict = {}

    def for_state(self, state: SyncState):
        """!
        @brief Get the picture for a sync state.
        @param state The overall state.
        @return A PIL image; the same object for states that share a colour.
        """
        colour = _STATE_COLOURS.get(state)
        if colour is None:
            return self._original
        if colour not in self._cache:
            self._cache[colour] = self._recoloured(colour)
        return self._cache[colour]

    def _recoloured(self, tile_colour: tuple):
        """!
        @brief Copy the icon with another tile colour.
        @param tile_colour The new colour as (red, green, blue).
        @return The new PIL image.

        Every pixel is placed between the symbol colour and the new tile colour
        according to its brightness. This keeps the darker border and the smooth
        edges. Transparency is taken over unchanged.
        """
        brightness = self._original.convert("L")
        channels = [
            brightness.point(_ramp(symbol, tile))
            for symbol, tile in zip(_SYMBOL_COLOUR, tile_colour)
        ]
        channels.append(self._original.getchannel("A"))
        return self._image_module.merge("RGBA", channels)


def _ramp(symbol: int, tile: int) -> list:
    """!
    @brief Build the lookup table of one colour channel.
    @param symbol The channel value of the symbol colour.
    @param tile The channel value of the new tile colour.
    @return 256 channel values, one per brightness.
    """
    span = _TILE_BRIGHTNESS - _SYMBOL_BRIGHTNESS
    return [
        max(0, min(255, round(symbol + (tile - symbol) * (value - _SYMBOL_BRIGHTNESS) / span)))
        for value in range(256)
    ]
