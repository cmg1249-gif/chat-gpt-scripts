"""Start the actual Windows tray entry point, authenticate, and stop normally."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'camera-desktop-sharing'))
from control_listener import Remote
from control_owner import saved_owner_secret
from control_protocol import pinned_context

with tempfile.TemporaryDirectory(prefix='roomcam-tray-check-') as temporary:
    session = Path(temporary) / 'session.json'
    process = subprocess.Popen([str(root / 'camera-desktop-sharing/dist/webcam_server.exe'),
        '--local', '--session-file', str(session), '--stop-after', '15'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 20
        while not session.exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'Tray host exited before startup'
            time.sleep(.2)
        info = json.loads(session.read_text())
        remote = Remote(f'https://127.0.0.1:{info["port"]}', pinned_context(info['certificate']), 'Tray startup check', '', secrets.token_urlsafe(32), 'tray-test', saved_owner_secret(root / '.build'))
        remote.pair()
        status = remote.json('/status')
        assert not status['active'] and not status['mic'] and not status['desktop_audio']
        assert not remote.json('/control/status')['terminal']
        process.wait(timeout=30)
        assert process.returncode == 0, 'Native tray setup or scheduled shutdown failed'
        print('PASS actual Windows tray entry point accepts owner login, leaves capture/shell off and exits normally without headless mode')
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)
