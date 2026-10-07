"""Actual executable owner login, restart, live routes and optional browser fixture.

Requires the owner's private credential in .build/owner-password.txt. It is
never printed, placed on the host, or included in public verification results.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

root = Path(__file__).resolve().parents[1]
folder = root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')
suffix = '.exe' if os.name == 'nt' else '.elf'
sys.path.insert(0, str(folder))
from control_owner import saved_owner_secret, owner_public
from control_listener import Remote, find_internet
from control_profiles import VERSION
from control_protocol import pinned_context

parser = argparse.ArgumentParser()
parser.add_argument('--internet', action='store_true')
parser.add_argument('--serve')
args = parser.parse_args()
secret = saved_owner_secret(root / '.build')
assert secret, 'Private owner credential required; it is not distributed with this checker'
processes = []
options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}


def spawn(command):
    process = subprocess.Popen([str(item) for item in command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    processes.append(process)
    return process


def stop(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)


def wait_file(path, process):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        assert process.poll() is None, 'Packaged app exited before startup'
        time.sleep(.2)
    raise AssertionError('Packaged app startup timeout')


def marker(remote):
    remote.json('/terminal', 'POST')
    time.sleep(.5)
    if os.name == 'nt':
        remote.json('/terminal/input', 'POST', dict(data='\x1b[?1;2c'))
        time.sleep(.5)
    command = "Write-Output ('OWNER_SHELL_' + 'OK')\r" if os.name == 'nt' else "printf '%s%s\\n' OWNER_SHELL_ OK\r"
    remote.json('/terminal/input', 'POST', dict(data=command))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if 'OWNER_SHELL_OK' in remote.json('/terminal')['output']:
            return
        time.sleep(.1)
    raise AssertionError('Shell marker missing')


with tempfile.TemporaryDirectory(prefix='roomcam-owner-check-') as temporary:
    scratch = Path(temporary)
    saved = scratch / 'viewer-data'
    saved.mkdir(mode=0o700)
    shutil.copyfile(root / '.build/owner-password.txt', saved / 'owner-password.txt')
    os.chmod(saved / 'owner-password.txt', 0o600)
    try:
        for iteration in range(1 if args.internet or args.serve else 2):
            host_file, viewer_file = scratch / f'host-{iteration}.json', scratch / f'viewer-{iteration}.json'
            host = spawn([folder / ('dist/webcam_server' + suffix), '--headless', '--session-file', host_file, '--stop-after', '900' if args.serve else '240'])
            info = wait_file(host_file, host)
            assert info['port'] == 2220, 'LAN listener unavailable on 2220'
            viewer = spawn([folder / ('dist/viewer' + suffix), '--no-browser', '--session-file', viewer_file, '--data-dir', saved])
            session = wait_file(viewer_file, viewer)
            url, fragment = session['url'].split('#', 1)
            token = urllib.parse.parse_qs(fragment)['launch'][0]
            if args.serve:
                output = Path(args.serve)
                output.write_text(json.dumps(dict(url=session['url'])), encoding='utf-8')
                print('PASS packaged owner browser fixture ready; no credential in fixture metadata', flush=True)
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline and not output.with_suffix('.stop').exists():
                    time.sleep(.5)
                break

            client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            csrf = ''
            def api(path, method='GET', data=None):
                request = urllib.request.Request(url + path, method=method,
                    data=None if data is None else json.dumps(data).encode(),
                    headers={'Content-Type': 'application/json', 'X-RoomCam-CSRF': csrf})
                with client.open(request, timeout=110) as response:
                    return json.loads(response.read())

            csrf = api('bootstrap', 'POST', dict(token=token))['csrf']
            assert api('owner-settings') == dict(saved=True)
            try:
                api('connect', 'POST', dict(username='Connor-test', password='a-wrong-owner-password-with-enough-characters'))
                raise AssertionError('Wrong owner password accepted')
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            if args.internet:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    routes = find_internet('', owner=owner_public(secret))
                    reachable = []
                    for base, context, route in routes:
                        try:
                            candidate = Remote(base, context, route, '', secrets.token_urlsafe(32), 'Connor-test', secret)
                            health = candidate.pair()
                            if health['version'] == VERSION:
                                reachable.append((base, context, route))
                        except (OSError, ValueError, KeyError):
                            continue
                    if len({item[2] for item in reachable}) == 2:
                        break
                    time.sleep(3)
                assert len({item[2] for item in reachable}) == 2, 'Both live owner routes did not become reachable'
                for base, context, route in reachable:
                    remote = Remote(base, context, route, '', secrets.token_urlsafe(32), 'Connor-test', secret)
                    remote.pair()
                    marker(remote)
                    replacement = Remote(base, context, route, remote.code, secrets.token_urlsafe(32), 'Connor-test', secret, previous_password=remote.password)
                    replacement.pair()
                    assert replacement.json('/control/status')['terminal']
                    remote.stop()
                    print('PASS first-ever owner internet login, shell and session recovery: ' + route, flush=True)

            connected = api('connect', 'POST', dict(username='Connor-test', password=secret if iteration == 0 else '', mode='internet' if args.internet else 'auto'))
            assert connected['connected'] and connected['version'] == VERSION
            if not args.internet:
                assert connected['route'] == 'Local network'
            state = api('remote/status')
            assert not state['active'] and not state['mic'] and not state['desktop_audio']
            assert not api('remote/control/status')['terminal']
            api('remote/terminal', 'POST', {})
            time.sleep(.5)
            if os.name == 'nt':
                api('remote/terminal/input', 'POST', dict(data='\x1b[?1;2c'))
                time.sleep(.5)
            command = "Write-Output ('VIEWER_OWNER_' + 'OK')\r" if os.name == 'nt' else "printf '%s%s\\n' VIEWER_OWNER_ OK\r"
            api('remote/terminal/input', 'POST', dict(data=command))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if 'VIEWER_OWNER_OK' in api('remote/terminal')['output']:
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Packaged viewer shell marker missing')
            assert api('disconnect', 'POST', {})['ok']
            assert not api('connection')['connected']
            print('PASS actual viewer username/password login, capture off, shell and disconnect: ' + connected['route'], flush=True)
            stop(viewer)
            stop(host)
        if not args.internet and not args.serve:
            print('PASS restart of both executables with viewer-only saved credential; no host settings package', flush=True)
    finally:
        for process in reversed(processes):
            stop(process)
