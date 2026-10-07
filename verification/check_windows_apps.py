"""Start the actual EXEs and verify their local entry points and browser assets."""
import http.cookiejar
import json
import os
import secrets
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parents[1]
platform_dir = root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')
suffix = '.exe' if os.name == 'nt' else '.elf'
platform_name = 'Windows' if os.name == 'nt' else 'Linux'
spawn_options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
sys.path.insert(0, str(platform_dir))
from control_listener import Remote
from control_protocol import pinned_context
from control_owner import saved_owner_secret
from control_profiles import VERSION


def wait_file(path, process):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        if process.poll() is not None:
            raise AssertionError(f'{process.args[0]} exited with {process.returncode}')
        time.sleep(.2)
    raise AssertionError('Packaged app startup timed out')


processes = []
remote = None
with tempfile.TemporaryDirectory(prefix='roomcam-exe-check-') as scratch:
    try:
        scratch = Path(scratch)
        host_info, listener_info = scratch / 'host.json', scratch / 'listener.json'
        host = subprocess.Popen([str(platform_dir / ('dist/webcam_server' + suffix)), '--local', '--headless', '--session-file', str(host_info), '--stop-after', '60'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **spawn_options)
        processes.append(host)
        info = wait_file(host_info, host)
        owner_secret = saved_owner_secret(root / '.build')
        assert owner_secret, 'Private owner credential required for packaged-host verification'
        remote = Remote(f'https://127.0.0.1:{info["port"]}', pinned_context(info['certificate']), 'Local package test', '', secrets.token_urlsafe(32), 'Connor-test', owner_secret)
        health = remote.pair()
        assert health['platform'] == platform_name and health['version'] == VERSION
        remote.json('/terminal', 'POST')
        time.sleep(.5)
        if os.name == 'nt':
            remote.json('/terminal/input', 'POST', {'data': '\x1b[?1;2c'})
        time.sleep(.5)
        command = "Write-Output ('PACKAGED_HOST_' + 'OK')\r" if os.name == 'nt' else "printf '%s%s\\n' PACKAGED_HOST_ OK\r"
        remote.json('/terminal/input', 'POST', {'data': command})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            output = remote.json('/terminal')['output']
            if 'PACKAGED_HOST_OK' in output:
                break
            time.sleep(.1)
        assert 'PACKAGED_HOST_OK' in output, output
        remote.stop()
        print(f'PASS actual {platform_name} host startup, encrypted pairing, shell and cleanup', flush=True)

        viewer_data = scratch / 'profiles'
        viewer_data.mkdir(mode=0o700)
        shutil.copyfile(root / '.build/owner-password.txt', viewer_data / 'owner-password.txt')
        os.chmod(viewer_data / 'owner-password.txt', 0o600)
        listener = subprocess.Popen([str(platform_dir / ('dist/viewer' + suffix)), '--no-browser', '--session-file', str(listener_info), '--data-dir', str(viewer_data)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **spawn_options)
        processes.append(listener)
        listener_data = wait_file(listener_info, listener)
        url, fragment = listener_data['url'].split('#', 1)
        token = urllib.parse.parse_qs(fragment)['launch'][0]
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        page = browser.open(url).read().decode()
        assert 'Control center' in page
        assert 'Host code or fallback details' not in page and 'profile-form' not in page and 'Private connection password' in page
        assert "data:text/css" not in browser.open(url + 'assets/control.css').read().decode()
        for asset in ('control.js', 'control.css', 'xterm.js', 'xterm.css', 'favicon.svg'):
            assert browser.open(url + 'assets/' + asset).status == 200
        bootstrap = urllib.request.Request(url + 'bootstrap', data=json.dumps({'token': token}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        csrf = json.loads(browser.open(bootstrap).read())['csrf']
        assert json.loads(browser.open(url + 'connection').read())['connected'] is False
        settings = json.loads(browser.open(url + 'owner-settings').read())
        assert settings == dict(saved=True)
        synthetic_session = platform_dir / ('.build/cross-windows.json' if os.name == 'nt' else '.build/cross-linux.json')
        if synthetic_session.exists() and not synthetic_session.with_suffix('.stop').exists():
            fixture = json.loads(synthetic_session.read_text())
            connect = urllib.request.Request(url + 'connect', data=json.dumps(dict(code=fixture['code'], password=fixture['password'], mode='lan', address='127.0.0.1')).encode(),
                                             headers={'Content-Type': 'application/json', 'X-RoomCam-CSRF': csrf}, method='POST')
            connected = json.loads(browser.open(connect, timeout=25).read())
            assert connected['connected']
            disconnect = urllib.request.Request(url + 'disconnect', data=b'', headers={'X-RoomCam-CSRF': csrf}, method='POST')
            assert browser.open(disconnect).status == 200
            print(f'PASS actual {platform_name} viewer browser gateway pairing with synthetic host', flush=True)
        print(f'PASS actual {platform_name} viewer startup, bundled UI assets, bootstrap and authenticated status', flush=True)
    finally:
        if remote:
            remote.stop()
        for process in reversed(processes):
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
