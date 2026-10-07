"""Probe a provider using a disposable HTTP response, no camera or shell."""
import http.server
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ROOMCAM_RELAY_TEST')
    def log_message(self, *args):
        pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory(prefix='roomcam-relay-probe-') as scratch:
    key = str(Path(scratch) / 'identity')
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key], check=True)
    command = ['ssh', '-F', 'none', '-T', '-p', '443', '-o', 'BatchMode=yes',
        '-o', 'IdentityAgent=none', '-o', 'IdentitiesOnly=yes', '-i', key,
        '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(Path(scratch) / 'known_hosts'),
        '-o', 'ConnectTimeout=10', '-o', 'ExitOnForwardFailure=yes',
        '-R', f'0:127.0.0.1:{server.server_port}', 'http@free.pinggy.io']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = queue.Queue()
    def read():
        for line in process.stdout:
            lines.put(line)
    threading.Thread(target=read, daemon=True).start()
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                print(lines.get(timeout=.5).rstrip(), flush=True)
            except queue.Empty:
                if process.poll() is not None:
                    break
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
