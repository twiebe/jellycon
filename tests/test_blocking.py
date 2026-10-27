from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

from resources.lib import dialogs, functions, intro_skipper


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
