"""Opt-in live connectivity test. Only a generated test card goes over the internet."""
import io
import secrets
import threading
import time
from unittest.mock import patch

from PIL import Image, ImageDraw
import numpy as np
from werkzeug.serving import make_server
import listener
import server
from test_media import verify_audio


class SyntheticAudio:
    sample_rate = 48000
    channels = 2

    def __init__(self):
        self.position = 0
        self.closed = False

    def read(self):
        if self.closed or server.stop_event.wait(0.02):
            return b''
        times = np.arange(self.position, self.position + 960) / self.sample_rate
        self.position += 960
        samples = (1500 * np.sin(2 * np.pi * 997 * times)).astype('<i2')
        return np.repeat(samples[:, None], 2, axis=1).tobytes()

    def close(self):
        self.closed = True


def main():
    topic = 'desktop-stream-check-' + secrets.token_hex(16)
    server.NTFY_TOPIC = listener.NTFY_TOPIC = topic
    server.stop_event.clear()
    server.paired = False
    server.password_hash = None
    server.started_at = time.time()
    password = secrets.token_urlsafe(24)
    card = Image.new('RGB', (640, 360), '#174469')
    ImageDraw.Draw(card).text((30, 30), 'SCREEN STREAM CONNECTIVITY TEST - SYNTHETIC IMAGE', fill='white')
    output = io.BytesIO()
    card.save(output, 'JPEG')
    web = make_server('127.0.0.1', 0, server.app, threaded=True)
    server.PORT = web.server_port
    threading.Thread(target=web.serve_forever, daemon=True).start()
    # Bound the complete check even when discovery cannot reach its service.
    expired = threading.Event()
    timer = threading.Timer(150, expired.set)
    timer.daemon = True
    timer.start()
    original_sleep = time.sleep

    def bounded_sleep(seconds):
        if expired.is_set():
            raise RuntimeError('Internet check timed out; verify outbound internet access and retry.')
        original_sleep(seconds)

    try:
        print('Testing public tunnel and discovery with synthetic frames only.', flush=True)
        with patch.object(server, 'capture_jpeg', return_value=output.getvalue()), patch.object(server, 'LoopbackCapture', SyntheticAudio), patch.object(listener.time, 'sleep', side_effect=bounded_sleep):
            for iteration in range(2):
                url = server.open_tunnel()
                # A new Quick Tunnel hostname can need time for DNS/edge readiness.
                deadline = time.monotonic() + 60
                while True:
                    try:
                        if iteration:
                            listener.http_json(url + '/health', username=server.USERNAME, password=password)
                        else:
                            listener.http_json(url + '/pair-info')
                        break
                    except (OSError, ValueError):
                        if time.monotonic() > deadline:
                            raise
                        bounded_sleep(2)
                server.publish_rendezvous(url)
                found, token = listener.find_session(server.session_id if iteration else None, password)
                if found != url:
                    raise RuntimeError('Discovery returned an unexpected tunnel')
                if not iteration:
                    response = listener.http_json(found + '/pair', method='POST', payload={'token': token, 'password': password})
                    if not response.get('ok'):
                        raise RuntimeError('Pairing failed')
                listener.stream_video(found, password, frames=12, headless=True)
                verify_audio(found, password, expect_test_tone=True)
                print('PASS: ' + ('new tunnel rediscovered with existing credentials' if iteration else 'public discovery, pairing and 12 decoded test frames'), flush=True)
                server.close_tunnel()
        print('PASS: internet check complete; only generated video and audio were transmitted.', flush=True)
    finally:
        timer.cancel()
        server.stop_event.set()
        server.close_tunnel()
        web.shutdown()
        web.server_close()


if __name__ == '__main__':
    main()
