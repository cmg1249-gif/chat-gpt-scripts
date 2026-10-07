"""Verify a packaged viewer against an already running host of the other OS."""
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parents[1]
folder = root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')
suffix = '.exe' if os.name == 'nt' else '.elf'
expected_platform = 'Linux' if os.name == 'nt' else 'Windows'
options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
with tempfile.TemporaryDirectory(prefix='roomcam-cross-owner-') as temporary:
    scratch = Path(temporary)
    saved = scratch / 'saved'
    saved.mkdir(mode=0o700)
    shutil.copyfile(root / '.build/owner-password.txt', saved / 'owner-password.txt')
    os.chmod(saved / 'owner-password.txt', 0o600)
    session_file = scratch / 'viewer.json'
    process = subprocess.Popen([str(folder / ('dist/viewer' + suffix)), '--no-browser', '--session-file', str(session_file), '--data-dir', str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    try:
        deadline = time.monotonic() + 45
        while not session_file.exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'Packaged cross-platform viewer exited'
            time.sleep(.2)
        url, fragment = json.loads(session_file.read_text())['url'].split('#', 1)
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        csrf = ''
        def api(path, method='GET', data=None):
            request = urllib.request.Request(url + path, method=method,
                data=None if data is None else json.dumps(data).encode(),
                headers={'Content-Type': 'application/json', 'X-RoomCam-CSRF': csrf})
            with client.open(request, timeout=100) as response:
                return json.loads(response.read())
        csrf = api('bootstrap', 'POST', dict(token=urllib.parse.parse_qs(fragment)['launch'][0]))['csrf']
        connected = api('connect', 'POST', dict(username='cross-owner-test', password='', mode='internet'))
        assert connected['platform'] == expected_platform, connected
        api('remote/terminal', 'POST', {})
        time.sleep(.5)
        if expected_platform == 'Windows':
            api('remote/terminal/input', 'POST', dict(data='\x1b[?1;2c'))
            time.sleep(.5)
        command = "Write-Output ('CROSS_OWNER_' + 'OK')\r" if expected_platform == 'Windows' else "printf '%s%s\\n' CROSS_OWNER_ OK\r"
        api('remote/terminal/input', 'POST', dict(data=command))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if 'CROSS_OWNER_OK' in api('remote/terminal')['output']:
                break
            time.sleep(.1)
        else:
            raise AssertionError('Cross-platform shell marker missing')
        assert api('disconnect', 'POST', {})['ok']
        print('PASS actual ' + ('Windows' if os.name == 'nt' else 'Linux') + ' viewer -> ' + expected_platform + ' host: private owner internet login, host shell and disconnect via ' + connected['route'])
    finally:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=15)
