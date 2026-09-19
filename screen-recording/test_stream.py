import base64
import io
import unittest
from unittest.mock import patch

import server
import listener
from PIL import Image


class StreamTests(unittest.TestCase):
    def setUp(self):
        server.paired = False
        server.password_hash = None
        server.started_at = server.time.time()
        server.stop_event.clear()
        self.client = server.app.test_client()

    def pair(self):
        return self.client.post('/pair', json={'token': server.pair_token, 'password': 'testing-password'})

    def auth(self):
        return {'Authorization': 'Basic ' + base64.b64encode(b'viewer:testing-password').decode()}

    def test_pair_auth_and_replay(self):
        self.assertEqual(self.client.get('/video').status_code, 401)
        self.assertEqual(self.pair().status_code, 200)
        self.assertEqual(self.client.get('/health', headers=self.auth()).status_code, 200)
        self.assertEqual(self.pair().status_code, 410)
        self.assertEqual(self.client.get('/pair-info').status_code, 410)

    def test_bad_pair_inputs(self):
        for value in ([1], 'text', {'token': 123, 'password': 'password'}, {'token': 'wrong', 'password': 'short'}):
            self.assertEqual(self.client.post('/pair', json=value).status_code, 400)
        self.assertEqual(self.client.post('/pair', json={'token': 'wrong', 'password': 'password'}).status_code, 403)
        self.assertEqual(self.client.post('/pair', json={'token': '\u2603', 'password': 'password'}).status_code, 403)

    def test_expired_pair(self):
        server.started_at -= server.PAIR_LIFETIME + 1
        self.assertEqual(self.pair().status_code, 410)

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
