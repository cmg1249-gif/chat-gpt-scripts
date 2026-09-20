import base64
import io
import json
import ssl
import queue
import threading
import tls
import numpy as np
import desktop_audio
from viewer import audio_format
import viewer
from retry import retry_delay
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import server
import listener
from discovery import discovery_key, signature
from PIL import Image


class StreamTests(unittest.TestCase):
    def test_https_has_trust_without_windows_roots(self):
        with patch.object(ssl.SSLContext, 'load_default_certs'):
            context = tls.make_context()
        self.assertGreater(context.cert_store_stats()['x509_ca'], 50)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def setUp(self):
        server.paired = False
        server.password_hash = None
        server.started_at = server.time.time()
        server.stop_event.clear()
        server.discovery_changed.clear()
        server.tunnel_process = None
        server.audio_hub = desktop_audio.AudioHub()
        self.addCleanup(server.audio_hub.close)
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
        with patch.object(server, 'publish_rendezvous', side_effect=publish), patch.object(server.stop_event, 'wait', return_value=False):
            server.rendezvous_loop('https://example.com')
        self.assertEqual(len(calls), 2)

    def test_rate_limit_backoff(self):
        error = listener.urllib.error.HTTPError('https://example.com', 429, 'rate limited', {'Retry-After': '120'}, None)
        self.assertEqual(retry_delay(error), 120)
        error.headers = {}
        self.assertEqual(retry_delay(error), 60)

    def test_listener_honors_rate_limit_backoff(self):
        error = listener.urllib.error.HTTPError('https://example.com', 429, 'rate limited', {'Retry-After': '120'}, None)
        with patch.object(listener.urllib.request, 'urlopen', side_effect=error), patch.object(listener.time, 'sleep', side_effect=KeyboardInterrupt) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                listener.find_session()
        sleep.assert_called_once_with(120)

    def test_dead_tunnel_detected_during_publish_wait(self):
        server.tunnel_process = Mock()
        server.tunnel_process.poll.side_effect = [None, 1]
        with patch.object(server, 'publish_rendezvous'), patch.object(server.stop_event, 'wait', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'rebuilding tunnel'):
                server.rendezvous_loop('https://example.com')

    def test_paired_advertisement_omits_token(self):
        self.pair()
        with patch.object(server.urllib.request, 'urlopen') as opened:
            opened.return_value.__enter__.return_value.status = 200
            server.publish_rendezvous('https://example.com')
        payload = json.loads(opened.call_args.args[0].data)
        self.assertIs(opened.call_args.kwargs['context'], tls.HTTPS_CONTEXT)
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

    def test_media_endpoints_require_authentication(self):
        for endpoint in ('/monitors', '/audio-info', '/audio'):
            self.assertEqual(self.client.get(endpoint).status_code, 401)

    def test_monitor_list_and_invalid_selection(self):
        self.pair()
        monitors = [{'id': 1, 'name': 'First'}, {'id': 2, 'name': 'Second'}]
        with patch.object(server, 'list_monitors', return_value=monitors):
            self.assertEqual(self.client.get('/monitors', headers=self.auth()).json['monitors'], monitors)
            self.assertEqual(self.client.get('/video?monitor=abc', headers=self.auth()).status_code, 400)
            for index in (0, -1, 3):
                self.assertEqual(self.client.get(f'/video?monitor={index}', headers=self.auth()).status_code, 404)

    def test_second_monitor_is_captured(self):
        self.pair()
        fixture = io.BytesIO()
        Image.new('RGB', (32, 24), 'green').save(fixture, 'JPEG')
        displays = [{}, {'left': 0}, {'left': -1920}]
        with patch.object(server, 'list_monitors', return_value=[{'id': 1}, {'id': 2}]), patch.object(server.mss, 'MSS') as factory, patch.object(server, 'capture_jpeg', return_value=fixture.getvalue()) as capture:
            factory.return_value.__enter__.return_value.monitors = displays
            response = self.client.get('/video?monitor=2', headers=self.auth(), buffered=False)
            self.assertEqual(response.headers['X-Monitor-Id'], '2')
            capture.assert_called_with(factory.return_value.__enter__.return_value, displays[2])
            response.close()

    def test_audio_unavailable_keeps_video_service_alive(self):
        self.pair()
        with patch.object(server, 'audio_info', side_effect=desktop_audio.AudioUnavailable('No speakers')), patch.object(server, 'LoopbackCapture', side_effect=desktop_audio.AudioUnavailable('No speakers')):
            self.assertFalse(self.client.get('/audio-info', headers=self.auth()).json['available'])
            self.assertEqual(self.client.get('/audio', headers=self.auth()).status_code, 503)
        self.assertEqual(self.client.get('/health', headers=self.auth()).status_code, 200)

    def test_audio_stream_headers_and_cleanup(self):
        self.pair()
        capture = Mock(sample_rate=48000)
        capture.read.return_value = b'\x00\x01\x00\x01' * 512
        with patch.object(server, 'LoopbackCapture', return_value=capture):
            response = self.client.get('/audio', headers=self.auth(), buffered=False)
            self.assertEqual(response.headers['X-Audio-Format'], 's16le')
            self.assertEqual(response.headers['X-Audio-Channels'], '2')
            self.assertEqual(server.active_audio_viewers, 1)
            self.assertEqual(len(next(iter(response.response))), 2048)
            response.close()
        self.assertEqual(server.active_audio_viewers, 0)
        server.audio_hub.close()
        self.assertTrue(capture.close.called)

    def test_audio_reconnections_share_one_capture(self):
        capture = Mock(sample_rate=48000)
        tick = threading.Event()
        capture.read.side_effect = lambda: (tick.wait(0.005), b'pcm')[1]
        factory = Mock(return_value=capture)
        first = server.audio_hub.subscribe(factory)
        second = server.audio_hub.subscribe(factory)
        self.assertEqual(first.read(), b'pcm')
        self.assertEqual(second.read(), b'pcm')
        first.close()
        second.close()
        third = server.audio_hub.subscribe(factory)
        self.assertEqual(third.read(), b'pcm')
        third.close()
        factory.assert_called_once()
        capture.close.assert_not_called()
        server.audio_hub.close()
        capture.close.assert_called_once()

    def test_audio_hub_device_failure_can_recover(self):
        factory = Mock(side_effect=desktop_audio.AudioUnavailable('device gone'))
        with self.assertRaises(desktop_audio.AudioUnavailable):
            server.audio_hub.subscribe(factory)
        server.audio_hub.thread.join(timeout=1)
        capture = Mock(sample_rate=44100)
        tick = threading.Event()
        capture.read.side_effect = lambda: (tick.wait(0.005), b'new')[1]
        recovered = server.audio_hub.subscribe(lambda: capture)
        self.assertEqual(recovered.read(), b'new')
        recovered.close()

    def test_microphone_is_never_used_as_loopback(self):
        manager = Mock()
        manager.get_default_wasapi_loopback.return_value = {'isLoopbackDevice': False, 'maxInputChannels': 2}
        with self.assertRaises(desktop_audio.AudioUnavailable):
            desktop_audio.default_loopback(manager)
        manager.open.assert_not_called()

    def test_audio_channel_conversion(self):
        mono = np.array([1, -2, 300], dtype='<i2')
        stereo = np.frombuffer(desktop_audio.stereo_pcm(mono.tobytes(), 1), dtype='<i2').reshape(-1, 2)
        np.testing.assert_array_equal(stereo[:, 0], mono)
        np.testing.assert_array_equal(stereo[:, 1], mono)
        self.assertEqual(desktop_audio.stereo_pcm(stereo.tobytes(), 2), stereo.tobytes())
        surround = np.full((2, 6), 32000, dtype='<i2')
        mixed = np.frombuffer(desktop_audio.stereo_pcm(surround.tobytes(), 6), dtype='<i2')
        self.assertTrue(np.all(mixed == 32767))

    def test_audio_format_validation(self):
        self.assertEqual(audio_format({'X-Audio-Sample-Rate': '48000', 'X-Audio-Channels': '2', 'X-Audio-Format': 's16le'}), (48000, 2))
        for headers in ({}, {'X-Audio-Sample-Rate': '999999', 'X-Audio-Channels': '2', 'X-Audio-Format': 's16le'}):
            with self.assertRaises(ValueError):
                audio_format(headers)

    def test_muted_viewer_does_not_request_audio(self):
        instance = viewer.DesktopViewer.__new__(viewer.DesktopViewer)
        instance.password = 'testing-password'
        instance.muted = True
        instance.stop = threading.Event()
        instance.http = Mock()
        with patch.object(instance.stop, 'wait', side_effect=lambda delay: instance.stop.set()), patch.object(viewer, 'AudioOutput') as output:
            instance.audio_worker()
        instance.http.assert_not_called()
        output.assert_not_called()

    def test_viewer_audio_delivers_pcm_and_closes_on_mute(self):
        instance = viewer.DesktopViewer.__new__(viewer.DesktopViewer)
        instance.password = 'testing-password'
        instance.muted = False
        instance.stop = threading.Event()
        instance.base_url = 'https://example.com'
        instance.http = Mock(return_value={'available': True})
        instance.messages = queue.Queue()
        data = b'\x01\x00\x02\x00' * 128
        response = io.BytesIO(data)
        response.headers = {'X-Audio-Sample-Rate': '48000', 'X-Audio-Channels': '2', 'X-Audio-Format': 's16le'}
        def mute(chunk):
            instance.muted = True
            instance.stop.set()
        with patch.object(viewer.urllib.request, 'urlopen', return_value=response), patch.object(viewer, 'AudioOutput') as output:
            output.return_value.write.side_effect = mute
            instance.audio_worker()
            output.return_value.write.assert_called_once_with(data)
            output.return_value.close.assert_called_once()

    def test_audio_failure_does_not_stop_viewer(self):
        instance = viewer.DesktopViewer.__new__(viewer.DesktopViewer)
        instance.password = 'testing-password'
        instance.muted = False
        instance.stop = threading.Event()
        instance.base_url = 'https://example.com'
        instance.http = Mock(return_value={'available': False, 'error': 'No speakers'})
        instance.messages = queue.Queue()
        with patch.object(instance.stop, 'wait', side_effect=lambda delay: instance.stop.set()), patch.object(viewer, 'AudioOutput') as output:
            instance.audio_worker()
            output.assert_not_called()
        self.assertIn('No speakers', instance.messages.get_nowait()[1])

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
