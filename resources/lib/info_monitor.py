"""
Loads item info lazily, only when the user opens Kodi's video information dialog on a JellyCon item.
"""
from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from .lazylogger import LazyLogger
from .kodi_utils import HomeWindow

log = LazyLogger(__name__)

INFO_WINDOW = "movieinformation"
LOADED_PROPERTY = "jellycon_info_loaded"
FALLBACK_PROPERTY = "jellycon_info_fallback"
SETTING = "info_load_people"
# A skin that shows cast and crew from elsewhere (TMDb Helper) sets this
# home window property to its own id, e.g. SetProperty(JellyCon.SkipInfoLoad,skin.nightcity,home)
SKIP_PROPERTY = "JellyCon.SkipInfoLoad"


def load_enabled():
    return xbmcaddon.Addon().getSetting(SETTING) != "false"


def skipped_by_skin():
    return xbmcgui.Window(10000).getProperty(SKIP_PROPERTY) == xbmc.getSkinDir()


class _SettingsMonitor(xbmc.Monitor):

    def __init__(self, on_change):
        xbmc.Monitor.__init__(self)
        self._on_change = on_change

    def onSettingsChanged(self):
        self._on_change()


class InfoDialogMonitor(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self._stop_event = threading.Event()
        self._settings_changed = threading.Event()
        self._monitor = _SettingsMonitor(self._settings_changed.set)
        self.enabled = load_enabled()

    def stop_monitor(self):
        self._stop_event.set()
        self._settings_changed.set()

    def run(self):
        was_active = False
        while not self._stop_event.is_set() and not self._monitor.abortRequested():
            if self._settings_changed.is_set():
                self._settings_changed.clear()
                self.enabled = load_enabled()
            if not self.enabled:
                # Switched off: no polling until the setting changes or the service stops
                self._settings_changed.wait()
                was_active = False
                continue
            active = xbmc.getCondVisibility(
                "Window.IsActive({})".format(INFO_WINDOW)
            )
            # only react when the dialog has just been opened
            if active and not was_active:
                try:
                    self._on_info_opened()
                except Exception as err:
                    log.error("Info dialog monitor error: {0}".format(err))
            was_active = active
            if self._monitor.waitForAbort(0.1):
                break

    def _on_info_opened(self):
        if skipped_by_skin():
            return
        item_id = ""
        item_type = ""
        # the dialog's item may take a moment to become available
        for _ in range(5):
            item_id = xbmc.getInfoLabel("ListItem.Property(id)")
            item_type = xbmc.getInfoLabel("ListItem.Property(ItemType)")
            if item_id:
                break
            xbmc.sleep(100)

        if not item_id or not item_type:
            # not a JellyCon item
            return

        if xbmc.getInfoLabel("ListItem.Property({})".format(LOADED_PROPERTY)) == "true":
            # this is the dialog we opened ourselves, cast already loaded
            return

        window = HomeWindow()
        fallback = window.get_property(FALLBACK_PROPERTY)
        if fallback:
            window.clear_property(FALLBACK_PROPERTY)
            try:
                if time.time() - float(fallback) < 5:
                    # opened the native dialog, leave it alone (no loop)
                    return
            except ValueError:
                pass

        log.debug("Info dialog opened for {0} ({1}), loading cast".format(item_id, item_type))
        # The native dialog stays open while the plugin fetches the data and
        # replaces it, so there is no gap showing the list in between.
        xbmc.executebuiltin(
            "RunPlugin(plugin://plugin.video.jellycon/?mode=SHOW_INFO&item_id={})".format(item_id)
        )
