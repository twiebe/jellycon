from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import threading
import hashlib
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs
import xbmcgui
from six.moves import cPickle, queue

from .jellyfin import api
from .lazylogger import LazyLogger
from .item_functions import extract_item_info
from .kodi_utils import HomeWindow
from .tracking import timer
from .filelock import FileLock
from .utils import translate_string, load_user_details, translate_path, send_event_notification

log = LazyLogger(__name__)


class CacheItem:
    item_list = None
    item_list_hash = None
    date_saved = None
    date_last_used = None
    last_action = None
    items_url = None
    file_path = None
    user_id = None

    def __init__(self, *args):
        pass


class DataManager:

    addon_dir = translate_path(xbmcaddon.Addon().getAddonInfo('profile'))

    def __init__(self, *args):
        self.user_details = load_user_details()

        self.api = api

    @timer
    def get_items(self, url, gui_options, use_cache=False):

        home_window = HomeWindow()
        log.debug("last_content_url : use_cache={0} url={1}".format(use_cache, url))
        home_window.set_property("last_content_url", url)

        user_id = self.user_details.get('user_id')
        server = self.api.server

        m = hashlib.md5()
        m.update('{}|{}|{}'.format(user_id, server, url).encode())
        url_hash = m.hexdigest()
        cache_file = os.path.join(self.addon_dir, "cache_" + url_hash + ".pickle")

        item_list = None
        total_records = 0
        baseline_name = None
        cached_item = None

        home_window.set_property(cache_file, "true")

        clear_cache = home_window.get_property("skip_cache_for_" + url)
        if clear_cache and os.path.isfile(cache_file):
            log.debug("Clearing cache data and loading new data")
            home_window.clear_property("skip_cache_for_" + url)
            os.remove(cache_file)

        # try to load the list item data from the cache
        if os.path.isfile(cache_file) and use_cache:
            log.debug("Loading url data from cached pickle data")

            with FileLock(cache_file + ".locked", timeout=5):
                with open(cache_file, 'rb') as handle:
                    try:
                        cache_item = cPickle.load(handle)
                        cached_item = cache_item
                        item_list = cache_item.item_list
                        total_records = cache_item.total_records
                    except Exception as err:
                        log.error("Pickle Data Load Failed : {0}".format(err))
                        item_list = None

        # we need to load the list item data form the server
        if item_list is None or len(item_list) == 0:
            log.debug("Loading url data from server")

            results = self.api.get(url)

            if results is None:
                results = []

            if isinstance(results, dict):
                total_records = results.get("TotalRecordCount", 0)

            if isinstance(results, dict) and results.get("Items") is not None:
                baseline_name = results.get("BaselineItemName")
                results = results.get("Items", [])
            elif isinstance(results, list) and len(results) > 0 and results[0].get("Items") is not None:
                baseline_name = results[0].get("BaselineItemName")
                results = results[0].get("Items")

            item_list = []
            for item in results:
                item_data = extract_item_info(item, gui_options)
                item_data.baseline_itemname = baseline_name
                item_list.append(item_data)

            cache_item = CacheItem()
            cache_item.item_list = item_list
            cache_item.file_path = cache_file
            cache_item.items_url = url
            cache_item.user_id = user_id
            cache_item.last_action = "fresh_data"
            cache_item.date_saved = time.time()
            cache_item.date_last_used = time.time()
            cache_item.total_records = total_records

            cached_item = cache_item

        cache_check = None
        if use_cache:
            cache_check = CacheCheck(cached_item, gui_options)

        return cache_file, item_list, total_records, cache_check


def get_data_hash(items):

    m = hashlib.md5()
    for item in items:
        item_string = "%s_%s_%s_%s_%s_%s" % (
            item.name,
            item.play_count,
            item.favorite,
            item.resume_time,
            item.recursive_unplayed_items_count,
            item.etag
        )
        item_string = item_string.encode("UTF-8")
        m.update(item_string)

    return m.hexdigest()


def save_cache_item(cache_item):
    with FileLock(cache_item.file_path + ".locked", timeout=5):
        with open(cache_item.file_path, 'wb') as handle:
            cPickle.dump(cache_item, handle, protocol=cPickle.HIGHEST_PROTOCOL)


class CacheCheck:
    """
    Cache work left for a listing once it is built. The plugin runs it
    before it returns the listing. Fresh data is saved right away, the
    check of cached data against the server goes to the service: while a
    thread of the plugin runs, Kodi keeps the invocation alive, and
    stopping it then (e.g. on a quick Back) can crash Kodi.
    """

    def __init__(self, cached_item, gui_options):
        self.cached_item = cached_item
        self.gui_options = gui_options

    def run(self):
        cached_item = self.cached_item

        # if the data is fresh then just save it
        # if the data is to old do a reload
        is_fresh = (cached_item.date_saved is not None
                    and (time.time() - cached_item.date_saved) < 20
                    and cached_item.last_action == "fresh_data")

        if is_fresh and cached_item.item_list:
            log.debug("CacheCheck : Saving fresh data")
            cached_item.item_list_hash = get_data_hash(cached_item.item_list)
            cached_item.last_action = "cached_data"
            cached_item.date_saved = time.time()
            cached_item.date_last_used = time.time()
            save_cache_item(cached_item)
        else:
            log.debug("CacheCheck : Asking the service to recheck the cached data")
            send_event_notification("jellycon_cache_check", {
                "cache_file": os.path.basename(cached_item.file_path),
                "gui_options": self.gui_options
            })


def recheck_cache(cache_file, gui_options):
    """
    Reload the items of a cached listing and compare them with the cache.
    If they changed, save them and refresh the container. Runs in the
    service.
    """
    cache_path = os.path.join(DataManager.addon_dir, os.path.basename(cache_file))
    if not os.path.isfile(cache_path):
        log.debug("recheck_cache : Cache file is gone : {0}".format(cache_file))
        return

    try:
        with FileLock(cache_path + ".locked", timeout=5):
            with open(cache_path, 'rb') as handle:
                cached_item = cPickle.load(handle)
    except Exception as err:
        log.error("recheck_cache : Pickle Data Load Failed : {0}".format(err))
        return

    log.debug("recheck_cache : Reloading to recheck data hashes")
    cached_hash = cached_item.item_list_hash
    log.debug("recheck_cache : Cache Hash : {0}".format(cached_hash))

    results = api.get(cached_item.items_url)
    if results is None:
        results = []

    total_records = 0
    if isinstance(results, dict):
        total_records = results.get("TotalRecordCount", 0)

    if isinstance(results, dict) and results.get("Items") is not None:
        results = results.get("Items", [])
    elif isinstance(results, list) and len(results) > 0 and results[0].get("Items") is not None:
        results = results[0].get("Items")

    loaded_items = []
    for item in results:
        item_data = extract_item_info(item, gui_options)
        loaded_items.append(item_data)

    if len(loaded_items) == 0:
        log.debug("recheck_cache : loaded_items is Empty so not saving it")
        return

    loaded_hash = get_data_hash(loaded_items)
    log.debug("recheck_cache : Loaded Hash : {0}".format(loaded_hash))

    # if they dont match then save the data and trigger a content reload
    if cached_hash != loaded_hash:
        log.debug("recheck_cache : Hashes different, saving new data and reloading container")

        cached_item.item_list = loaded_items
        cached_item.item_list_hash = loaded_hash
        cached_item.last_action = "fresh_data"
        cached_item.date_saved = time.time()
        cached_item.date_last_used = time.time()
        cached_item.total_records = total_records
        save_cache_item(cached_item)

        # TODO: probably should only set this in simple check mode
        current_time_stamp = str(time.time())
        HomeWindow().set_property("jellycon_widget_reload", current_time_stamp)
        log.debug("Setting New Widget Hash: {0}".format(current_time_stamp))

        log.debug("recheck_cache : Sending container refresh")
        xbmc.executebuiltin("Container.Refresh")

    else:
        cached_item.date_last_used = time.time()
        save_cache_item(cached_item)
        log.debug("recheck_cache : Updating last used date for cache data")


class CacheRecheckService(threading.Thread):
    """
    Runs the cache checks the plugin asks for (jellycon_cache_check) one
    after the other, on its own thread so the service does not wait for
    the server.
    """

    def __init__(self):
        super(CacheRecheckService, self).__init__()
        self.requests = queue.Queue()
        self.pending = set()
        self.lock = threading.Lock()
        self.stop_thread = False

    def add(self, cache_file, gui_options):
        with self.lock:
            # a listing opened again before its check ran is checked once
            if cache_file in self.pending:
                return
            self.pending.add(cache_file)
        self.requests.put((cache_file, gui_options))

    def stop(self):
        self.stop_thread = True
        self.requests.put(None)

    def run(self):
        log.debug("CacheRecheckService : Started")
        while not self.stop_thread:
            request = self.requests.get()
            if request is None:
                continue
            cache_file, gui_options = request
            with self.lock:
                self.pending.discard(cache_file)
            try:
                recheck_cache(cache_file, gui_options)
            except Exception as err:
                log.error("CacheRecheckService : Cache check failed : {0}".format(err))
        log.debug("CacheRecheckService : Exited")


def clear_cached_server_data(display=True):
    log.debug("clear_cached_server_data() called")

    addon_dir = translate_path(xbmcaddon.Addon().getAddonInfo('profile'))
    dirs, files = xbmcvfs.listdir(addon_dir)

    del_count = 0
    for filename in files:
        if filename.startswith("cache_") and filename.endswith(".pickle"):
            log.debug("Deleting CacheFile: {0}".format(filename))
            xbmcvfs.delete(os.path.join(addon_dir, filename))
            del_count += 1

    log.debug('Deleted {} files'.format(del_count))
    if display:
        msg = translate_string(30394)
        xbmcgui.Dialog().ok(translate_string(30393), msg)


def clear_old_cache_data():
    log.debug("clear_old_cache_data() : called")

    addon_dir = translate_path(xbmcaddon.Addon().getAddonInfo('profile'))
    dirs, files = xbmcvfs.listdir(addon_dir)

    del_count = 0
    for filename in files:
        if filename.startswith("cache_") and filename.endswith(".pickle"):
            log.debug("clear_old_cache_data() : Checking CacheFile : {0}".format(filename))

            cache_item = None
            for x in range(0, 5):
                try:
                    data_file = os.path.join(addon_dir, filename)
                    with FileLock(data_file + ".locked", timeout=5):
                        with open(data_file, 'rb') as handle:
                            cache_item = cPickle.load(handle)
                    break
                except Exception as error:
                    log.debug("clear_old_cache_data() : Pickle load error : {0}".format(error))
                    cache_item = None
                    xbmc.sleep(1000)

            if cache_item is not None:
                item_last_used = -1
                if cache_item.date_last_used is not None:
                    item_last_used = time.time() - cache_item.date_last_used

                log.debug("clear_old_cache_data() : Cache item last used : {0} sec ago".format(item_last_used))
                if item_last_used == -1 or item_last_used > (3600 * 24 * 7):
                    log.debug("clear_old_cache_data() : Deleting cache item age : {0}".format(item_last_used))
                    data_file = os.path.join(addon_dir, filename)
                    with FileLock(data_file + ".locked", timeout=5):
                        xbmcvfs.delete(data_file)
                    del_count += 1
            else:
                log.debug("clear_old_cache_data() : Deleting unloadable cache item")
                data_file = os.path.join(addon_dir, filename)
                with FileLock(data_file + ".locked", timeout=5):
                    xbmcvfs.delete(data_file)

    log.debug("clear_old_cache_data() : Cache items deleted : {0}".format(del_count))
