from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

from resources.lib import functions


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
