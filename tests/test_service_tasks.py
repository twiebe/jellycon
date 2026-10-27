from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import threading
import time

from resources.lib import service_tasks


class FakeHomeWindow(object):
    properties = {}

    def get_property(self, key):
        return FakeHomeWindow.properties.get(key, '')

    def set_property(self, key, value):
        FakeHomeWindow.properties[key] = value


class FakePlayer(object):
    playing = False

    def isPlaying(self):
        return FakePlayer.playing


def make_tasks(monkeypatch, playing=False):
    FakeHomeWindow.properties = {'exit': 'False', 'user_name': 'user'}
    FakePlayer.playing = playing
    calls = []
    monkeypatch.setattr(service_tasks, 'HomeWindow', FakeHomeWindow)
    monkeypatch.setattr(service_tasks.xbmc, 'Player', FakePlayer)
    monkeypatch.setattr(service_tasks.xbmc, 'getCondVisibility', lambda condition: False)
    monkeypatch.setattr(service_tasks.xbmcaddon.Addon, 'getSetting', lambda self, name: '0')
    for name in ('send_progress', 'set_random_movies', 'set_random_tvshows',
                 'set_random_all', 'set_library_window_values', 'set_background_image'):
        monkeypatch.setattr(service_tasks, name, lambda *args, name=name: calls.append(name))
    tasks = service_tasks.ServiceTasks(None, None, False)
    return tasks, calls


def test_progress_is_sent_every_10_seconds_while_playing(monkeypatch):
    tasks, calls = make_tasks(monkeypatch, playing=True)

    tasks.run_once()
    assert calls == []

    tasks.last_progress_update = time.time() - 11
    tasks.run_once()
    tasks.run_once()
    assert calls == ['send_progress']


def test_widgets_refresh_15_seconds_after_playback(monkeypatch):
    tasks, calls = make_tasks(monkeypatch, playing=True)
    tasks.random_movie_list_interval = 600

    tasks.run_once()
    FakePlayer.playing = False
    tasks.run_once()
    assert 'set_random_movies' not in calls

    tasks.last_random_movie_update -= 16
    tasks.run_once()
    assert 'set_random_movies' in calls


def run_until_stopped(tasks):
    thread_done = threading.Event()

    def run():
        tasks.run()
        thread_done.set()

    threading.Thread(target=run).start()
    return thread_done


def test_tasks_stop_on_abort(monkeypatch):
    tasks, calls = make_tasks(monkeypatch)
    aborted = threading.Event()
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'abortRequested', lambda self: aborted.is_set())
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'waitForAbort',
                        lambda self, timeout=0: aborted.wait(timeout))

    done = run_until_stopped(tasks)
    assert not done.wait(0.2)
    aborted.set()
    assert done.wait(2)


def test_tasks_stop_when_asked(monkeypatch):
    tasks, calls = make_tasks(monkeypatch)
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'abortRequested', lambda self: False)
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'waitForAbort',
                        lambda self, timeout=0: time.sleep(0.01) or False)

    done = run_until_stopped(tasks)
    assert not done.wait(0.2)
    tasks.stop()
    assert done.wait(2)


def test_tasks_stop_when_kodi_quits(monkeypatch):
    tasks, calls = make_tasks(monkeypatch)
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'abortRequested', lambda self: False)
    monkeypatch.setattr(service_tasks.xbmc.Monitor, 'waitForAbort',
                        lambda self, timeout=0: time.sleep(0.01) or False)

    done = run_until_stopped(tasks)
    FakeHomeWindow.properties['exit'] = 'True'
    assert done.wait(2)
