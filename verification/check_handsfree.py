"""Exercise viewer-generated private packages with actual shipped executables."""
import argparse
import http.cookiejar
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--internet', action='store_true')
parser.add_argument('--serve', help='Write a disposable browser test URL and wait for a .stop file')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
platform = 'windows' if os.name == 'nt' else 'linux'
folder = root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')
suffix = '.exe' if os.name == 'nt' else '.elf'
spawn_options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
processes = []


def spawn(command):
    process = subprocess.Popen([str(item) for item in command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **spawn_options)
    processes.append(process)
    return process


def stop(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)


def await_file(path, process):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        assert process.poll() is None, 'Packaged application exited before startup'
        time.sleep(.2)
    raise AssertionError('Packaged application startup timed out')


with tempfile.TemporaryDirectory(prefix='roomcam-handsfree-') as temporary:
    scratch = Path(temporary)
    try:
        for iteration in range(2):
            listener_file = scratch / ('viewer-' + str(iteration) + '.json')
            viewer = spawn([folder / ('dist/viewer' + suffix), '--no-browser', '--session-file', listener_file, '--data-dir', scratch / 'saved'])
            session = await_file(listener_file, viewer)
            url, fragment = session['url'].split('#', 1)
            token = urllib.parse.parse_qs(fragment)['launch'][0]
            client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            csrf = ''

            def api(path, method='GET', data=None):
                request = urllib.request.Request(url + path, method=method,
                    data=None if data is None else json.dumps(data).encode(),
                    headers={'Content-Type': 'application/json', 'X-RoomCam-CSRF': csrf})
                with client.open(request, timeout=100) as response:
                    return json.loads(response.read())

            csrf = api('bootstrap', 'POST', {'token': token})['csrf']
            if iteration == 0:
                profile = api('profiles', 'POST', {'name': 'Disposable package test', 'platform': platform})
                assert set(profile) == {'id', 'name', 'platform'}
                result = api('profiles/' + profile['id'] + '/package', 'POST', {})
                package = client.open(url.rstrip('/') + result['download']).read()
                host_folder = scratch / 'prepared-host'
                with zipfile.ZipFile(io.BytesIO(package)) as archive:
                    assert set(archive.namelist()) == {'webcam_server' + suffix, 'roomcam-host.json', 'START-HERE.txt'}
                    archive.extractall(host_folder)
                    # Python's extractor ignores ZIP permissions; native unzip preserves them.
                    if os.name != 'nt':
                        os.chmod(host_folder / ('webcam_server' + suffix), 0o755)
                print('PASS packaged viewer creates and downloads private host package', flush=True)
            else:
                assert api('profiles')['computers'] == [profile]
            host_file = scratch / ('host-' + str(iteration) + '.json')
            host = spawn([host_folder / ('webcam_server' + suffix), '--headless', '--session-file', host_file,
                '--stop-after', '900' if args.serve else '150'])
            await_file(host_file, host)  # Readiness only: never copy pairing data into the viewer.
            connection = api('connect', 'POST', {'profile': profile['id'], 'mode': 'lan'})
            assert connection['connected'] and connection['route'] == 'Local network'
            assert connection['version'] == '3.0.2-preview'
            state = api('remote/status')
            assert not state['active'] and not state['mic'] and not state['desktop_audio']
            assert not api('remote/control/status')['terminal']
            api('remote/terminal', 'POST', {})
            time.sleep(1)
            if os.name == 'nt':
                api('remote/terminal/input', 'POST', {'data': '\x1b[?1;2c'})
                time.sleep(.5)
            command = "Write-Output ('HANDS_FREE_' + 'OK')\r" if os.name == 'nt' else "printf '%s%s\\n' HANDS_FREE_ OK\r"
            api('remote/terminal/input', 'POST', {'data': command})
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                output = api('remote/terminal')['output']
                if 'HANDS_FREE_OK' in output:
                    break
                time.sleep(.2)
            assert 'HANDS_FREE_OK' in output, 'Shell did not execute marker'
            api('remote/terminal', 'DELETE', {})
            assert not api('remote/control/status')['terminal']
            api('disconnect', 'POST', {})
            print('PASS ' + platform + ': saved-computer-only LAN connection, shell, capture off, disconnect' + (' after BOTH applications restart' if iteration else ''), flush=True)
            if args.internet and iteration == 0:
                connection = api('connect', 'POST', {'profile': profile['id'], 'mode': 'internet'})
                assert connection['connected'] and connection['route'] in ('Cloudflare', 'Pinggy encrypted relay')
                assert not api('remote/control/status')['terminal']
                print('PASS prepared package: saved-computer-only internet connection via ' + connection['route'], flush=True)
                api('disconnect', 'POST', {})
            if args.serve and iteration == 1:
                # A new viewer session gives the real browser its own one-use bootstrap.
                stop(viewer)
                browser_file = scratch / 'browser.json'
                viewer = spawn([folder / ('dist/viewer' + suffix), '--no-browser', '--session-file', browser_file, '--data-dir', scratch / 'saved'])
                browser_session = await_file(browser_file, viewer)
                Path(args.serve).write_text(json.dumps(browser_session))
                print('Browser fixture ready; no capture enabled', flush=True)
                deadline = time.monotonic() + 800
                while time.monotonic() < deadline and not Path(args.serve).with_suffix('.stop').exists():
                    time.sleep(.5)
            stop(host)
            stop(viewer)
    finally:
        for process in reversed(processes):
            stop(process)
