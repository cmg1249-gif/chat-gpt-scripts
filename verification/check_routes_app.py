"""Verify the normal packaged host advertises both independent live routes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'camera-desktop-sharing'))
from control_listener import Remote, find_internet

with tempfile.TemporaryDirectory(prefix='roomcam-routes-') as directory:
    session = Path(directory) / 'session.json'
    process = subprocess.Popen([str(root / 'camera-desktop-sharing/dist/webcam_server.exe'),
        '--headless', '--session-file', str(session), '--stop-after', '60'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 45
        while not session.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError('Sharing host exited during startup')
            time.sleep(.2)
        data = json.loads(session.read_text())
        routes = []
        while time.monotonic() < deadline:
            routes = find_internet(data['code'])
            if len({item[2] for item in routes}) == 2:
                break
            time.sleep(3)
        assert len({item[2] for item in routes}) == 2, [item[2] for item in routes]
        for base, context, route in routes:
            remote = Remote(base, context, route, data['code'], 'disposable-routes-check')
            status = remote.pair()
            assert status['version'] == '3.0.2-preview'
            capture = remote.json('/status')
            assert not capture['active'] and not capture['mic'] and not capture['desktop_audio']
            assert not status['terminal']
            print('PASS normal packaged host: ' + route + '; authenticated, capture and shell remain off', flush=True)
        process.wait(timeout=75)
        assert process.returncode == 0
        print('PASS normal host closes both providers on scheduled shutdown', flush=True)
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)
