# Gnu General Public License - see LICENSE.TXT

import xbmc
import xbmcaddon

from resources.lib.lazylogger import LazyLogger
from resources.lib.functions import main_entry_point, handle_entry_point_error
from resources.lib.tracking import set_timing_enabled

log = LazyLogger('default')

settings = xbmcaddon.Addon()
log_timing_data = settings.getSetting('log_timing') == "true"
if log_timing_data:
    set_timing_enabled(True)

log.debug("About to enter mainEntryPoint()")

try:
    main_entry_point()
except Exception:
    handle_entry_point_error()

# Kodi notices a Back pressed while a listing loads only when the listing
# is handed over, and stops the plugin then. A stop that comes while the
# plugin exits races Kodi's cleanup of the plugin and can crash Kodi.
# Wait a moment, so the stop finds the plugin still running; it ends the
# wait.
xbmc.Monitor().waitForAbort(0.25)
