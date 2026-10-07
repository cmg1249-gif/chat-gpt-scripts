import base64
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

import control_protocol as protocol
from control_listener import Listener, Remote
from control_terminal import Terminal
from connection import Tunnel


class ProtocolTests(unittest.TestCase):
    def test_relay_whitelist_and_signed_certificate(self):
        code = protocol.new_code()
        good = 'https://sample-123456.run.pinggy-free.link'
        for url in ('http://sample-123456.run.pinggy-free.link', good + '.evil.example', good + '/path',
                    'https://free.pinggy.io', 'https://dashboard.pinggy.io', 'https://user@sample-123456.free.pinggy.net'):
            self.assertFalse(protocol.relay_url(url))
        with tempfile.TemporaryDirectory() as directory:
            _, pem = protocol.make_certificate(directory)
            body = protocol.sign(dict(app=protocol.APP, created=time.time(), url=good, certificate=pem), code)
            result = protocol.internet_candidate(body, code)
            self.assertEqual(result[0], good)
            self.assertEqual(result[1].verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(result[1].cert_store_stats()['x509'], 1)
            body['certificate'] = 'changed'
            with self.assertRaises(ValueError):
                protocol.internet_candidate(body, code)

    def test_connection_details_expiry_and_tampering(self):
        code = protocol.new_code()
        body = dict(app=protocol.APP, created=time.time(), url='https://sample-host-test.trycloudflare.com')
        details = protocol.connection_details(code, [protocol.sign(body, code)])
        parsed, candidates = protocol.parse_connection_details(details)
        self.assertEqual(parsed, code)
        self.assertEqual(candidates[0][0], body['url'])
        body['created'] -= 121
        with self.assertRaises(ValueError):
            protocol.parse_connection_details(protocol.connection_details(code, [protocol.sign(body, code)]))
        with self.assertRaises(ValueError):
            protocol.parse_connection_details(protocol.connection_details(protocol.new_code(), [protocol.sign(body, code)]))
        for value in (None, 12, 'roomcam:not_base64', 'x' * 16001):
            with self.assertRaises(ValueError):
                protocol.parse_connection_details(value)

    def test_pairing_code_has_128_bits_and_normalizes(self):
        code = protocol.new_code()
        self.assertEqual(len(code), 26)
        self.assertLessEqual(len(protocol.topic_for(code)), 64)
        self.assertEqual(protocol.normalize_code(code.lower()[:5] + '-' + code[5:]), code)
        with self.assertRaises(ValueError):
            protocol.normalize_code('1234')

    def test_discovery_requires_code_freshness_and_challenge(self):
        code = protocol.new_code()
        body = dict(app=protocol.APP, created=int(time.time()), nonce='nonce', url='https://sample-host-test.trycloudflare.com')
        signed = protocol.sign(body, code)
        self.assertTrue(protocol.verified(signed, code, 'nonce'))
        self.assertFalse(protocol.verified(signed, protocol.new_code(), 'nonce'))
        self.assertFalse(protocol.verified(signed, code, 'other'))
        signed['url'] = 'https://another-host-test.trycloudflare.com'
        self.assertFalse(protocol.verified(signed, code))
        body['created'] -= 121
        self.assertFalse(protocol.verified(protocol.sign(body, code), code))

    def test_generic_and_api_addresses_rejected(self):
        for url in ('https://trycloudflare.com', 'https://api.trycloudflare.com', 'https://www.trycloudflare.com', 'https://real-host.trycloudflare.com.evil.example', 'http://real-host.trycloudflare.com'):
            self.assertFalse(protocol.tunnel_url(url), url)
        self.assertTrue(protocol.tunnel_url('https://sample-host-test.trycloudflare.com'))

    def test_ready_requires_registered_connection(self):
        lines = io.StringIO('ERR Post "https://api.trycloudflare.com/tunnel": timeout\n| https://sample-host-test.trycloudflare.com |\nINF Registered tunnel connection connIndex=0\n')
        process = Mock(stderr=lines)
        process.poll.return_value = None
        messages = []
        tunnel = Tunnel(2220, 'offline-test', None, messages.append)
        with patch('connection.subprocess.Popen', return_value=process):
            self.assertEqual(tunnel.open(), 'https://sample-host-test.trycloudflare.com')
        self.assertTrue(any('api.trycloudflare.com' in message for message in messages))
        self.assertIn('Registered', ''.join(lines.getvalue()))

    def test_failure_preserves_diagnostic_and_clears_old_url(self):
        process = Mock(stderr=io.StringIO('ERR outbound connection blocked\n'))
        process.poll.return_value = 1
        tunnel = Tunnel(2220, 'offline-test', None, lambda _: None)
        tunnel.url = 'https://old-host-test.trycloudflare.com'
        with patch('connection.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(ConnectionError, 'outbound connection blocked'):
                tunnel.open()
        self.assertIsNone(tunnel.url)

    def test_certificate_context_trusts_only_session_certificate(self):
        with tempfile.TemporaryDirectory() as directory:
            _, pem = protocol.make_certificate(directory)
            ctx = protocol.pinned_context(pem)
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(ctx.cert_store_stats()['x509'], 1)


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.listener = Listener()
        self.listener.origin = 'http://localhost'
        self.client = self.listener.app.test_client()

    def login(self):
        response = self.client.post('/bootstrap', json=dict(token=self.listener.launch_token))
        self.assertEqual(response.status_code, 200)
        self.headers = {'X-RoomCam-CSRF': response.json['csrf']}

    def test_no_auth_cannot_connect_or_read_or_open_shell(self):
        for path, method in (('/connect', 'POST'), ('/remote/terminal', 'POST'), ('/remote/status', 'GET')):
            self.assertEqual(self.client.open(path, method=method).status_code, 401)

    def test_bootstrap_secret_single_use(self):
        token = self.listener.launch_token
        self.login()
        other = self.listener.app.test_client()
        self.assertEqual(other.post('/bootstrap', json={'token': token}).status_code, 401)
        self.assertEqual(other.post('/bootstrap', json={'token': 'wrong'}).status_code, 401)

    def test_csrf_origin_and_dns_rebinding_rejected(self):
        self.login()
        self.assertEqual(self.client.post('/connect', json={}).status_code, 403)
        self.assertEqual(self.client.post('/connect', json={}, headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/connection', headers={'Host': 'evil.example'}).status_code, 403)

    def test_bad_code_returns_useful_error(self):
        self.login()
        response = self.client.post('/connect', json=dict(code='bad', password='password'), headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('26-character', response.json['error'])

    def test_local_success_does_not_require_internet_discovery(self):
        self.login()
        remote = Mock()
        remote.pair.return_value = dict(host='Test host', platform='Windows', version='3.0.3-preview')
        with patch('control_listener.find_lan', return_value=[('https://127.0.0.1:2220', None, 'Local network')]), patch('control_listener.find_internet') as internet, patch('control_listener.Remote', return_value=remote):
            result = self.client.post('/connect', json=dict(code=protocol.new_code(), password='password'), headers=self.headers)
        self.assertEqual(result.status_code, 200)
        internet.assert_not_called()

    def test_auto_falls_back_to_internet(self):
        self.login()
        remote = Mock()
        remote.pair.return_value = dict(host='Test host', platform='Linux', version='3.0.3-preview')
        with patch('control_listener.find_lan', return_value=[]), patch('control_listener.find_internet', return_value=[('https://test-host-demo.trycloudflare.com', None, 'Internet tunnel')]), patch('control_listener.Remote', return_value=remote):
            result = self.client.post('/connect', json=dict(code=protocol.new_code(), password='password'), headers=self.headers)
        self.assertEqual(result.json['route'], 'Internet tunnel')

    def test_blocked_lan_discovery_still_tries_internet(self):
        self.login()
        remote = Mock()
        remote.pair.return_value = dict(host='Test host', platform='Linux', version='3.0.3-preview')
        with patch('control_listener.find_lan', side_effect=OSError('UDP blocked')), patch('control_listener.find_internet', return_value=[('https://test-host-demo.trycloudflare.com', None, 'Cloudflare')]), patch('control_listener.Remote', return_value=remote):
            result = self.client.post('/connect', json=dict(code=protocol.new_code(), password='password'), headers=self.headers)
        self.assertEqual(result.status_code, 200)

    def test_failed_primary_uses_independent_relay(self):
        self.login()
        failed, fallback = Mock(), Mock()
        failed.pair.side_effect = urllib.error.URLError('Cloudflare unavailable')
        fallback.pair.return_value = dict(host='Test host', platform='Linux', version='3.0.3-preview')
        routes = [('https://test-host-demo.trycloudflare.com', None, 'Cloudflare'), ('https://sample-123456.run.pinggy-free.link', None, 'Pinggy encrypted relay')]
        with patch('control_listener.find_internet', return_value=routes), patch('control_listener.Remote', side_effect=[failed, fallback]):
            result = self.client.post('/connect', json=dict(code=protocol.new_code(), password='password', mode='internet'), headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['route'], 'Pinggy encrypted relay')

    def test_connection_details_bypass_discovery_service(self):
        self.login()
        code = protocol.new_code()
        details = protocol.connection_details(code, [protocol.sign(dict(app=protocol.APP, created=time.time(), url='https://sample-host-test.trycloudflare.com'), code)])
        remote = Mock()
        remote.pair.return_value = dict(host='Test host', platform='Windows', version='3.0.3-preview')
        with patch('control_listener.find_internet') as discovery, patch('control_listener.Remote', return_value=remote):
            result = self.client.post('/connect', json=dict(code=details, password='password', mode='internet'), headers=self.headers)
        self.assertEqual(result.status_code, 200)
        discovery.assert_not_called()

    def test_read_recovers_but_shell_input_is_never_replayed(self):
        self.login()
        old, replacement = Mock(), Mock()
        self.listener.remote = old
        old.open.side_effect = urllib.error.URLError('connection lost')
        response = Mock(status=200, headers={'Content-Type': 'application/json'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":true}'
        replacement.open.return_value = response
        with patch.object(self.listener, 'recover', return_value=replacement) as recover:
            self.assertEqual(self.client.get('/remote/status').status_code, 200)
            recover.assert_called_once_with(old)
            self.assertEqual(replacement.open.call_count, 1)
            recover.reset_mock()
            self.assertEqual(self.client.post('/remote/terminal/input', json={'data': 'command\r'}, headers=self.headers).status_code, 502)
            recover.assert_not_called()

    def test_recovery_keeps_code_password_and_respects_disconnect(self):
        old = Mock(base='https://old-host-test.trycloudflare.com', code=protocol.new_code(), password='session-password', owner_secret=None)
        self.listener.remote = old
        self.listener.candidates = [('https://sample-123456.run.pinggy-free.link', None, 'Pinggy encrypted relay')]
        replacement = Mock()
        replacement.pair.return_value = {'version': '3.0.3-preview'}
        with patch('control_listener.find_internet', side_effect=OSError('discovery down')), patch('control_listener.Remote', return_value=replacement) as constructor:
            self.assertIs(self.listener.recover(old), replacement)
            self.assertEqual(constructor.call_args.args[-2:], (old.code, old.password))
        self.listener.remote = None
        self.assertIsNone(self.listener.recover(old))

    def test_incompatible_host_reports_version(self):
        self.login()
        remote = Mock()
        remote.pair.return_value = dict(host='Test host', platform='Linux', version='2.0.1')
        with patch('control_listener.find_lan', return_value=[('https://127.0.0.1:2220', None, 'Local network')]), patch('control_listener.Remote', return_value=remote):
            result = self.client.post('/connect', json=dict(code=protocol.new_code(), password='password', mode='lan'), headers=self.headers)
        self.assertIn('Incompatible', result.json['error'])
        self.assertIsNone(self.listener.remote)

    def test_proxy_restricts_endpoints_and_disconnect_stops_host(self):
        self.login()
        self.listener.remote = Mock()
        remote = self.listener.remote
        self.assertEqual(self.client.get('/remote/pair-info').status_code, 404)
        self.assertEqual(self.client.get('/remote/mic/start').status_code, 404)
        response = self.client.post('/disconnect', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        remote.stop.assert_called_once()
        self.assertIsNone(self.listener.remote)


class RetryTests(unittest.TestCase):
    def test_dns_handshake_retry_does_not_repeat_pair_post(self):
        remote = Remote('https://sample-host-test.trycloudflare.com', None, 'test', 'code', 'password')
        remote.json = Mock(side_effect=[urllib.error.URLError('DNS not ready'), {'token': 'token'}, {}, {'version': 'test'}])
        with patch('control_listener.time.sleep'):
            self.assertEqual(remote.pair()['version'], 'test')
        self.assertEqual([call.args[0] for call in remote.json.call_args_list], ['/pair-info', '/pair-info', '/pair', '/control/status'])

    def test_rejected_password_and_certificate_are_not_retried(self):
        for error in (urllib.error.HTTPError('url', 403, 'denied', {}, None), urllib.error.URLError(ssl.SSLCertVerificationError('bad cert'))):
            remote = Remote('https://sample-host-test.trycloudflare.com', None, 'test', 'code', 'password')
            remote.json = Mock(side_effect=error)
            with self.assertRaises(OSError):
                remote.pair()
            remote.json.assert_called_once()

    def test_provider_failure_does_not_stop_other_provider(self):
        from control_relay import InternetRoutes
        manager = InternetRoutes(1, 2, 'test-topic', lambda _: None, lambda _: {}, 'session')
        cloud, relay = Mock(), Mock()
        done = threading.Event()
        cloud.run.side_effect = lambda: None
        relay.run.side_effect = done.set
        manager.routes = [('Cloudflare', cloud), ('Pinggy', relay)]
        thread = threading.Thread(target=manager.run)
        thread.start()
        try:
            self.assertTrue(done.wait(2))
        finally:
            manager.close()
            manager.close_process()
            thread.join(2)
        cloud.close.assert_called_once()
        relay.close.assert_called_once()


class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import webcam_server as server
        from control_host import ControlHost
        cls.server = server
        cls.original_hooks = list(server.app.before_request_funcs.get(None, []))
        # Registration must precede any real requests. Run this suite separately
        # from the legacy media tests, as documented in CONTROL-CENTER.md.
        cls.control = ControlHost(server)

    def setUp(self):
        self.server.PASSWORD = None
        self.server.pair_started = time.monotonic()
        self.server.pair_token = secrets.token_urlsafe(32)
        self.client = self.server.app.test_client()

    def pair(self):
        headers = {'X-RoomCam-Code': self.control.code, 'X-RoomCam-Control': '1'}
        token = self.client.get('/pair-info', headers=headers).json['token']
        result = self.client.post('/pair', headers=headers, json=dict(token=token, password='test-password'))
        self.assertEqual(result.status_code, 200)
        return {'Authorization': 'Basic ' + base64.b64encode(b'admin:test-password').decode(), 'X-RoomCam-Control': '1'}

    def test_unpaired_public_request_cannot_claim_shell(self):
        self.assertEqual(self.client.get('/pair-info').status_code, 403)
        self.assertEqual(self.client.post('/pair', json={'token': self.server.pair_token, 'password': 'attacker-password'}).status_code, 403)
        self.assertEqual(self.client.post('/terminal', headers={'X-RoomCam-Control': '1'}).status_code, 401)

    def test_signed_identity_contains_no_pairing_secret(self):
        nonce = secrets.token_hex(16)
        data = self.client.get('/control/identity?nonce=' + nonce).json
        self.assertTrue(protocol.verified(data, self.control.code, nonce))
        self.assertNotIn(self.control.code, json.dumps(data))
        self.assertNotIn(self.server.pair_token, json.dumps(data))

    def test_pair_then_status_and_shell_is_initially_closed(self):
        headers = self.pair()
        result = self.client.get('/control/status', headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['version'], '3.0.3-preview')
        self.assertFalse(result.json['terminal'])
        self.assertEqual(self.client.get('/control/status', headers={'Authorization': 'Basic ' + base64.b64encode(b'admin:wrong').decode()}).status_code, 401)

    def test_terminal_rejects_cross_origin_and_missing_control_header(self):
        headers = self.pair()
        self.assertEqual(self.client.post('/terminal', headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
        headers.pop('X-RoomCam-Control')
        self.assertEqual(self.client.post('/terminal', headers=headers).status_code, 403)


class ShellTests(unittest.TestCase):
    def test_real_shell_output_state_and_cleanup(self):
        terminal = Terminal()
        self.addCleanup(terminal.close)
        terminal.start()
        # ConPTY asks the terminal emulator for device attributes at startup.
        if os.name == 'nt':
            time.sleep(.5)
            terminal.write('\x1b[?1;2c')
            command = "$roomcam_test = 'ROOMCAM_' + 'SHELL_OK'; Write-Output $roomcam_test\r"
        else:
            command = "roomcam_test='ROOMCAM_'; printf '%s%s\\n' \"$roomcam_test\" 'SHELL_OK'\r"
        time.sleep(.5)
        terminal.write(command)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if 'ROOMCAM_SHELL_OK' in terminal.read()['output']:
                break
            time.sleep(.1)
        self.assertIn('ROOMCAM_SHELL_OK', terminal.read()['output'])
        terminal.write("Write-Output ($roomcam_test + '_PERSIST')\r" if os.name == 'nt' else "printf '%s%s\\n' \"$roomcam_test\" PERSIST\r")
        expected = 'ROOMCAM_SHELL_OK_PERSIST' if os.name == 'nt' else 'ROOMCAM_PERSIST'
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and expected not in terminal.read()['output']:
            time.sleep(.1)
        self.assertIn(expected, terminal.read()['output'])
        terminal.write('Start-Sleep -Seconds 20\r' if os.name == 'nt' else 'sleep 20\r')
        time.sleep(.4)
        terminal.write('\x03')
        time.sleep(.2)
        terminal.write("Write-Output ($roomcam_test + '_INTERRUPT')\r" if os.name == 'nt' else "printf '%s%s\\n' \"$roomcam_test\" INTERRUPT\r")
        expected = 'ROOMCAM_SHELL_OK_INTERRUPT' if os.name == 'nt' else 'ROOMCAM_INTERRUPT'
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and expected not in terminal.read()['output']:
            time.sleep(.1)
        self.assertIn(expected, terminal.read()['output'])
        self.assertTrue(terminal.read()['running'])
        process = terminal.process
        terminal.close()
        self.assertFalse(process.isalive())
        self.assertFalse(terminal.read()['running'])

    def test_terminal_limits_and_not_started_input(self):
        terminal = Terminal()
        with self.assertRaises(ValueError):
            terminal.write('whoami\r')
        with self.assertRaises(ValueError):
            terminal.resize(0, 100)
        with self.assertRaises(ValueError):
            terminal.write('x' * 8193)


if __name__ == '__main__':
    unittest.main(verbosity=2)
