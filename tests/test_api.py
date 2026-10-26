from __future__ import (
    division, absolute_import, print_function, unicode_literals
)

import json

import pytest
import requests

from resources.lib import jellyfin


class FakeResponse(object):
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(body) if body is not None else ''
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FakeWindow(object):
    properties = {}

    def get_property(self, key):
        return self.properties.get(key, '')

    def set_property(self, key, value):
        self.properties[key] = value

    def clear_property(self, key):
        self.properties.pop(key, None)


@pytest.fixture
def env(monkeypatch):
    calls = {'requests': [], 'cleared': [], 'notifications': []}
    responses = []

    def fake_request(method, url, **kwargs):
        calls['requests'].append((method, url))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def create_headers(self, force=False):
        token = None if force else self.token
        auth = 'MediaBrowser Client="Kodi JellyCon"'
        if token:
            auth += ', Token="{}"'.format(token)
        self.headers = {'Authorization': auth}

    FakeWindow.properties = {'user_name': 'tester'}
    monkeypatch.setattr(jellyfin.requests, 'request', fake_request)
    monkeypatch.setattr(jellyfin.API, 'create_headers', create_headers)
    monkeypatch.setattr(jellyfin, 'HomeWindow', FakeWindow)
    monkeypatch.setattr(jellyfin, 'clear_user_details', calls['cleared'].append)
    monkeypatch.setattr(jellyfin, 'translate_string', lambda string_id: str(string_id))
    monkeypatch.setattr(jellyfin.xbmcgui.Dialog, 'notification',
                        lambda self, *args, **kwargs: calls['notifications'].append(args))

    api = jellyfin.API('http://server', 'token')
    # Keep the token in the headers, like a logged in session does
    monkeypatch.setattr(api, 'create_headers', lambda force=False: create_headers(api))
    return api, responses, calls


def test_get_returns_json_on_success(env):
    api, responses, _ = env
    responses.append(FakeResponse(200, {'Type': 'Movie'}))
    assert api.get('/Items/1') == {'Type': 'Movie'}


@pytest.mark.parametrize('response', [FakeResponse(500, {'error': 'boom'}),
                                      FakeResponse(404),
                                      requests.ConnectionError('offline')])
def test_get_returns_empty_dict_on_failure(env, response):
    api, responses, calls = env
    responses.append(response)
    assert api.get('/Items/1') == {}
    assert calls['cleared'] == []


def test_post_with_empty_body_succeeds(env):
    api, responses, _ = env
    responses.append(FakeResponse(204))
    assert api.request('POST', '/Users/u/PlayedItems/1') == (True, {})


def test_delete_reports_success(env):
    api, responses, _ = env
    responses.extend([FakeResponse(200, {'Played': False}), FakeResponse(500)])
    assert api.delete('/Users/u/PlayedItems/1') is True
    assert api.delete('/Users/u/PlayedItems/1') is False


def test_rejected_token_is_kept_and_flagged(env):
    api, responses, calls = env
    responses.append(FakeResponse(401))

    assert api.delete('/Users/u/PlayedItems/1') is False
    assert api.token_rejected
    assert api.token == 'token'
    assert calls['cleared'] == []
    assert calls['notifications'] == []
    assert FakeWindow.properties['auth_rejected'] == 'true'


def test_working_token_clears_rejected_state(env):
    api, responses, _ = env
    FakeWindow.properties.update(auth_rejected='true', auth_rejected_snoozed='true')
    responses.append(FakeResponse(200, {}))
    api.get('/Users/Me')
    assert 'auth_rejected' not in FakeWindow.properties
    assert 'auth_rejected_snoozed' not in FakeWindow.properties


@pytest.mark.parametrize('path', ['/Users/AuthenticateByName',
                                  '/Users/AuthenticateWithQuickConnect',
                                  '/QuickConnect/Initiate'])
def test_401_on_login_paths_is_no_token_rejection(env, path):
    api, responses, _ = env
    responses.append(FakeResponse(401))
    api.post(path, {})
    assert not api.token_rejected
    assert 'auth_rejected' not in FakeWindow.properties


def test_401_without_token_is_no_token_rejection(env):
    api, responses, _ = env
    api.token = None
    responses.append(FakeResponse(401))
    api.get('/Users/Public')
    assert not api.token_rejected


def test_action_with_rejected_token_asks_user(env, monkeypatch):
    api, responses, calls = env
    asked = []
    monkeypatch.setattr(api, 'resolve_unauthorized', lambda: asked.append(True))
    responses.append(FakeResponse(401))
    api.delete('/Users/u/PlayedItems/1')
    api.notify_failed(30271)
    assert asked == [True]
    assert calls['notifications'] == []


@pytest.fixture
def answers(env, monkeypatch):
    api = env[0]
    given = []
    monkeypatch.setattr(api, 'ask_unauthorized', lambda user_name: given.pop(0))
    return given


def test_relogin_drops_saved_login(env, answers, monkeypatch):
    api, _, calls = env
    from resources.lib import server_detect
    logins = []
    monkeypatch.setattr(server_detect, 'check_server', lambda **kwargs: logins.append(kwargs))
    FakeWindow.properties['auth_rejected'] = 'true'
    answers.append('relogin')

    assert api.resolve_unauthorized() == 'relogin'
    assert calls['cleared'] == ['tester']
    assert api.token is None
    assert logins == [{'change_user': True}]
    assert 'auth_rejected' not in FakeWindow.properties
    assert 'auth_dialog_open' not in FakeWindow.properties


def test_relogin_left_to_caller(env, answers, monkeypatch):
    api, _, calls = env
    from resources.lib import server_detect
    monkeypatch.setattr(server_detect, 'check_server', lambda **kwargs: pytest.fail('no login expected'))
    answers.append('relogin')
    assert api.resolve_unauthorized(relogin=False) == 'relogin'
    assert calls['cleared'] == ['tester']


def test_retry_keeps_token_until_it_works(env, answers):
    api, responses, calls = env
    answers.extend(['retry', 'retry'])
    responses.extend([FakeResponse(401), FakeResponse(200, {'Id': 'u'})])

    assert api.resolve_unauthorized() == 'ok'
    assert api.token == 'token'
    assert calls['cleared'] == []
    assert [n[1] for n in calls['notifications']] == ['30797']


def test_retry_while_server_unreachable_reports_reason(env, answers):
    api, responses, calls = env
    answers.append('retry')
    responses.append(requests.ConnectionError('offline'))
    assert api.resolve_unauthorized() == 'cancel'
    assert [n[1] for n in calls['notifications']] == ['30786']


def test_cancel_keeps_token_and_snoozes_background_prompts(env, answers):
    api, _, calls = env
    answers.append('cancel')
    assert api.resolve_unauthorized() == 'cancel'
    assert api.token == 'token'
    assert calls['cleared'] == []
    assert FakeWindow.properties['auth_rejected_snoozed'] == 'true'


def test_only_one_dialog_at_a_time(env, answers):
    api = env[0]
    FakeWindow.properties['auth_dialog_open'] = 'true'
    assert api.resolve_unauthorized() == 'cancel'


@pytest.mark.parametrize('response, reason', [
    (requests.ConnectionError('offline'), '30786'),
    (requests.exceptions.ConnectTimeout('no route'), '30786'),
    (requests.exceptions.ReadTimeout('slow'), '30787'),
    (FakeResponse(403), '30789'),
    (FakeResponse(404), '30788'),
    (FakeResponse(503), '30790'),
    (FakeResponse(400), '30791'),
])
def test_failure_reason(env, response, reason):
    api, responses, _ = env
    responses.append(response)
    api.get('/Items/1')
    # translate_string is faked to return the string id
    assert api.last_error == reason


def test_unreachable_server_is_announced_once_and_recovery_too(env):
    api, responses, calls = env
    responses.extend([requests.ConnectionError('offline')] * 3 + [FakeResponse(200, {})] * 2)

    for _ in range(3):
        api.get('/Items/1')
    assert [n[1] for n in calls['notifications']] == ['30786']

    api.get('/Items/1')
    api.get('/Items/1')
    assert [n[1] for n in calls['notifications']] == ['30786', '30792']
    assert 'server_unreachable' not in FakeWindow.properties


def test_action_failure_names_action_and_reason(env):
    api, responses, calls = env
    responses.append(FakeResponse(404))
    api.delete('/Users/u/PlayedItems/1')
    api.notify_failed(30271)
    assert [n[1] for n in calls['notifications']] == ['30785']


def test_action_failure_not_repeated_after_unreachable_notification(env):
    api, responses, calls = env
    responses.append(requests.ConnectionError('offline'))
    api.delete('/Users/u/PlayedItems/1')
    api.notify_failed(30271)
    # Only "Server not reachable", no second toast for the same problem
    assert [n[1] for n in calls['notifications']] == ['30786']


@pytest.fixture
def saved_login(monkeypatch):
    saved = []
    user_details = {'user_name': 'tester', 'user_id': 'user-id', 'token': 'token', 'password': 'secret'}
    monkeypatch.setattr(jellyfin, 'load_user_details', lambda: user_details)
    monkeypatch.setattr(jellyfin, 'save_user_details', lambda *args: saved.append(args))
    return user_details, saved


def test_rejected_token_is_renewed_with_saved_password(env, saved_login):
    api, responses, calls = env
    _, saved = saved_login
    responses.extend([FakeResponse(401),
                      FakeResponse(200, {'AccessToken': 'new', 'User': {'Id': 'user-id'}}),
                      FakeResponse(200, {'Type': 'Movie'})])

    assert api.get('/Items/1') == {'Type': 'Movie'}
    assert [url for _, url in calls['requests']] == [
        'http://server/Items/1', 'http://server/Users/AuthenticateByName', 'http://server/Items/1']
    assert saved == [('tester', 'user-id', 'new', 'secret')]
    assert not api.token_rejected
    assert 'auth_rejected' not in FakeWindow.properties


def test_rejected_token_without_saved_password_is_reported(env, saved_login):
    api, responses, calls = env
    user_details, _ = saved_login
    del user_details['password']
    responses.append(FakeResponse(401))

    assert api.get('/Items/1') == {}
    assert len(calls['requests']) == 1
    assert api.token_rejected
    assert FakeWindow.properties['auth_rejected'] == 'true'


def test_failed_renewal_is_not_repeated_right_away(env, saved_login):
    # A disabled user cannot sign in, don't try again on every request
    api, responses, calls = env
    responses.extend([FakeResponse(401), FakeResponse(401), FakeResponse(401)])

    api.get('/Items/1')
    api.get('/Items/2')

    assert [url for _, url in calls['requests']] == [
        'http://server/Items/1', 'http://server/Users/AuthenticateByName', 'http://server/Items/2']
    assert api.token_rejected
    assert FakeWindow.properties['auth_rejected'] == 'true'


def test_token_renewed_elsewhere_is_used_without_signing_in(env, saved_login):
    api, responses, calls = env
    user_details, saved = saved_login
    user_details['token'] = 'renewed-by-service'
    responses.extend([FakeResponse(401), FakeResponse(200, {'Type': 'Movie'})])

    assert api.get('/Items/1') == {'Type': 'Movie'}
    assert len(calls['requests']) == 2
    assert saved == []


def test_disabled_user_waits_for_renewal_without_asking(env, saved_login, monkeypatch):
    api, responses, calls = env
    _, saved = saved_login
    now = [1000.0]
    monkeypatch.setattr(jellyfin.time, 'time', lambda: now[0])

    # Disabled: the login is refused with 403, once announced, no dialog
    responses.extend([FakeResponse(401), FakeResponse(403)])
    assert api.get('/Items/1') == {}
    assert not api.token_rejected
    assert api.last_error == '30804'
    assert 'auth_rejected' not in FakeWindow.properties

    # Further requests don't try to sign in until the delay passed
    responses.append(FakeResponse(401))
    api.get('/Items/2')
    assert not api.token_rejected
    assert len(calls['requests']) == 3

    # Enabled again: the next attempt signs in and says so
    now[0] += jellyfin.RENEW_RETRY_DELAY
    responses.extend([FakeResponse(401),
                      FakeResponse(200, {'AccessToken': 'new', 'User': {'Id': 'user-id'}}),
                      FakeResponse(200, {'Type': 'Movie'})])
    assert api.get('/Items/3') == {'Type': 'Movie'}
    assert saved == [('tester', 'user-id', 'new', 'secret')]
    assert [n[1] for n in calls['notifications']] == ['30804', '30797']
