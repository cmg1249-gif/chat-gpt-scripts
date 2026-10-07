"""Independent TLS relay; neither user SSH credentials nor host settings needed."""
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from connection import Tunnel
from control_protocol import relay_url


def system_environment():
    env = os.environ.copy()
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    elif getattr(sys, 'frozen', False):
        env.pop('LD_LIBRARY_PATH', None)
    return env


class RelayTunnel(Tunnel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scratch = None

    def open(self):
        self.url = None
        ssh, keygen = shutil.which('ssh'), shutil.which('ssh-keygen')
        if not ssh or not keygen:
            raise OSError('Pinggy fallback requires OpenSSH client (ssh and ssh-keygen).')
        self.scratch = tempfile.TemporaryDirectory(prefix='roomcam-relay-')
        key = str(Path(self.scratch.name) / 'identity')
        # A disposable identity prevents offering any of the user's own keys.
        options = dict(env=system_environment(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        subprocess.run([keygen, '-q', '-t', 'ed25519', '-N', '', '-f', key],
                       check=True, capture_output=True, timeout=15, **options)
        known = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.cache'))) / 'RoomCam' / 'relay_known_hosts'
        known.parent.mkdir(parents=True, exist_ok=True)
        command = [ssh, '-F', 'none', '-T', '-p', '443', '-o', 'BatchMode=yes',
                   '-o', 'IdentityAgent=none', '-o', 'IdentitiesOnly=yes', '-i', key,
                   '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(known),
                   '-o', 'ConnectTimeout=12', '-o', 'ExitOnForwardFailure=yes',
                   '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
                   '-R', f'0:127.0.0.1:{self.port}', 'tls@free.pinggy.io']
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, **options)
        process = self.process
        messages = queue.Queue(maxsize=128)
        def drain():
            for line in process.stdout:
                try:
                    messages.put_nowait(line)
                except queue.Full:
                    pass
        threading.Thread(target=drain, daemon=True).start()
        recent = []
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline and not self.stop.is_set():
            try:
                line = messages.get(timeout=.2)
            except queue.Empty:
                if process.poll() is not None:
                    raise OSError('Pinggy relay exited: ' + ' | '.join(recent[-3:]))
                continue
            recent.append(line.strip())
            recent = recent[-6:]
            for match in re.finditer(r'(?:https|tls)://([a-z0-9.-]+)', line):
                url = 'https://' + match.group(1)
                if relay_url(url):
                    self.url = url
                    return url
        raise TimeoutError('Pinggy relay did not become ready: ' + ' | '.join(recent[-3:]))

    def close_process(self):
        super().close_process()
        self.url = None
        scratch, self.scratch = self.scratch, None
        if scratch:
            scratch.cleanup()


class InternetRoutes:
    """Keep independent routes available; provider failures stay isolated."""
    def __init__(self, http_port, tls_port, topic, log, advertisement, session):
        self.session = session
        self.stop = threading.Event()
        self.changed = threading.Event()
        self.routes = [
            ('Cloudflare', Tunnel(http_port, topic, None, log, advertisement, session)),
            ('Pinggy', RelayTunnel(tls_port, topic, None, log, advertisement, session)),
        ]
        self.threads = []

    @property
    def status(self):
        return ' · '.join(name + ': ' + route.status for name, route in self.routes)

    @property
    def urls(self):
        return [route.url for _, route in self.routes if route.url]

    def run(self):
        for _, route in self.routes:
            thread = threading.Thread(target=route.run, daemon=True)
            self.threads.append(thread)
            thread.start()
        while not self.stop.wait(.5):
            if self.changed.is_set():
                self.changed.clear()
                for _, route in self.routes:
                    route.changed.set()

    def close(self):
        self.stop.set()
        for _, route in self.routes:
            route.close()

    def close_process(self):
        for _, route in self.routes:
            route.close_process()
        for thread in self.threads:
            thread.join(timeout=2)
