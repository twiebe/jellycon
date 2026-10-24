from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import pytest

from resources.lib import functions


def test_show_menu_survives_failed_item_request(monkeypatch):
    notified = []
    monkeypatch.setattr(functions.api, 'get', lambda path: {})
    monkeypatch.setattr(functions.api, 'notify_failed', notified.append)

    functions.show_menu({'item_id': 'gone'})

    assert notified == [30692]


def test_mark_unwatched_reports_failure(monkeypatch):
    notified = []
    refreshed = []
    monkeypatch.setattr(functions.api, 'delete', lambda url: False)
    monkeypatch.setattr(functions.api, 'notify_failed', notified.append)
    monkeypatch.setattr(functions, 'check_for_new_content', lambda: refreshed.append(True))

    functions.mark_item_unwatched('item')

    assert notified == [30271]
    assert refreshed == []


def test_plugin_crash_after_server_error_is_reported(monkeypatch):
    notified = []
    ended = []
    monkeypatch.setattr(functions.api, 'last_error', 'Server not reachable')
    monkeypatch.setattr(functions.api, 'notify_failed', notified.append)
    monkeypatch.setattr(functions.xbmcplugin, 'endOfDirectory',
                        lambda handle, succeeded=True: ended.append((handle, succeeded)))
    monkeypatch.setattr(functions.sys, 'argv', ['plugin://plugin.video.jellycon/', '7', '?mode=x'])

    try:
        None + 'x'
    except TypeError:
        functions.handle_entry_point_error()

    assert notified == [30697]
    assert ended == [(7, False)]


def test_plugin_crash_without_server_error_is_raised(monkeypatch):
    monkeypatch.setattr(functions.api, 'last_error', None)
    with pytest.raises(TypeError):
        try:
            None + 'x'
        except TypeError:
            functions.handle_entry_point_error()
