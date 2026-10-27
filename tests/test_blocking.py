from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import base64
import threading

import pytest
import requests

from resources.lib import dialogs, functions, image_server, intro_skipper, monitors, play_utils


class FakePlayer(object):
    playing = False
    stopped = []

    def isPlaying(self):
        return FakePlayer.playing

    def stop(self):
        FakePlayer.stopped.append(True)


def run_play_action(monkeypatch, playing, has_media=False):
    FakePlayer.playing = playing
    FakePlayer.stopped = []
    played = []
    monkeypatch.setattr(functions.xbmc, 'Player', FakePlayer)
    monkeypatch.setattr(functions.xbmc, 'getCondVisibility',
                        lambda condition: has_media and condition == 'Player.HasMedia')
    monkeypatch.setattr(functions, 'play_file', played.append)

    functions.play_action({'item_id': 'item'})

    assert played[0]['item_id'] == 'item'
    return FakePlayer.stopped


def test_play_action_does_not_stop_idle_player(monkeypatch):
    assert run_play_action(monkeypatch, playing=False) == []


def test_play_action_stops_current_playback(monkeypatch):
    assert run_play_action(monkeypatch, playing=True) == [True]


def test_play_action_stops_player_that_is_still_opening(monkeypatch):
    assert run_play_action(monkeypatch, playing=False, has_media=True) == [True]


def make_skip_dialog(monkeypatch, skip_action='0'):
    calls = []
    monkeypatch.setattr(intro_skipper, 'get_setting_skip_action', lambda segment_type: skip_action)
    monkeypatch.setattr(dialogs.xbmcgui.WindowXMLDialog, 'show', lambda self: calls.append('show'))
    monkeypatch.setattr(dialogs.xbmcgui.WindowXMLDialog, 'close', lambda self: calls.append('close'))
    dialog = dialogs.SkipDialog('SkipDialog.xml', '', 'default', '720p')
    dialog.media_id = 'item'
    dialog.start = 100
    dialog.end = 200
    return dialog, calls


def tick(dialog, ticks):
    service = intro_skipper.IntroSkipperService(None)
    segment = {'Type': 'Intro', 'StartTicks': 100, 'EndTicks': 200}
    return service.handle_dialog('', dialog, 'item', ticks, None, segment)


def test_skip_dialog_never_shown_is_not_closed(monkeypatch):
    dialog, calls = make_skip_dialog(monkeypatch)

    for ticks in (10, 20, 30, 250):
        tick(dialog, ticks)

    assert calls == []


def test_skip_dialog_is_shown_and_closed_once(monkeypatch):
    dialog, calls = make_skip_dialog(monkeypatch)

    for ticks in (10, 110, 120, 150, 210, 220):
        tick(dialog, ticks)

    assert calls == ['show', 'close']


def test_skip_dialog_closed_by_user_is_not_closed_again(monkeypatch):
    dialog, calls = make_skip_dialog(monkeypatch)

    tick(dialog, 110)
    dialog.onAction(FakeAction(92))
    for ticks in (120, 150, 210):
        tick(dialog, ticks)

    assert calls == ['show', 'close']


class FakeAction(object):
    def __init__(self, action_id):
        self.action_id = action_id

    def getId(self):
        return self.action_id


class FakePlayNextDialog(object):
    def __init__(self, *args):
        pass

    def set_episode_info(self, info):
        pass

    def doModal(self):
        pass

    def get_play_called(self):
        return False


def test_dismissed_play_next_dialog_does_not_refresh_container(monkeypatch):
    builtins = []
    stop_settings = {
        'promptPlayNextEpisodePercentage': '90',
        'promptPlayNextEpisodePercentage_prompt': 'true',
        'promptDeleteEpisodePercentage': '100',
        'promptDeleteMoviePercentage': '100',
    }
    monkeypatch.setattr(play_utils.settings, 'getSetting', lambda name: stop_settings.get(name, ''))
    monkeypatch.setattr(play_utils.settings, 'getAddonInfo', lambda name: '')
    monkeypatch.setattr(play_utils, 'PlayNextDialog', FakePlayNextDialog)
    monkeypatch.setattr(play_utils.xbmc, 'executebuiltin', lambda *args: builtins.append(args))

    play_utils.prompt_for_stop_actions('item', {
        'current_position': 95, 'duration': 100,
        'next_episode': {'Id': 'next'}, 'item_type': 'Episode'})

    assert builtins == []


def test_image_server_serves_while_a_collage_hangs(monkeypatch):
    release = threading.Event()

    def build_image(path):
        if path == '/hang':
            release.wait(10)
        return b'image'

    monkeypatch.setattr(image_server, 'pil_loaded', True)
    monkeypatch.setattr(image_server, 'build_image', build_image)
    server = image_server.ImageHTTPServer(('127.0.0.1', 0), image_server.HttpImageHandler)
    threading.Thread(target=server.serve_forever).start()
    url = 'http://127.0.0.1:{0}/'.format(server.server_address[1])
    try:
        threading.Thread(target=requests.get, args=(url + 'hang',)).start()
        assert requests.get(url + 'quick', timeout=3).content == b'image'
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def test_collage_images_are_fetched_with_timeout(monkeypatch):
    pytest.importorskip('PIL')
    fetched = []

    def get(url, **kwargs):
        fetched.append(kwargs)
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(image_server, 'get_image_links',
                        lambda url: [{'thumb': 'http://server:8096/Items/1/Images/Primary'}])
    monkeypatch.setattr(image_server.requests, 'get', get)

    image_server.build_image('/' + base64.b64encode(b'/Items').decode())

    assert fetched[0].get('timeout')


def test_context_monitor_polls_at_most_four_times_a_second(monkeypatch):
    monitor = monitors.ContextMonitor()
    sleeps = []

    def sleep(milliseconds):
        sleeps.append(milliseconds)
        monitor.stop_thread = True

    monkeypatch.setattr(monitors.xbmc.Monitor, 'abortRequested', lambda self: False)
    monkeypatch.setattr(monitors.xbmc, 'getCondVisibility', lambda condition: False)
    monkeypatch.setattr(monitors.xbmc, 'getInfoLabel', lambda label: '')
    monkeypatch.setattr(monitors.xbmc, 'sleep', sleep)

    monitor.run()

    assert sleeps == [250]
