# coding=utf-8
# Gnu General Public License - see LICENSE.TXT

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.lazylogger import LazyLogger
from resources.lib.play_utils import Service, PlaybackService
from resources.lib.kodi_utils import HomeWindow
from resources.lib.websocket_client import WebSocketClient
from resources.lib.server_detect import check_server
from resources.lib.monitors import LibraryChangeMonitor, ContextMonitor
from resources.lib.datamanager import clear_old_cache_data, clear_cached_server_data
from resources.lib.tracking import set_timing_enabled
from resources.lib.image_server import HttpImageServerThread
from resources.lib.playnext import PlayNextService
from resources.lib.intro_skipper import IntroSkipperService
from resources.lib.service_tasks import ServiceTasks

settings = xbmcaddon.Addon()

log_timing_data = settings.getSetting('log_timing') == "true"
if log_timing_data:
    set_timing_enabled(True)

# clear user and token when logging in
home_window = HomeWindow()
home_window.clear_property("user_name")
home_window.clear_property("AccessToken")
home_window.clear_property("Params")

log = LazyLogger('service')
kodi_monitor = xbmc.Monitor()

addon_version = settings.getAddonInfo('version')
try:
    """
    The data structure has changed in version 1.0.0.
    Clear all cached data to ensure a clean startup
    TODO: Remove once we reach 1.1.0
    """
    if addon_version.startswith('1.0'):
        clear_cached_server_data(False)
    else:
        clear_old_cache_data()
except Exception as error:
    log.error("Error in clear_old_cache_data() : {0}".format(error))

# wait for 10 seconds for the Kodi splash screen to close
i = 0
while not kodi_monitor.abortRequested():
    if i == 100 or not xbmc.getCondVisibility("Window.IsVisible(startup)"):
        break
    i += 1
    xbmc.sleep(100)

check_server()

image_server = HttpImageServerThread()
image_server.start()

# set up all the services
monitor = Service()
playback_service = PlaybackService(monitor)

home_window = HomeWindow()

# start the library update monitor
library_change_monitor = LibraryChangeMonitor()
library_change_monitor.start()

# start the WebSocket Client running
remote_control = settings.getSetting('websocket_enabled') == "true"
websocket_client = WebSocketClient(library_change_monitor)
if remote_control:
    websocket_client.start()

play_next_service = None
play_next_trigger_time = int(settings.getSetting('play_next_trigger_time'))
if play_next_trigger_time > 0:
    play_next_service = PlayNextService(monitor)
    play_next_service.start()

# Start the context menu monitor
context_monitor = None
context_menu = settings.getSetting('override_contextmenu') == "true"
if context_menu:
    context_monitor = ContextMonitor()
    context_monitor.start()

# Start the skip service monitor
intro_skipper = IntroSkipperService(monitor)
intro_skipper.start()

enable_logging = settings.getSetting('log_debug') == "true"
if enable_logging:
    xbmcgui.Dialog().notification(settings.getAddonInfo('name'),
                                  "Debug logging enabled!",
                                  time=8000,
                                  icon=xbmcgui.NOTIFICATION_WARNING)

home_window.set_property('exit', 'False')

# The periodic work runs on its own thread, so this thread is free to run
# the callbacks of the Player and Monitor above, which Kodi only calls while
# this thread waits in waitForAbort()
service_tasks = ServiceTasks(library_change_monitor, websocket_client, remote_control)
service_tasks.start()

while home_window.get_property('exit') == 'False' and not kodi_monitor.abortRequested():
    kodi_monitor.waitForAbort(1)

service_tasks.stop()
# Kodi kills a service that needs more than 5 seconds to stop
service_tasks.join(2)
websocket_client = service_tasks.websocket_client

image_server.stop()

# stop the WebSocket Client
websocket_client.stop_client()

# call stop on the library update monitor
library_change_monitor.stop()

# stop the play next episode service
if play_next_service:
    play_next_service.stop_service()

# call stop on the context menu monitor
if context_monitor:
    context_monitor.stop_monitor()

if intro_skipper:
    intro_skipper.stop_service()

# clear user and token when logging off
home_window.clear_property("user_name")
home_window.clear_property("AccessToken")
home_window.clear_property("userimage")

log.debug("Service shutting down")
