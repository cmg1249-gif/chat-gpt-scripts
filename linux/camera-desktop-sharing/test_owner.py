"""Owner authorization and LAN-first connection regression tests."""
import copy
import json
import secrets
import threading
import time
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.datastructures import Authorization

from control_host import ControlHost
from control_listener import Listener, Remote
from control_owner import OwnerAuth, owner_public, sign_login, session_proof
from control_profiles import VERSION
from control_protocol import APP, owner_internet_candidate, new_code, make_certificate

SECRET = 'synthetic-test-owner-credential-never-used-in-releases'
PUBLIC = owner_public(SECRET)


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.auth = OwnerAuth(PUBLIC, 'test-session')
        self.password = secrets.token_urlsafe(32)

    def login(self, secret=SECRET):
        return sign_login(secret, self.auth.challenge(), 'Connor-test', self.password)

    def test_valid_owner_and_no_cleartext_credentials_on_wire(self):
        payload = self.login()
        wire = json.dumps(payload)
        self.assertNotIn(SECRET, wire)
        self.assertNotIn(self.password, wire)
        self.assertEqual(self.auth.accept(payload), ('Connor-test', self.password))

    def test_wrong_owner_rejected(self):
        with self.assertRaises(ValueError):
            self.auth.accept(self.login('another-disposable-test-secret-for-wrong-owner'))

    def test_replay_and_expiry_rejected(self):
        payload = self.login()
        self.auth.accept(payload)
        with self.assertRaises(ValueError):
            self.auth.accept(payload)
        payload = self.login()
        self.auth.pending[payload['token']] = time.monotonic() - 46
        with self.assertRaises(ValueError):
            self.auth.accept(payload)

    def test_every_signed_field_is_bound(self):
        payload = self.login()
        for field in ('app', 'operation', 'session', 'token', 'host_key', 'endpoint', 'certificate', 'viewer_key', 'nonce', 'credential'):
            changed = copy.deepcopy(payload)
            changed[field] = 'tampered'
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.auth.accept(changed)
        self.assertEqual(self.auth.accept(payload)[1], self.password)

    def test_proof_cannot_be_relayed_to_another_host(self):
        other = OwnerAuth(PUBLIC, 'test-session')
        payload = self.login()
        other.pending[payload['token']] = time.monotonic()
        with self.assertRaises(ValueError):
            other.accept(payload)

    def test_bounded_challenges(self):
        for _ in range(32):
            self.auth.challenge()
        with self.assertRaises(RuntimeError):
            self.auth.challenge()

    def test_host_requires_owner_for_shell_and_blocks_old_pairing(self):
        server = types.SimpleNamespace(app=Flask(__name__), session_id='host-test', PASSWORD=None,
            USERNAME='admin', pair_lock=threading.Lock(), log=Mock(), stop_camera=Mock(), stop_mic=Mock(),
            mixer=Mock(), desktop_wanted=False, camera_wanted=False)
        server.is_authorized = lambda auth: bool(auth and auth.username == server.USERNAME and auth.password == server.PASSWORD and server.PASSWORD)
        control = ControlHost(server, owner_public=PUBLIC)
        control.terminal = Mock()
        control.terminal.read.return_value = dict(running=False)
        client = server.app.test_client()
        self.assertEqual(client.get('/terminal').status_code, 401)
        self.assertEqual(client.get('/pair-info', headers={'X-RoomCam-Code': control.code}).status_code, 403)
        self.assertEqual(client.post('/pair', headers={'X-RoomCam-Code': control.code, 'X-RoomCam-Control': '1'}).status_code, 403)
        challenge = client.get('/owner-challenge?endpoint=https://127.0.0.1:2220').json
        signed = sign_login(SECRET, challenge, 'Connor-test', self.password)
        self.assertEqual(client.post('/owner-auth', json=signed).status_code, 403)
        headers = {'X-RoomCam-Control': '1'}
        self.assertEqual(client.post('/owner-auth', json=signed, headers=headers).status_code, 200)
        self.assertEqual(server.USERNAME, 'Connor-test')
        self.assertEqual(client.post('/owner-auth', json=signed, headers=headers).status_code, 403)
        self.assertEqual(client.get('/control/status', auth=('Connor-test', self.password)).status_code, 200)
        self.assertEqual(client.get('/control/status', auth=('admin', self.password)).status_code, 401)

    def test_host_rejects_forwarded_cloudflare_destination(self):
        server = types.SimpleNamespace(app=Flask(__name__), session_id='host-test', PASSWORD=None)
        control = ControlHost(server, owner_public=PUBLIC)
        control.tunnel = types.SimpleNamespace(urls=['https://real-host-test.trycloudflare.com'])
        client = server.app.test_client()
        endpoint = 'https://fake-host-test.trycloudflare.com'
        self.assertEqual(client.get('/owner-challenge', query_string=dict(endpoint=endpoint)).status_code, 403)
        # Even a valid owner signature for a proxy's destination is unusable on
        # the real host. The proxy cannot change this field without the key.
        challenge = control.owner_auth.challenge(endpoint, control.certificate)
        payload = sign_login(SECRET, challenge, 'user', self.password)
        self.assertEqual(client.post('/owner-auth', json=payload, headers={'X-RoomCam-Control': '1'}).status_code, 403)

    def test_lan_endpoint_does_not_depend_on_hostname_dns(self):
        server = types.SimpleNamespace(app=Flask(__name__), session_id='host-test', PASSWORD=None)
        control = ControlHost(server, owner_public=PUBLIC)
        with patch('socket.getaddrinfo', side_effect=OSError('hostname lookup unavailable')):
            self.assertTrue(control.endpoint_allowed('https://172.24.12.20:2220'))
            self.assertTrue(control.endpoint_allowed('https://127.0.0.1:2220'))
            for endpoint in ('https://172.24.12.20:2221', 'https://172.24.12.20:2220/other', 'https://host.example:2220', 'http://172.24.12.20:2220'):
                self.assertFalse(control.endpoint_allowed(endpoint))

    def test_discovery_rejects_generic_wrong_owner_and_expired_addresses(self):
        advert = dict(app=APP, owner=PUBLIC, created=int(time.time()), url='https://sample-host-test.trycloudflare.com')
        self.assertEqual(owner_internet_candidate(advert, PUBLIC)[2], 'Cloudflare')
        for change in ({'url': 'https://trycloudflare.com'}, {'url': 'https://www.trycloudflare.com'}, {'owner': 'wrong'}, {'created': 0}, {'url': 'https://sample-host-test.trycloudflare.com/path'}):
            with self.assertRaises(ValueError):
                owner_internet_candidate(dict(advert, **change), PUBLIC)


class OwnerListenerTests(unittest.TestCase):
    def setUp(self):
        self.listener = Listener()
        self.client = self.listener.app.test_client()
        self.client.post('/bootstrap', json={'token': self.listener.launch_token})
        self.headers = {'X-RoomCam-CSRF': self.listener.csrf}

    def tearDown(self):
        self.listener.package_directory.cleanup()

    def test_username_and_password_only_lan_then_internet(self):
        remote = Mock()
        remote.pair.side_effect = [OSError('LAN blocked'), dict(host='Test', platform='Linux', version=VERSION)]
        lan = [('https://127.0.0.1:2220', None, 'Local network')]
        internet = [('https://sample-host-test.trycloudflare.com', None, 'Cloudflare')]
        with patch('control_listener.OWNER_PUBLIC_KEY', PUBLIC), patch('control_listener.find_lan', return_value=lan), patch('control_listener.find_internet', return_value=internet), patch('control_listener.Remote', return_value=remote) as constructor:
            response = self.client.post('/connect', json=dict(username='Connor-test', password=SECRET), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        calls = constructor.call_args_list
        self.assertEqual([call.args[2] for call in calls], ['Local network', 'Cloudflare'])
        self.assertEqual(calls[-1].args[-2:], ('Connor-test', SECRET))
        self.assertNotEqual(calls[0].args[4], calls[1].args[4])
        self.assertNotEqual(calls[0].args[4], SECRET)

    def test_first_ever_internet_connection_does_not_require_local_pairing(self):
        remote = Mock()
        remote.pair.return_value = dict(host='Test', platform='Windows', version=VERSION)
        with patch('control_listener.OWNER_PUBLIC_KEY', PUBLIC), patch('control_listener.find_lan', return_value=[]), patch('control_listener.find_internet', return_value=[('https://sample-host-test.trycloudflare.com', None, 'Cloudflare')]), patch('control_listener.Remote', return_value=remote):
            response = self.client.post('/connect', json=dict(username='test', password=SECRET), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)

    def test_wrong_private_secret_fails_before_discovery(self):
        with patch('control_listener.OWNER_PUBLIC_KEY', PUBLIC), patch('control_listener.find_lan') as lan:
            response = self.client.post('/connect', json=dict(username='test', password='another-test-secret-with-enough-characters'), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        lan.assert_not_called()

    def test_remote_uses_encrypted_proof_then_authenticated_status(self):
        auth = OwnerAuth(PUBLIC, 'test')
        remote = Remote('https://sample-host-test.trycloudflare.com', None, 'Test', '', self.password if hasattr(self, 'password') else secrets.token_urlsafe(32), 'user', SECRET)
        challenge = auth.challenge(remote.base)
        with patch.object(remote, 'json', side_effect=[challenge, dict(code=new_code()), dict(version=VERSION)]) as request:
            remote.pair()
        payload = request.call_args_list[1].args[2]
        self.assertEqual(auth.accept(payload), ('user', remote.password))
        self.assertNotIn(SECRET, json.dumps(payload))

    def test_route_recovery_requires_proof_before_reusing_api_password(self):
        previous = secrets.token_urlsafe(32)
        challenge = OwnerAuth(PUBLIC, 'test').challenge('https://sample-host-test.trycloudflare.com')
        challenge['connection_proof'] = session_proof(challenge, previous)
        remote = Remote('https://sample-host-test.trycloudflare.com', None, 'Test', new_code(), secrets.token_urlsafe(32), 'user', SECRET, previous_password=previous)
        with patch.object(remote, 'json', side_effect=[challenge, dict(version=VERSION)]) as request:
            remote.pair()
        self.assertEqual(remote.password, previous)
        self.assertTrue(request.call_args_list[0].args[0].startswith('/owner-challenge?endpoint='))
        self.assertEqual(request.call_args_list[1].args[0], '/control/status')

    def test_fake_recovery_endpoint_does_not_receive_previous_api_password(self):
        previous = secrets.token_urlsafe(32)
        challenge = OwnerAuth(PUBLIC, 'fake-test').challenge('https://sample-host-test.trycloudflare.com')
        challenge['connection_proof'] = 'fake'
        fresh = secrets.token_urlsafe(32)
        remote = Remote('https://sample-host-test.trycloudflare.com', None, 'Test', new_code(), fresh, 'user', SECRET, previous_password=previous)
        with patch.object(remote, 'json', side_effect=[challenge, dict(code=new_code()), dict(version=VERSION)]) as request:
            remote.pair()
        self.assertEqual(remote.password, fresh)
        self.assertNotIn(previous, json.dumps(request.call_args_list[1].args[2]))

    def test_bootstrap_requests_never_send_basic_credentials(self):
        remote = Remote('https://sample-host-test.trycloudflare.com', None, 'Test', '', secrets.token_urlsafe(32), 'user', SECRET)
        opener = Mock()
        with patch('control_listener.urllib.request.build_opener', return_value=opener):
            for path in ('/owner-challenge', '/owner-auth'):
                remote.open(path)
                self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))

    def test_forwarded_challenge_for_another_destination_is_rejected(self):
        remote = Remote('https://fake-host-test.trycloudflare.com', None, 'Test', '', secrets.token_urlsafe(32), 'user', SECRET)
        challenge = OwnerAuth(PUBLIC, 'test').challenge('https://real-host-test.trycloudflare.com')
        with patch.object(remote, 'json', return_value=challenge) as request, self.assertRaises(ValueError):
            remote.pair()
        self.assertEqual(request.call_count, 1)

    def test_forwarded_lan_challenge_requires_same_tls_certificate(self):
        context = Mock()
        context.get_ca_certs.return_value = [b'another-peer-certificate']
        remote = Remote('https://127.0.0.1:2220', context, 'Test', '', secrets.token_urlsafe(32), 'user', SECRET)
        with tempfile.TemporaryDirectory() as directory:
            _, certificate = make_certificate(directory)
            challenge = OwnerAuth(PUBLIC, 'test').challenge(remote.base, certificate)
        with patch.object(remote, 'json', return_value=challenge) as request, self.assertRaises(ValueError):
            remote.pair()
        self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
