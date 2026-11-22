from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import threading

import pytest

from resources.lib import info_monitor


@pytest.fixture(autouse=True)
def kodi_runs(monkeypatch):
    # Kodistubs answer True
    monkeypatch.setattr(info_monitor._SettingsMonitor, 'abortRequested', lambda self: False)
    monkeypatch.setattr(info_monitor._SettingsMonitor, 'waitForAbort', lambda self, timeout=None: False)


def opened(monkeypatch, skip_property, skin):
    builtins = []
    monkeypatch.setattr(info_monitor, 'skipped_by_skin', lambda: skip_property == skin)
    monkeypatch.setattr(info_monitor.xbmc, 'getInfoLabel', lambda label: {
        'ListItem.Property(id)': 'item',
        'ListItem.Property(ItemType)': 'Movie'}.get(label, ''))
    monkeypatch.setattr(info_monitor.xbmc, 'executebuiltin', builtins.append)
    info_monitor.InfoDialogMonitor()._on_info_opened()
    return builtins


def test_info_loads_the_cast(monkeypatch):
    assert opened(monkeypatch, '', 'skin.estuary') == [
        'RunPlugin(plugin://plugin.video.jellycon/?mode=SHOW_INFO&item_id=item)']


def test_a_skin_switches_the_loading_off_for_itself(monkeypatch):
    assert opened(monkeypatch, 'skin.nightcity', 'skin.nightcity') == []


def test_the_switch_of_another_skin_does_not_count(monkeypatch):
    assert opened(monkeypatch, 'skin.nightcity', 'skin.estuary') != []


def test_switched_off_it_watches_nothing_until_it_stops(monkeypatch):
    polled = []
    monkeypatch.setattr(info_monitor, 'load_enabled', lambda: False)
    monkeypatch.setattr(info_monitor.xbmc, 'getCondVisibility', polled.append)
    monitor = info_monitor.InfoDialogMonitor()
    thread = threading.Thread(target=monitor.run)
    thread.start()
    thread.join(0.3)
    assert thread.is_alive()
    monitor.stop_monitor()
    thread.join(1)
    assert not thread.is_alive()
    assert polled == []


def test_switched_on_again_it_watches(monkeypatch):
    enabled = [False]
    polled = threading.Event()
    monkeypatch.setattr(info_monitor, 'load_enabled', lambda: enabled[0])
    monkeypatch.setattr(info_monitor.xbmc, 'getCondVisibility', lambda condition: polled.set() or False)
    monitor = info_monitor.InfoDialogMonitor()
    thread = threading.Thread(target=monitor.run)
    thread.start()
    enabled[0] = True
    monitor._monitor.onSettingsChanged()
    assert polled.wait(1)
    monitor.stop_monitor()
    thread.join(1)
