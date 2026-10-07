"""Bundled tunnel lifecycle and password-authenticated rendezvous messages."""
import hmac
import json
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

from discovery import discovery_key, signature
from retry import retry_delay
from tls import HTTPS_CONTEXT
from control_protocol import tunnel_url

APP = 'roomcam-desktop-v2'


def decode_advertisement(message, password, session=None):
    try:
        data = json.loads(message)
        if data.get('app') != APP or not isinstance(data.get('session'), str):
            return None
        if session and data['session'] != session:
            return None
        url = data.get('url', '')
        if not tunnel_url(url):
            return None
        if not data.get('paired'):
            token = data.get('token')
            return data if session is None and isinstance(token, str) and len(token) >= 16 else None
        digest = signature(data, discovery_key(password, data['session']))
        if not hmac.compare_digest(digest, str(data.get('signature', ''))):
            return None
        return data
    except (ValueError, TypeError, AttributeError):
        return None


class Tunnel:
    def __init__(self, port, topic, password, log, advertisement=None, session=None):
        self.port, self.topic, self.log = port, topic, log
        self.session = session or secrets.token_urlsafe(16)
        self.key = discovery_key(password, self.session) if password else None
        self.advertisement = advertisement
        self.changed = threading.Event()
        self.process = None
        self.stop = threading.Event()
        self.url = None
        self.status = 'Connecting'

    def open(self):
        self.url = None
        candidate = None
        registered = False
        recent = []
        binary = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'cloudflared'
        self.process = subprocess.Popen(
            [str(binary), 'tunnel', '--url', f'http://127.0.0.1:{self.port}', '--no-autoupdate'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        messages = queue.Queue(maxsize=256)
        process = self.process
        def drain():
            for line in process.stderr:
                try:
                    messages.put_nowait(line)
                except queue.Full:
                    pass
        threading.Thread(target=drain, daemon=True).start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not self.stop.is_set():
            try:
                line = messages.get(timeout=.2)
            except queue.Empty:
                if process.poll() is not None:
                    raise ConnectionError('Tunnel exited during startup: ' + (' | '.join(recent[-4:]) or 'no diagnostic output'))
                continue
            recent.append(line.strip())
            recent = recent[-8:]
            if 'ERR' in line or 'error=' in line:
                self.log('Cloudflare: ' + line.strip())
                continue
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if match and tunnel_url(match.group(0)):
                candidate = match.group(0)
            if 'Registered tunnel connection' in line:
                registered = True
            if candidate and registered:
                self.url = candidate
                return self.url
        raise TimeoutError('Tunnel did not connect within 60 seconds: ' + ' | '.join(recent[-4:]))

    def publish(self):
        if self.advertisement:
            data = self.advertisement(self.url)
        else:
            data = dict(app=APP, url=self.url, session=self.session, paired=True, created=int(time.time()))
            data['signature'] = signature(data, self.key)
        request = urllib.request.Request(f'https://ntfy.sh/{self.topic}',
                                         data=json.dumps(data).encode(), method='POST')
        with urllib.request.urlopen(request, timeout=10, context=HTTPS_CONTEXT) as response:
            if response.status != 200:
                raise ConnectionError(f'Discovery returned {response.status}')
            return json.loads(response.read(8192))

    def close_process(self):
        self.url = None
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def run(self):
        while not self.stop.is_set():
            try:
                self.open()
                next_publish = 0
                while not self.stop.is_set():
                    if self.changed.is_set():
                        self.changed.clear()
                        next_publish = 0
                    if self.process.poll() is not None:
                        raise ConnectionError('Tunnel exited; reconnecting')
                    if time.monotonic() >= next_publish:
                        try:
                            self.publish()
                            self.status = 'Ready for viewer'
                            next_publish = time.monotonic() + 30
                        except (OSError, ValueError) as exc:
                            self.status = 'Discovery retrying'
                            self.log(f'Discovery unavailable: {exc}')
                            next_publish = time.monotonic() + retry_delay(exc, default=20)
                    self.stop.wait(2)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.status = 'Connection retrying'
                self.log(f'Connection unavailable: {exc}')
            finally:
                self.close_process()
            self.stop.wait(5)

    def close(self):
        self.stop.set()
