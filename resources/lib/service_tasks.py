# Gnu General Public License - see LICENSE.TXT
from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui

from .jellyfin import api
from .kodi_utils import HomeWindow
from .lazylogger import LazyLogger
from .menu_functions import set_library_window_values
from .play_utils import send_progress
from .server_detect import check_connection_speed
from .websocket_client import WebSocketClient
from .widgets import set_background_image, set_random_movies, set_random_tvshows, set_random_all

log = LazyLogger(__name__)


class ServiceTasks(threading.Thread):
    '''
    The periodic work of the service: progress reports, widget and
    background updates, update checks. It talks to the server, so it runs
    on its own thread. The Player and Monitor callbacks of the service only
    run while the main thread waits in waitForAbort().
    '''

    def __init__(self, library_change_monitor, websocket_client, remote_control):
        super(ServiceTasks, self).__init__()
        self.stop_thread = False
        self.library_change_monitor = library_change_monitor
        self.websocket_client = websocket_client
        self.remote_control = remote_control

        settings = xbmcaddon.Addon()
        self.background_interval = int(settings.getSetting('background_interval'))
        self.newcontent_interval = int(settings.getSetting('new_content_check_interval'))
        self.random_movie_list_interval = int(settings.getSetting('random_movie_refresh_interval')) * 60

        self.home_window = HomeWindow()
        self.prev_user = self.home_window.get_property("user_name")
        self.first_run = True
        self.last_progress_update = time.time()
        self.last_content_check = time.time()
        self.last_background_update = 0
        self.last_random_movie_update = 0
        self.last_random_tvshow_update = 0
        self.last_random_all_update = 0

    def stop(self):
        self.stop_thread = True

    def run(self):
        log.debug("ServiceTasks Thread Started")
        monitor = xbmc.Monitor()
        while (not self.stop_thread and not monitor.abortRequested()
               and self.home_window.get_property('exit') == 'False'):
            self.run_once()
            if monitor.waitForAbort(1):
                break
        log.debug("ServiceTasks Thread Exited")

    def run_once(self):
        home_window = self.home_window
        random_movie_list_interval = self.random_movie_list_interval
        background_interval = self.background_interval
        newcontent_interval = self.newcontent_interval
        try:
            if xbmc.Player().isPlaying():
                self.last_random_movie_update = time.time() - (random_movie_list_interval - 15)
                # if playing every 10 seconds updated the server with progress
                if (time.time() - self.last_progress_update) > 10:
                    self.last_progress_update = time.time()
                    send_progress()

            else:
                screen_saver_active = xbmc.getCondVisibility("System.ScreenSaverActive")

                if not screen_saver_active:
                    # The server rejected our token, ask the user what to do
                    if (home_window.get_property('auth_rejected') == 'true'
                            and home_window.get_property('auth_rejected_snoozed') != 'true'):
                        api.resolve_unauthorized()

                    user_changed = False
                    if self.prev_user != home_window.get_property("user_name"):
                        log.debug("user_change_detected")
                        self.prev_user = home_window.get_property("user_name")
                        user_changed = True

                    if user_changed or self.first_run:
                        settings = xbmcaddon.Addon()
                        server_speed_check_data = settings.getSetting("server_speed_check_data")
                        server_host = settings.getSetting('server_address')
                        if server_host is not None and server_host != "" and server_host != "<none>" and server_host not in server_speed_check_data:
                            message = "This is the first time you have connected to this server.\nDo you want to run a connection speed test?"
                            response = xbmcgui.Dialog().yesno("First Connection", message)
                            if response:
                                speed = check_connection_speed()
                                if speed > 0:
                                    settings.setSetting("server_speed_check_data", server_host + "-" + str(speed))
                            else:
                                settings.setSetting("server_speed_check_data", server_host + "-skipped")

                    if user_changed or (random_movie_list_interval != 0 and (time.time() - self.last_random_movie_update) > random_movie_list_interval):
                        self.last_random_movie_update = time.time()
                        set_random_movies()

                    if user_changed or (random_movie_list_interval != 0 and (time.time() - self.last_random_tvshow_update) > random_movie_list_interval):
                        self.last_random_tvshow_update = time.time()
                        set_random_tvshows()

                    if user_changed or (random_movie_list_interval != 0 and (time.time() - self.last_random_all_update) > random_movie_list_interval):
                        self.last_random_all_update = time.time()
                        set_random_all()

                    if user_changed or (newcontent_interval != 0 and (time.time() - self.last_content_check) > newcontent_interval):
                        self.last_content_check = time.time()
                        self.library_change_monitor.check_for_updates()

                    if user_changed or (background_interval != 0 and (time.time() - self.last_background_update) > background_interval):
                        self.last_background_update = time.time()
                        set_library_window_values(user_changed)
                        set_background_image(user_changed)

                    if self.remote_control and user_changed:
                        self.websocket_client.stop_client()
                        self.websocket_client = WebSocketClient(self.library_change_monitor)
                        self.websocket_client.start()

                elif screen_saver_active:
                    self.last_random_movie_update = time.time() - (random_movie_list_interval - 15)
                    if background_interval != 0 and ((time.time() - self.last_background_update) > background_interval):
                        self.last_background_update = time.time()
                        set_background_image(False)

        except Exception as error:
            log.error("Exception in Playback Monitor: {0}".format(error))
            log.error("{0}".format(traceback.format_exc()))

        self.first_run = False
