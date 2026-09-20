import base64
import io
import json
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import server
import listener
from discovery import discovery_key, signature
from PIL import Image


class StreamTests(unittest.TestCase):
    def setUp(self):
        server.paired = False
        server.password_hash = None
        server.started_at = server.time.time()
        server.stop_event.clear()
        server.tunnel_process = None
        self.client = server.app.test_client()

    def pair(self):
        return self.client.post('/pair', json={'token': server.pair_token, 'password': 'testing-password'})

    def auth(self):
        return {'Authorization': 'Basic ' + base64.b64encode(b'viewer:testing-password').decode()}

    def test_pair_auth_and_replay(self):
        self.assertEqual(self.client.get('/video').status_code, 401)
        self.assertEqual(self.pair().status_code, 200)
        self.assertEqual(self.client.get('/health', headers=self.auth()).status_code, 200)
        self.assertEqual(self.pair().status_code, 200)
        self.assertEqual(self.client.post('/pair', json={'token': server.pair_token, 'password': 'different-password'}).status_code, 410)
        self.assertEqual(self.client.get('/pair-info').status_code, 410)

    def test_bad_pair_inputs(self):
        for value in ([1], 'text', {'token': 123, 'password': 'password'}, {'token': 'wrong', 'password': 'short'}):
            self.assertEqual(self.client.post('/pair', json=value).status_code, 400)
        self.assertEqual(self.client.post('/pair', json={'token': 'wrong', 'password': 'password'}).status_code, 403)
        self.assertEqual(self.client.post('/pair', json={'token': '\u2603', 'password': 'password'}).status_code, 403)

    def test_expired_pair(self):
        server.started_at -= server.PAIR_LIFETIME + 1
        self.assertEqual(self.pair().status_code, 410)

    def test_discovery_renews_expired_token(self):
        original = server.pair_token
        server.started_at -= server.PAIR_LIFETIME + 1
        with patch.object(server, 'publish_rendezvous', side_effect=lambda url: server.stop_event.set()):
            server.rendezvous_loop('https://example.com')
        self.assertNotEqual(original, server.pair_token)
        self.assertEqual(self.pair().status_code, 200)

    def test_discovery_retries_failure(self):
        calls = []
        def publish(url):
            calls.append(url)
            if len(calls) == 1:
                raise OSError('offline')
            server.stop_event.set()
        with patch.object(server, 'publish_rendezvous', side_effect=publish), patch.object(server.stop_event, 'wait'):
            server.rendezvous_loop('https://example.com')
        self.assertEqual(len(calls), 2)

    def test_paired_advertisement_omits_token(self):
        self.pair()
        with patch.object(server.urllib.request, 'urlopen') as opened:
            opened.return_value.__enter__.return_value.status = 200
            server.publish_rendezvous('https://example.com')
        payload = json.loads(opened.call_args.args[0].data)
        self.assertNotIn('token', payload)
        self.assertTrue(payload['paired'])
        self.assertEqual(payload['session'], server.session_id)

    def test_discovery_ignores_malformed_messages_and_vm_clock(self):
        payload = {'app': 'desktop-stream-v1', 'url': 'https://example.com', 'token': 'test', 'created': 1, 'session': 'vm'}
        data = b'[]\nnot-json\n' + json.dumps({'event': 'message', 'message': json.dumps(payload)}).encode() + b'\n'
        with patch.object(listener.urllib.request, 'urlopen', return_value=io.BytesIO(data)), patch.object(listener, 'http_json', return_value={'pairing': True}):
            self.assertEqual(listener.find_session(), ('https://example.com', 'test'))

    def test_discovery_retries_network_failure(self):
        payload = {'app': 'desktop-stream-v1', 'url': 'https://example.com', 'token': 'test'}
        data = json.dumps({'event': 'message', 'message': json.dumps(payload)}).encode() + b'\n'
        with patch.object(listener.urllib.request, 'urlopen', side_effect=[OSError('offline'), io.BytesIO(data)]), patch.object(listener, 'http_json', return_value={'pairing': True}), patch.object(listener.time, 'sleep'):
            self.assertEqual(listener.find_session(), ('https://example.com', 'test'))

    def test_reconnect_only_uses_original_session(self):
        def advertisement(session, url):
            payload = {'app': 'desktop-stream-v1', 'session': session, 'url': url, 'paired': True}
            payload['signature'] = signature(payload, discovery_key('testing-password', session))
            return json.dumps({'event': 'message', 'message': json.dumps(payload)}).encode() + b'\n'
        data = advertisement('mine', 'https://mine.example') + advertisement('other', 'https://other.example')
        with patch.object(listener.urllib.request, 'urlopen', return_value=io.BytesIO(data)), patch.object(listener, 'http_json', return_value={'ok': True, 'session': 'mine'}):
            self.assertEqual(listener.find_session('mine', 'testing-password'), ('https://mine.example', None))

    def test_reconnect_retries_stale_tunnel(self):
        def advertisement(url):
            payload = {'app': 'desktop-stream-v1', 'session': 'mine', 'url': url, 'paired': True}
            payload['signature'] = signature(payload, discovery_key('testing-password', 'mine'))
            return json.dumps({'event': 'message', 'message': json.dumps(payload)}).encode() + b'\n'
        with patch.object(listener.urllib.request, 'urlopen', side_effect=[io.BytesIO(advertisement('https://old.example')), io.BytesIO(advertisement('https://new.example'))]), patch.object(listener, 'http_json', side_effect=[OSError('old tunnel gone'), {'ok': True, 'session': 'mine'}]), patch.object(listener.time, 'sleep'):
            self.assertEqual(listener.find_session('mine', 'testing-password'), ('https://new.example', None))

    def test_forged_reconnect_does_not_receive_password(self):
        payload = {'app': 'desktop-stream-v1', 'session': 'mine', 'url': 'https://forged.example', 'paired': True, 'signature': 'invalid'}
        data = json.dumps({'event': 'message', 'message': json.dumps(payload)}).encode() + b'\n'
        with patch.object(listener.urllib.request, 'urlopen', return_value=io.BytesIO(data)), patch.object(listener, 'http_json') as http, patch.object(listener.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                listener.find_session('mine', 'testing-password')
        http.assert_not_called()

    def test_network_worker_retries_tunnel_startup(self):
        args = SimpleNamespace(port=0, local=False, session_file=None)
        web = Mock()
        web.server_port = 8766
        def advertised(url):
            server.stop_event.set()
        with patch.object(server, 'make_server', return_value=web), patch.object(server, 'open_tunnel', side_effect=[OSError('offline'), 'https://example.com']) as opened, patch.object(server, 'rendezvous_loop', side_effect=advertised), patch.object(server, 'close_tunnel'), patch.object(server.stop_event, 'wait'):
            server.start_network(args)
        self.assertEqual(opened.call_count, 2)

    def test_dead_tunnel_triggers_recreation(self):
        server.tunnel_process = Mock()
        server.tunnel_process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'rebuilding tunnel'):
            server.rendezvous_loop('https://example.com')

    def test_paired_server_keeps_advertising(self):
        self.pair()
        with patch.object(server, 'publish_rendezvous', side_effect=lambda url: server.stop_event.set()) as published:
            server.rendezvous_loop('https://example.com')
        published.assert_called_once()

    def test_wrong_password(self):
        self.pair()
        headers = {'Authorization': 'Basic ' + base64.b64encode(b'viewer:incorrect').decode()}
        self.assertEqual(self.client.get('/health', headers=headers).status_code, 401)

    def test_stream_framing_and_viewer_cleanup(self):
        self.pair()
        fixture = io.BytesIO()
        Image.new('RGB', (320, 180), 'blue').save(fixture, 'JPEG')
        with patch.object(server, 'capture_jpeg', return_value=fixture.getvalue()):
            response = self.client.get('/video', headers=self.auth(), buffered=False)
        chunk = next(iter(response.response))
        jpeg = chunk.split(b'\r\n\r\n', 1)[1][:-2]
        image = Image.open(io.BytesIO(jpeg))
        self.assertGreater(image.height, 0)
        self.assertLessEqual(image.width, server.MAX_WIDTH)
        self.assertEqual(server.active_viewers, 1)
        response.close()
        self.assertEqual(server.active_viewers, 0)

    def test_fragmented_small_frames(self):
        buf = io.BytesIO()
        Image.new('RGB', (24, 16), 'red').save(buf, 'JPEG')
        jpeg = buf.getvalue()
        data = b'--frame\r\nContent-Length: ' + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n'
        class Fragmented(io.BytesIO):
            def read1(self, n):
                return self.read(7)
        with patch.object(listener.urllib.request, 'urlopen', return_value=Fragmented(data)):
            listener.stream_video('http://127.0.0.1', 'testing-password', frames=1, headless=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
