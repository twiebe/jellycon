# Gnu General Public License - see LICENSE.TXT
"""
The width of the artwork JellyCon asks the server for, per kind of image: the
server scales it down before Kodi gets it. Kodi itself keeps an image up to
imageres (720 lines) or fanartres (1080 lines) and draws a much larger one on a
small card pixelated, without mipmaps on many devices.

Each kind has a setting: Auto (0) fits the place a skin gives it at the
resolution of the GUI, unlimited (-1) asks for the original, else the width in
px. Music, photos, channels and folders keep their size.
"""
from __future__ import division, absolute_import, print_function, unicode_literals

ART_KINDS = ("poster", "thumb", "fanart", "logo")
ART_SETTINGS = {
    "poster": "artSizePoster",
    "thumb": "artSizeThumb",
    "fanart": "artSizeFanart",
    "logo": "artSizeLogo",
}
# Auto at a GUI of 1080 lines: poster cards (up to 360 px wide in a library
# view, some room for larger ones), episode and landscape cards (two times
# their width), the full screen, a logo box. It follows the GUI height.
ART_AUTO_1080 = {"poster": 400, "thumb": 640, "fanart": 1920, "logo": 800}

# Jellyfin item types whose artwork is sized
_STILL_TYPES = ("Episode", "MusicVideo", "Video", "Trailer")
_SIZED_TYPES = _STILL_TYPES + ("Movie", "Series", "Season", "BoxSet")
_IMAGE_KINDS = {
    "Backdrop": "fanart",
    "Thumb": "thumb",
    "BoxRear": "poster",
    "Logo": "logo",
    "Art": "logo",
    "Banner": "logo",
    "Disc": "logo",
}

_queries = None


def _setting(key):
    import xbmcaddon
    return xbmcaddon.Addon().getSetting(key)


def gui_size():
    import xbmcgui
    return xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()


def art_kind(art_type, item_type, parent=False):
    """
    The size setting of the image ART_TYPE (Primary, Backdrop, ...) of an item
    of ITEM_TYPE, or of its series with PARENT: poster, thumb, fanart, logo, or
    None for one that keeps its size.
    """
    if item_type not in _SIZED_TYPES:
        return None
    if art_type == "Primary":
        if item_type in _STILL_TYPES and not parent:
            return "thumb"
        return "poster"
    return _IMAGE_KINDS.get(art_type)


def _width(kind, screen_width, height):
    try:
        value = int(_setting(ART_SETTINGS[kind]) or 0)
    except ValueError:
        value = 0
    if value < 0:
        return None
    if value == 0:
        auto = int(round(ART_AUTO_1080[kind] * height / 1080.0))
        # a backdrop fills the screen: no wider than it on a 16:10 or 4:3 screen
        return min(auto, screen_width) if kind == "fanart" else auto
    return value


def _size_queries():
    global _queries
    if _queries is None:
        screen_width, height = gui_size()
        height = height or 1080
        screen_width = screen_width or height * 16 // 9
        queries = {None: ""}
        for kind in ART_KINDS:
            width = _width(kind, screen_width, height)
            queries[kind] = "&MaxWidth=%d" % width if width else ""
        _queries = queries
    return _queries


def size_query(kind):
    """The size parameters of an image URL for artwork of KIND (art_kind)."""
    return _size_queries()[kind]


def art_key():
    """What the artwork URLs are built with: changes with any size setting and
    with the GUI resolution Auto follows."""
    queries = _size_queries()
    return "|".join(queries[kind] for kind in (None,) + ART_KINDS)


def reset():
    """Read the settings and the GUI size anew, e.g. after a settings change."""
    global _queries
    _queries = None
