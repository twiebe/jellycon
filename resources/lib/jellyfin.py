from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import json

import requests
import xbmc
import xbmcaddon
import xbmcgui
from kodi_six.utils import py2_decode

from .utils import (
    get_device_id, get_version, load_user_details, clear_user_details,
    translate_string
)
from .kodi_utils import HomeWindow
from .lazylogger import LazyLogger

log = LazyLogger(__name__)


class API:
    def __init__(self, server=None, user_id=None, token=None):
        self.server = server
        self.user_id = user_id
        self.token = token

        self.settings = xbmcaddon.Addon()

        self.headers = {}
        self.last_error = None
        self.error_notified = False
        self.token_rejected = False
        self.create_headers()
        self.verify_cert = settings.getSetting('verify_cert') == 'true'

    def request(self, method, path, payload=None, timeout=5):
        '''
        Send a request to the server. Returns a tuple (ok, data): ok is True
        for a 2xx response, data is the decoded JSON body or {}.

        On failure, self.last_error holds a short reason for the user and
        self.error_notified tells whether a notification about it was just
        shown (server became unreachable), so callers do not show a second
        one. self.token_rejected is set when the server refused our token.
        Background requests can ignore failures: the user hears about an
        unreachable server or a rejected login once, not on every request.
        '''
        self.last_error = None
        self.error_notified = False
        self.token_rejected = False

        if 'Authorization' not in self.headers or self.token not in self.headers:
            self.create_headers(True)

        # Fixes initial login where class is initialized before wizard completes
        if not self.server:
            self.settings = xbmcaddon.Addon()
            self.server = self.settings.getSetting('server_address')

        url = '{}{}'.format(self.server, path)

        try:
            r = requests.request(method, url, json=payload, headers=self.headers,
                                 verify=self.verify_cert, timeout=timeout)
        except requests.exceptions.ReadTimeout as error:
            log.error('{0} {1} failed: {2}'.format(method, path, error))
            self.last_error = translate_string(30787)
            return False, {}
        except Exception as error:
            log.error('{0} {1} failed: {2}'.format(method, path, error))
            self.last_error = translate_string(30786)
            self.set_server_reachable(False)
            return False, {}

        self.set_server_reachable(True)

        if not r.ok:
            log.error('{0} {1} failed: HTTP {2} {3}'.format(
                method, path, r.status_code, r.text[:200]))
            self.last_error = self.describe_status(r.status_code)
            if r.status_code == 401 and self.is_token_rejection(path):
                self.token_rejected = True
                HomeWindow().set_property('auth_rejected', 'true')
            return False, {}

        # The token works (again), e.g. after a retry or a new login
        home_window = HomeWindow()
        if home_window.get_property('auth_rejected') and 'Token=' in self.headers.get('Authorization', ''):
            home_window.clear_property('auth_rejected')
            home_window.clear_property('auth_rejected_snoozed')

        if not r.content:
            return True, {}
        try:
            '''
            The requests library defaults to using simplejson to handle
            json decoding.  On low power devices and using Py3, this is
            significantly slower than the builtin json library.  Skip that
            and just parse the json ourselves.  Fall back to using
            requests/simplejson if there's a parsing error.
            '''
            return True, json.loads(r.text)
        except ValueError:
            try:
                return True, r.json()
            except ValueError:
                return True, {}

    @staticmethod
    def describe_status(status_code):
        if status_code == 401:
            return translate_string(30784)
        if status_code == 403:
            return translate_string(30789)
        if status_code == 404:
            return translate_string(30788)
        if status_code >= 500:
            return translate_string(30790).format(status_code)
        return translate_string(30791).format(status_code)

    def set_server_reachable(self, reachable):
        '''
        Notify once when the server becomes unreachable and once when it is
        back. The state lives in a window property, shared by the service
        and all plugin invocations.
        '''
        home_window = HomeWindow()
        was_unreachable = home_window.get_property('server_unreachable') == 'true'
        if reachable and was_unreachable:
            home_window.clear_property('server_unreachable')
            self.notify(translate_string(30792), xbmcgui.NOTIFICATION_INFO)
        elif not reachable and not was_unreachable:
            home_window.set_property('server_unreachable', 'true')
            self.notify(translate_string(30786))
            self.error_notified = True

    def notify_failed(self, action_string_id):
        '''
        Tell the user why the last request of an action failed, e.g.
        "Mark Unwatched failed: Server not reachable". Skipped when a
        notification about the same problem was just shown. A rejected
        login asks the user what to do instead.
        '''
        if self.token_rejected:
            self.resolve_unauthorized()
            return
        if self.error_notified:
            return
        self.notify(translate_string(30785).format(
            translate_string(action_string_id), self.last_error))

    def notify(self, message, icon=xbmcgui.NOTIFICATION_ERROR):
        xbmcgui.Dialog().notification(
            self.settings.getAddonInfo('name'), message, icon=icon, time=8000)

    def get(self, path):
        return self.request('GET', path, timeout=(5, 60))[1]

    def post(self, url, payload={}):
        return self.request('POST', url, payload)[1]

    def delete(self, url):
        return self.request('DELETE', url)[0]

    def is_token_rejection(self, path):
        '''
        A 401 means the server refused our token, e.g. because it was revoked
        when the user was disabled. Failed logins and Quick Connect (401 when
        disabled on the server) say nothing about the token.
        '''
        if 'Token=' not in self.headers.get('Authorization', ''):
            return False
        return not path.startswith(('/Users/AuthenticateByName', '/Users/AuthenticateWithQuickConnect',
                                    '/QuickConnect/'))

    def resolve_unauthorized(self, relogin=True):
        '''
        Ask the user what to do about a rejected token: sign in again, retry
        with the saved login, or leave it for now. With relogin=False the
        caller runs the login itself.
        Returns 'relogin' (saved login dropped), 'ok' (retry worked) or
        'cancel'.
        '''
        home_window = HomeWindow()
        # The service and a plugin call may both run into the same 401
        if home_window.get_property('auth_dialog_open') == 'true':
            return 'cancel'
        home_window.set_property('auth_dialog_open', 'true')
        try:
            user_name = home_window.get_property('user_name') or self.settings.getSetting('username')
            while True:
                choice = self.ask_unauthorized(user_name)

                if choice == 'retry':
                    ok, _ = self.request('GET', '/Users/Me')
                    if ok:
                        self.notify(translate_string(30797), xbmcgui.NOTIFICATION_INFO)
                        return 'ok'
                    if self.token_rejected:
                        continue
                    self.notify_failed(30796)
                    return 'cancel'

                if choice == 'relogin':
                    log.info('Dropping the saved login of user {0}'.format(user_name))
                    clear_user_details(user_name)
                    self.token = None
                    self.create_headers(True)
                    home_window.clear_property('auth_rejected')
                    home_window.clear_property('auth_rejected_snoozed')
                    if relogin:
                        # Imported here, server_detect imports this module
                        from .server_detect import check_server
                        check_server(change_user=True)
                    return 'relogin'

                # Keep the token, background requests stop asking until
                # the user runs into the problem again
                home_window.set_property('auth_rejected_snoozed', 'true')
                return 'cancel'
        finally:
            home_window.clear_property('auth_dialog_open')

    def ask_unauthorized(self, user_name):
        dialog = xbmcgui.Dialog()
        heading = self.settings.getAddonInfo('name')
        message = translate_string(30794).format(user_name)
        if hasattr(dialog, 'yesnocustom'):
            choice = dialog.yesnocustom(
                heading, message, customlabel=xbmc.getLocalizedString(222),
                nolabel=translate_string(30796), yeslabel=translate_string(30795))
            return {1: 'relogin', 0: 'retry'}.get(choice, 'cancel')
        # Kodi 18 has no third button
        choice = dialog.yesno(heading, message, nolabel=translate_string(30796),
                              yeslabel=translate_string(30795))
        return 'relogin' if choice else 'retry'

    def authenticate(self, auth_data):
        # Always force create fresh headers during authentication
        self.create_headers(True)
        response = self.post('/Users/AuthenticateByName', auth_data)
        token = response.get('AccessToken')
        if token:
            self.token = token
            self.user_id = response.get('User').get('Id')
            # Create headers again to include auth token
            self.create_headers()
            return response
        else:
            log.error('Unable to authenticate to Jellyfin server')
            return {}

    def create_headers(self, force=False):

        # If the headers already exist with an auth token, return unless we're regenerating
        if self.headers and 'Authorization' in self.headers.get('Authorization', '') and force is False:
            return

        headers = {}
        device_name = self.settings.getSetting('deviceName')
        if len(device_name) == 0:
            device_name = "JellyCon"
        # Ensure ascii and remove invalid characters
        device_name = py2_decode(device_name).replace('"', '_').replace(',', '_')
        device_id = get_device_id()
        version = get_version()

        authorization = (
            'MediaBrowser Client="Kodi JellyCon", Device="{device}", '
            'DeviceId="{device_id}", Version="{version}"'
        ).format(
            device=device_name,
            device_id=device_id,
            version=version
        )

        headers['Authorization'] = authorization

        # If we have a valid token, ensure it's included in the headers unless we're regenerating
        if self.token and force is False:
            headers['Authorization'] += ', Token="{}"'.format(self.token)
        else:
            # Check for updated credentials since initialization
            user_details = load_user_details()
            token = user_details.get('token')
            if token:
                self.token = token
                headers['Authorization'] += ", Token={}".format(self.token)

        # Kodi doesn't support br or zstd compression, exclude them
        headers['Accept-Encoding'] = 'gzip, deflate'

        # Make headers available to api calls
        self.headers = headers

    def post_capabilities(self):
        url = '/Sessions/Capabilities/Full'

        data = {
            'SupportsMediaControl': True,
            'PlayableMediaTypes': ["Video", "Audio"],
            'SupportedCommands': ["MoveUp",
                                  "MoveDown",
                                  "MoveLeft",
                                  "MoveRight",
                                  "Select",
                                  "Back",
                                  "ToggleContextMenu",
                                  "ToggleFullscreen",
                                  "ToggleOsdMenu",
                                  "GoHome",
                                  "PageUp",
                                  "NextLetter",
                                  "GoToSearch",
                                  "GoToSettings",
                                  "PageDown",
                                  "PreviousLetter",
                                  "TakeScreenshot",
                                  "VolumeUp",
                                  "VolumeDown",
                                  "ToggleMute",
                                  "SendString",
                                  "DisplayMessage",
                                  "SetAudioStreamIndex",
                                  "SetSubtitleStreamIndex",
                                  "SetRepeatMode",
                                  "Mute",
                                  "Unmute",
                                  "SetVolume",
                                  "PlayNext",
                                  "Play",
                                  "Playstate",
                                  "PlayMediaSource"]
        }

        self.post(url, data)

    def speedtest(self, test_data_size):
        self.create_headers()

        url = '{}/playback/bitratetest?size={}'.format(self.server, test_data_size)
        # Because this needs the stream argument, this doesn't go through self.get()
        response = requests.get(url, stream=True, headers=self.headers, verify=self.verify_cert)

        return response


settings = xbmcaddon.Addon()
user_details = load_user_details()
api = API(
    settings.getSetting('server_address'),
    user_details.get('user_id'),
    user_details.get('token')
)
