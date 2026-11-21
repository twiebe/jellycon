from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import json
import os
import pickle
import threading
import time

from resources.lib import datamanager, play_utils


class Item(object):
    def __init__(self, name, play_count=0):
        self.name = name
        self.play_count = play_count
        self.favorite = False
        self.resume_time = 0
        self.recursive_unplayed_items_count = 0
        self.etag = 'etag'


class FakeHomeWindow(object):
    properties = {}

    def get_property(self, key):
        return FakeHomeWindow.properties.get(key, '')

    def set_property(self, key, value):
        FakeHomeWindow.properties[key] = value


def make_cache_item(tmp_path, items, last_action, age):
    cache_item = datamanager.CacheItem()
    cache_item.item_list = items
    cache_item.item_list_hash = datamanager.get_data_hash(items)
    cache_item.file_path = str(tmp_path / 'cache_abc.pickle')
    cache_item.items_url = '/Users/user/Items?ParentId=movies'
    cache_item.last_action = last_action
    cache_item.date_saved = time.time() - age
    cache_item.date_last_used = time.time() - age
    cache_item.total_records = len(items)
    return cache_item


def load(path):
    with open(path, 'rb') as handle:
        return pickle.load(handle)


def test_cached_listing_leaves_the_server_check_to_the_service(tmp_path, monkeypatch):
    # A thread of the plugin keeps the invocation alive after the listing,
    # stopping it then can crash Kodi
    notified = []
    monkeypatch.setattr(datamanager, 'send_event_notification',
                        lambda method, data: notified.append((method, data)))
    monkeypatch.setattr(datamanager.api, 'get', lambda url: 1 / 0)
    cache_item = make_cache_item(tmp_path, [Item('a')], 'cached_data', 60)
    threads = threading.active_count()

    datamanager.CacheCheck(cache_item, {'server': 'http://server'}).run()

    assert threading.active_count() == threads
    assert notified == [('jellycon_cache_check', {
        'cache_file': 'cache_abc.pickle', 'gui_options': {'server': 'http://server'}})]


def test_fresh_listing_is_saved_with_its_hash(tmp_path, monkeypatch):
    notified = []
    monkeypatch.setattr(datamanager, 'send_event_notification',
                        lambda method, data: notified.append(method))
    cache_item = make_cache_item(tmp_path, [Item('a'), Item('b')], 'fresh_data', 0)
    cache_item.item_list_hash = None

    datamanager.CacheCheck(cache_item, {}).run()

    saved = load(cache_item.file_path)
    assert saved.last_action == 'cached_data'
    assert saved.item_list_hash == datamanager.get_data_hash(cache_item.item_list)
    assert notified == []


def recheck(tmp_path, monkeypatch, cached_items, server_items):
    refreshed = []
    FakeHomeWindow.properties = {}
    monkeypatch.setattr(datamanager.DataManager, 'addon_dir', str(tmp_path))
    monkeypatch.setattr(datamanager, 'HomeWindow', FakeHomeWindow)
    monkeypatch.setattr(datamanager.xbmc, 'executebuiltin', refreshed.append)
    monkeypatch.setattr(datamanager.api, 'get', lambda url: {
        'TotalRecordCount': len(server_items), 'Items': server_items})
    monkeypatch.setattr(datamanager, 'extract_item_info',
                        lambda item, gui_options: Item(item['Name'], item['PlayCount']))
    cache_item = make_cache_item(tmp_path, cached_items, 'cached_data', 60)
    datamanager.save_cache_item(cache_item)

    datamanager.recheck_cache('cache_abc.pickle', {})

    return load(cache_item.file_path), refreshed


def test_recheck_saves_changed_items_and_refreshes_the_container(tmp_path, monkeypatch):
    saved, refreshed = recheck(tmp_path, monkeypatch, [Item('a')],
                               [{'Name': 'a', 'PlayCount': 1}, {'Name': 'b', 'PlayCount': 0}])

    assert [item.name for item in saved.item_list] == ['a', 'b']
    assert saved.item_list_hash == datamanager.get_data_hash(saved.item_list)
    assert saved.last_action == 'fresh_data'
    assert saved.total_records == 2
    assert refreshed == ['Container.Refresh']
    assert FakeHomeWindow.properties.get('jellycon_widget_reload')


def test_recheck_of_unchanged_items_only_marks_them_used(tmp_path, monkeypatch):
    saved, refreshed = recheck(tmp_path, monkeypatch, [Item('a')], [{'Name': 'a', 'PlayCount': 0}])

    assert saved.last_action == 'cached_data'
    assert time.time() - saved.date_last_used < 5
    assert refreshed == []


def test_recheck_skips_a_deleted_cache_file(tmp_path, monkeypatch):
    monkeypatch.setattr(datamanager.DataManager, 'addon_dir', str(tmp_path))
    monkeypatch.setattr(datamanager.api, 'get', lambda url: 1 / 0)

    datamanager.recheck_cache('cache_gone.pickle', {})

    assert not os.path.exists(str(tmp_path / 'cache_gone.pickle'))


def test_service_passes_cache_check_to_its_thread():
    requests = []

    class Recheck(object):
        def add(self, cache_file, gui_options):
            requests.append((cache_file, gui_options))

    service = play_utils.PlaybackService(None, Recheck())
    payload = {'cache_file': 'cache_abc.pickle', 'gui_options': {'server': 'http://server'}}
    service.onNotification('plugin.video.jellycon', 'Other.jellycon_cache_check', json.dumps([payload]))

    assert requests == [('cache_abc.pickle', {'server': 'http://server'})]


def test_recheck_service_checks_a_listing_once_and_stops(monkeypatch):
    checked = []
    monkeypatch.setattr(datamanager, 'recheck_cache',
                        lambda cache_file, gui_options: checked.append(cache_file))
    service = datamanager.CacheRecheckService()
    service.add('cache_a.pickle', {})
    service.add('cache_a.pickle', {})
    service.add('cache_b.pickle', {})

    service.start()
    end = time.time() + 5
    while len(checked) < 2 and time.time() < end:
        time.sleep(0.01)
    service.stop()
    service.join(5)

    assert not service.is_alive()
    assert checked == ['cache_a.pickle', 'cache_b.pickle']
