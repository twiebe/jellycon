from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import pytest

from resources.lib import art_sizes, datamanager, utils

SERVER = "http://jf:8096"


@pytest.fixture
def sizes(monkeypatch):
    values = {key: "0" for key in art_sizes.ART_SETTINGS.values()}
    screen = [1920, 1080]
    reads = []

    def setting(key):
        reads.append(key)
        return values[key]

    monkeypatch.setattr(art_sizes, "_setting", setting)
    monkeypatch.setattr(art_sizes, "gui_size", lambda: tuple(screen))
    art_sizes.reset()
    yield values, screen, reads
    art_sizes.reset()


def test_auto_fits_the_place_of_each_kind_at_1080(sizes):
    assert art_sizes.size_query("poster") == "&MaxWidth=400"
    assert art_sizes.size_query("thumb") == "&MaxWidth=640"
    assert art_sizes.size_query("fanart") == "&MaxWidth=1920"
    assert art_sizes.size_query("logo") == "&MaxWidth=800"
    assert art_sizes.size_query(None) == ""


def test_auto_follows_the_gui_and_keeps_fanart_to_the_screen(sizes):
    _, screen, _ = sizes
    screen[:] = [3024, 1964]  # 14" MacBook Pro, 16:10
    assert art_sizes.size_query("poster") == "&MaxWidth=727"
    assert art_sizes.size_query("thumb") == "&MaxWidth=1164"
    assert art_sizes.size_query("fanart") == "&MaxWidth=3024"
    screen[:] = [0, 0]
    art_sizes.reset()
    assert art_sizes.size_query("fanart") == "&MaxWidth=1920"


def test_a_width_or_unlimited_per_kind(sizes):
    values, _, _ = sizes
    values.update({"artSizeThumb": "960", "artSizeFanart": "-1"})
    assert art_sizes.size_query("thumb") == "&MaxWidth=960"
    assert art_sizes.size_query("fanart") == ""


def test_settings_are_read_once(sizes):
    _, _, reads = sizes
    for _ in range(50):
        for kind in art_sizes.ART_KINDS + (None,):
            art_sizes.size_query(kind)
        art_sizes.art_key()
    assert len(reads) == 4


@pytest.mark.parametrize("art_type, item_type, parent, kind", [
    ("Primary", "Movie", False, "poster"),
    ("Primary", "Series", False, "poster"),
    ("Primary", "Season", False, "poster"),
    ("Primary", "Season", True, "poster"),
    ("Primary", "Episode", False, "thumb"),
    ("Primary", "Episode", True, "poster"),
    ("Primary", "MusicVideo", False, "thumb"),
    ("Primary", "BoxSet", False, "poster"),
    ("Backdrop", "Episode", True, "fanart"),
    ("Thumb", "Series", False, "thumb"),
    ("Logo", "Episode", True, "logo"),
    ("Banner", "Season", False, "logo"),
    ("Art", "Movie", False, "logo"),
    ("Disc", "Movie", False, "logo"),
    ("Primary", "MusicAlbum", False, None),
    ("Primary", "Audio", False, None),
    ("Backdrop", "MusicArtist", False, None),
    ("Primary", "Photo", False, None),
    ("Primary", "TvChannel", False, None),
    ("Primary", "CollectionFolder", False, None),
    ("Primary", "Genre", False, None),
])
def test_art_kind(art_type, item_type, parent, kind):
    assert art_sizes.art_kind(art_type, item_type, parent) == kind


EPISODE = {
    "Id": "e", "Type": "Episode", "SeriesId": "s",
    "ImageTags": {"Primary": "p"},
    "SeriesPrimaryImageTag": "sp",
    "ParentLogoItemId": "s", "ParentLogoImageTag": "l",
    "ParentBackdropItemId": "s", "ParentBackdropImageTags": ["b"],
}


def test_get_art_url_asks_for_the_size_of_the_kind(sizes):
    url = utils.get_art_url(EPISODE, "Primary", server=SERVER)
    assert url == SERVER + "/Items/e/Images/Primary/0?Format=original&Tag=p&MaxWidth=640"
    url = utils.get_art_url(EPISODE, "Primary", parent=True, server=SERVER)
    assert url == SERVER + "/Items/s/Images/Primary/0?Format=original&Tag=sp&MaxWidth=400"
    url = utils.get_art_url(EPISODE, "Logo", parent=True, server=SERVER)
    assert url == SERVER + "/Items/s/Images/Logo/0?Format=original&Tag=l&MaxWidth=800"
    url = utils.get_art_url(EPISODE, "Backdrop", server=SERVER)
    assert url == SERVER + "/Items/s/Images/Backdrop/0?Format=original&Tag=b&MaxWidth=1920"


def test_get_art_url_keeps_music_and_missing_images(sizes):
    album = {"Id": "a", "Type": "MusicAlbum", "ImageTags": {"Primary": "c"}}
    assert utils.get_art_url(album, "Primary", server=SERVER) == \
        SERVER + "/Items/a/Images/Primary/0?Format=original&Tag=c"
    assert utils.get_art_url(EPISODE, "Thumb", server=SERVER) == ""


def test_the_list_cache_changes_with_the_sizes(sizes, monkeypatch, tmp_path):
    # the cached items carry their artwork URLs: other sizes, other cache file
    values, _, _ = sizes
    files = []

    class Window(object):
        def set_property(self, name, value):
            files.append(name)

        def get_property(self, name):
            return ""

        def clear_property(self, name):
            pass

    class Api(object):
        server = SERVER

        def get(self, url):
            return {"Items": []}

    monkeypatch.setattr(datamanager, "HomeWindow", Window)
    monkeypatch.setattr(datamanager.DataManager, "addon_dir", str(tmp_path))
    manager = datamanager.DataManager.__new__(datamanager.DataManager)
    manager.user_details = {"user_id": "u"}
    manager.api = Api()

    first = manager.get_items("/Users/u/Items", {}, use_cache=True)[0]
    assert manager.get_items("/Users/u/Items", {}, use_cache=True)[0] == first
    values["artSizePoster"] = "960"
    art_sizes.reset()
    assert manager.get_items("/Users/u/Items", {}, use_cache=True)[0] != first
