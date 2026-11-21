from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

from unittest import mock

import pytest

from resources.lib import dir_functions, item_functions

GUI_OPTIONS = {'server': 'http://jellyfin:8096', 'name_format': None, 'name_format_type': ''}
DISPLAY_OPTIONS = {'addCounts': False, 'addResumePercent': False, 'addSubtitleAvailable': False,
                   'addUserRatings': False}


def movie(video=None, audio=None):
    return {
        'Id': 'm1', 'Name': 'Alpha', 'Type': 'Movie', 'IsFolder': False, 'ProductionYear': 2001,
        'RunTimeTicks': 6000000000, 'UserData': {'Played': False},
        'MediaStreams': [
            dict({'Type': 'Video', 'Codec': 'hevc', 'Width': 3840, 'Height': 2160,
                  'AspectRatio': '16:9', 'VideoRange': 'HDR', 'VideoRangeType': 'HDR10'}, **(video or {})),
            dict({'Type': 'Audio', 'Codec': 'dts', 'Profile': 'DTS-HD MA', 'Channels': 8,
                  'Language': 'eng'}, **(audio or {})),
        ],
    }


def series():
    return {
        'Id': 's1', 'Name': 'Show', 'Type': 'Series', 'IsFolder': True, 'ProductionYear': 2010,
        'ChildCount': 2, 'RecursiveItemCount': 12, 'UserData': {'UnplayedItemCount': 5},
    }


# the keywords of Kodi's own classes (xbmc.VideoStreamDetail, Kodi 20 and newer)
def video_stream_detail(width=0, height=0, aspect=0.0, duration=0, codec='', stereomode='', language='',
                        hdrtype=''):
    return 'video', {'width': width, 'height': height, 'aspect': aspect, 'duration': duration,
                     'codec': codec, 'stereomode': stereomode, 'language': language, 'hdrtype': hdrtype}


def audio_stream_detail(channels=-1, codec='', language=''):
    return 'audio', {'channels': channels, 'codec': codec, 'language': language}


@pytest.fixture
def gui(monkeypatch):
    """add_gui_item on a ListItem and stream details that keep what they get."""
    list_item = mock.MagicMock()
    monkeypatch.setattr(item_functions.xbmcgui, 'ListItem', lambda *args, **kwargs: list_item)
    monkeypatch.setattr(item_functions.xbmc, 'VideoStreamDetail', video_stream_detail)
    monkeypatch.setattr(item_functions.xbmc, 'AudioStreamDetail', audio_stream_detail)
    monkeypatch.setattr(item_functions.xbmc, 'SubtitleStreamDetail', lambda language='': ('sub', language))
    monkeypatch.setattr(item_functions.sys, 'argv', ['plugin://plugin.video.jellycon/', '1', ''])

    def add(item):
        details = item_functions.extract_item_info(item, GUI_OPTIONS)
        item_functions.add_gui_item(details.id, details, DISPLAY_OPTIONS, folder=details.is_folder)
        tag = list_item.getVideoInfoTag.return_value
        streams = [c.args[0] for c in tag.addVideoStream.call_args_list + tag.addAudioStream.call_args_list]
        properties = list_item.setProperties.call_args.args[0]
        return streams, properties
    return add


@pytest.mark.parametrize('range_type, hdr', [
    ('SDR', ''), ('HDR10', 'hdr10'), ('HDR10Plus', 'hdr10'), ('HLG', 'hlg'), ('DOVI', 'dolbyvision'),
    ('DOVIWithHDR10', 'dolbyvision'), (None, ''),
])
def test_the_video_stream_has_the_hdr_type_kodi_knows(gui, range_type, hdr):
    streams, _ = gui(movie(video={'VideoRangeType': range_type}))
    video = dict(streams)['video']
    assert video['hdrtype'] == hdr
    assert (video['width'], video['height'], video['codec']) == (3840, 2160, 'hevc')


@pytest.mark.parametrize('profile, codec', [
    ('DTS-HD MA', 'dtshd_ma'), ('DTS-HD HRA', 'dtshd_hra'), ('DTS', 'dts'), (None, 'dts'),
])
def test_the_audio_stream_names_dts_hd_like_the_library(gui, profile, codec):
    streams, _ = gui(movie(audio={'Profile': profile}))
    audio = dict(streams)['audio']
    assert (audio['codec'], audio['channels'], audio['language']) == (codec, 8, 'eng')


def test_a_movie_has_no_episode_counts(gui):
    _, properties = gui(movie())
    for name in ('TotalSeasons', 'TotalEpisodes', 'NumEpisodes', 'WatchedEpisodes', 'UnWatchedEpisodes'):
        assert name not in properties


def test_a_show_counts_its_episodes_like_the_library(gui):
    _, properties = gui(series())
    assert properties['TotalSeasons'] == '2'
    assert properties['TotalEpisodes'] == '12'
    assert properties['WatchedEpisodes'] == '7'
    assert properties['UnWatchedEpisodes'] == '5'


@pytest.fixture
def sorts(monkeypatch):
    added = []
    monkeypatch.setattr(dir_functions.xbmcplugin, 'addSortMethod', lambda handle, method: added.append(method))
    return added


@pytest.mark.parametrize('view_type', ['Movies', 'Episodes', 'Music Videos'])
def test_a_video_list_sorts_by_runtime(sorts, view_type):
    dir_functions.set_sort(1, view_type, False)
    assert dir_functions.xbmcplugin.SORT_METHOD_VIDEO_RUNTIME in sorts


@pytest.mark.parametrize('view_type', ['BoxSets', 'Series', 'Seasons', 'Music'])
def test_a_list_without_a_runtime_does_not_sort_by_it(sorts, view_type):
    dir_functions.set_sort(1, view_type, False)
    assert dir_functions.xbmcplugin.SORT_METHOD_VIDEO_RUNTIME not in sorts


# --- the name of a list, for the skin's header (Container.FolderName) -------------------------------

def test_a_menu_entry_names_the_list_it_opens(monkeypatch):
    from resources.lib import kodi_utils
    added = []
    monkeypatch.setattr(kodi_utils.xbmcplugin, 'addDirectoryItem',
                        lambda handle, url, listitem, isFolder: added.append(url))
    monkeypatch.setattr(kodi_utils.sys, 'argv', ['plugin://plugin.video.jellycon/', '1', ''])
    kodi_utils.add_menu_directory_item('Movies - Show All', 'plugin://plugin.video.jellycon/?url=x&mode=GET_CONTENT')
    kodi_utils.add_menu_directory_item('Movies - Genres', 'plugin://plugin.video.jellycon/?mode=GENRES')
    assert added == ['plugin://plugin.video.jellycon/?url=x&mode=GET_CONTENT&name=Movies%20-%20Show%20All',
                     'plugin://plugin.video.jellycon/?mode=GENRES']


def test_a_folder_names_the_list_it_opens(gui, monkeypatch):
    details = item_functions.extract_item_info(series(), GUI_OPTIONS)
    url, _, _ = item_functions.add_gui_item('/Shows/s1', details, DISPLAY_OPTIONS, folder=True)
    assert url.endswith('&name=Show')


def test_a_list_takes_its_name_as_category(monkeypatch):
    named = []
    monkeypatch.setattr(dir_functions.xbmcplugin, 'setPluginCategory', lambda handle, name: named.append(name))
    dir_functions.set_category(1, {'name': 'Movies - Show All'})
    dir_functions.set_category(1, {})
    assert named == ['Movies - Show All']
