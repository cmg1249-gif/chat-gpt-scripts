"""Loopback browser dashboard; credentials and pinned TLS stay in this process."""
import argparse
import base64
import hmac
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from flask import Flask, Response, jsonify, request, send_from_directory, send_file
from werkzeug.serving import make_server
from control_protocol import APP, direct_candidate, find_lan, normalize_code, topic_for, tunnel_url, verified, internet_candidate, parse_connection_details
from tls import HTTPS_CONTEXT
from control_profiles import VERSION, ProfileStore, data_directory, host_binary, write_host_package


class Remote:
    def __init__(self, base, context, route, code, password):
        self.base, self.context, self.route = base, context, route
        self.code = code
        self.auth = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
        self.password = password

    def open(self, path, method='GET', data=None, pairing=False):
        headers = {'Authorization': self.auth, 'X-RoomCam-Control': '1'}
        if pairing:
            headers['X-RoomCam-Code'] = self.code
        if data is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(data).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        # No redirects: never forward credentials to a different host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=self.context))
        return opener.open(req, timeout=12)

    def json(self, path, method='GET', data=None, pairing=False):
        with self.open(path, method, data, pairing) as response:
            return json.loads(response.read(1048576))

    def pair(self):
        try:
            # Retry only the read-only handshake; never replay a shell command.
            for attempt in range(3):
                try:
                    info = self.json('/pair-info', pairing=True)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (502, 503, 504) or attempt == 2:
                        raise
                except urllib.error.URLError as exc:
                    if isinstance(exc.reason, ssl.SSLError) or attempt == 2:
                        raise
                time.sleep(1 + attempt)
        except urllib.error.HTTPError as exc:
            if exc.code != 410:
                raise
            return self.json('/control/status')
        self.json('/pair', 'POST', dict(token=info['token'], password=self.password), pairing=True)
        return self.json('/control/status')

    def stop(self):
        for path, method in (('/terminal', 'DELETE'), ('/stop', 'POST'), ('/mic/stop', 'POST'), ('/desktop-audio/stop', 'POST')):
            try:
                self.json(path, method)
            except (OSError, ValueError):
                pass


def find_internet(code, wait=0):
    deadline = time.monotonic() + wait
    while True:
        try:
            found = _internet_snapshot(code)
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            found = []
        if found or time.monotonic() >= deadline:
            return found
        time.sleep(3)


def _internet_snapshot(code):
    url = f'https://ntfy.sh/{topic_for(code)}/json?poll=1&since=2m'
    with urllib.request.urlopen(url, context=HTTPS_CONTEXT, timeout=8) as response:
        lines = response.read(262144).decode().splitlines()
    candidates = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
            data = json.loads(event.get('message', '{}'))
            item = internet_candidate(data, code)
            if item[0] not in [c[0] for c in candidates]:
                candidates.append(item)
        except (ValueError, AttributeError, TypeError):
            continue
    return sorted(candidates, key=lambda item: item[2] != 'Cloudflare')[:4]


class Listener:
    def __init__(self, profile_directory=None):
        self.app = Flask(__name__)
        self.app.config['MAX_CONTENT_LENGTH'] = 16384
        self.launch_token = secrets.token_urlsafe(32)
        self.cookie = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.remote = None
        self.candidates = []
        self.recovery_after = 0
        self.connect_lock = threading.Lock()
        self.origin = ''
        self.activity = time.monotonic()
        self.profiles = ProfileStore(profile_directory)
        self.package_lock = threading.Lock()
        self.packages = {}
        self.package_directory = tempfile.TemporaryDirectory(prefix='roomcam-host-packages-')
        self.install_routes()

    def recover(self, previous):
        with self.connect_lock:
            if self.remote is not previous:
                return self.remote
            if time.monotonic() < self.recovery_after:
                return None
            self.recovery_after = time.monotonic() + 15
            candidates = list(self.candidates)
            try:
                candidates.extend(find_internet(previous.code))
            except (OSError, ValueError):
                pass
            seen = {previous.base}
            for base, context, route in candidates:
                if base in seen:
                    continue
                seen.add(base)
                replacement = Remote(base, context, route, previous.code, previous.password)
                try:
                    status = replacement.pair()
                    if status.get('version') != VERSION:
                        continue
                except (OSError, ValueError, KeyError):
                    continue
                self.remote = replacement
                self.candidates = candidates
                return replacement
            return None

    def install_routes(self):
        app = self.app
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))

        @app.before_request
        def protect():
            if self.origin and request.host_url.rstrip('/') != self.origin:
                return jsonify(error='Invalid listener address'), 403
            if request.headers.get('Origin') and request.headers['Origin'] != self.origin:
                return jsonify(error='Cross-origin request rejected'), 403
            if request.path == '/' or request.path.startswith('/assets/') or request.path == '/bootstrap':
                return None
            cookie = request.cookies.get('roomcam_listener', '')
            if not hmac.compare_digest(cookie, self.cookie):
                return jsonify(error='Open the dashboard from the listener app.'), 401
            if request.method not in ('GET', 'HEAD') and not hmac.compare_digest(request.headers.get('X-RoomCam-CSRF', ''), self.csrf):
                return jsonify(error='Invalid control token'), 403
            self.activity = time.monotonic()

        @app.after_request
        def headers(response):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
            return response

        @app.get('/')
        def index():
            return (root / 'control.html').read_text(encoding='utf-8')

        @app.get('/assets/<path:filename>')
        def assets(filename):
            return send_from_directory(root / 'assets', filename)

        @app.post('/bootstrap')
        def bootstrap():
            data = request.get_json(silent=True) or {}
            token = data.get('token', '') if isinstance(data, dict) else ''
            existing = hmac.compare_digest(request.cookies.get('roomcam_listener', ''), self.cookie)
            if not existing and (not self.launch_token or not isinstance(token, str) or not hmac.compare_digest(token, self.launch_token)):
                return jsonify(error='Reopen the dashboard using the listener app.'), 401
            self.launch_token = None
            response = jsonify(csrf=self.csrf)
            response.set_cookie('roomcam_listener', self.cookie, httponly=True, samesite='Strict')
            return response

        @app.post('/connect')
        def connect():
            if not self.connect_lock.acquire(blocking=False):
                return jsonify(error='A connection attempt is already running.'), 409
            try:
                if self.remote:
                    return jsonify(error='Disconnect the current host before pairing another.'), 409
                data = request.get_json(silent=True)
                if not isinstance(data, dict):
                    raise ValueError('Expected connection settings.')
                if data.get('profile'):
                    profile = self.profiles.get(data['profile'])
                    code, password, supplied = profile['code'], profile['password'], []
                else:
                    raw_code = data.get('code', '')
                    code, supplied = parse_connection_details(raw_code.strip() if isinstance(raw_code, str) else raw_code)
                    password = data.get('password', '')
                if not isinstance(password, str) or not 8 <= len(password) <= 128:
                    raise ValueError('Choose a password with 8–128 characters.')
                mode = data.get('mode', 'auto')
                if mode not in ('auto', 'lan', 'internet'):
                    raise ValueError('Unknown connection mode.')
                candidates, errors = [], []
                if mode != 'internet':
                    if data.get('address'):
                        try:
                            candidates.append(direct_candidate(data['address'].strip(), code))
                        except (OSError, ValueError) as exc:
                            errors.append('Direct LAN: ' + str(exc))
                    else:
                        try:
                            candidates.extend(find_lan(code))
                        except OSError as exc:
                            errors.append('LAN discovery: ' + str(exc))
                # Prefer LAN, then discover internet only if needed.
                for stage in ('lan', 'internet'):
                    if stage == 'internet':
                        if mode == 'lan':
                            break
                        try:
                            candidates = supplied or find_internet(code, wait=15)
                        except (OSError, ValueError) as exc:
                            errors.append('Internet discovery: ' + str(exc))
                            candidates = []
                    for base, context, route in candidates:
                        try:
                            remote = Remote(base, context, route, code, password)
                            status = remote.pair()
                            if status.get('version') != VERSION:
                                raise ValueError('Incompatible host. Install the matching control-center host and listener.')
                            self.remote = remote
                            self.candidates = list(candidates)
                            self.recovery_after = 0
                            return jsonify(connected=True, route=route, host=status['host'], platform=status['platform'], version=status['version'])
                        except urllib.error.HTTPError as exc:
                            if exc.code in (401, 403):
                                errors.append('Pairing code or session password was rejected. Use the matching code/password or restart the host.')
                            elif exc.code == 404:
                                errors.append('Incompatible host: control-center endpoint missing. Update both applications.')
                            else:
                                errors.append(f'{route}: HTTP {exc.code}')
                        except (OSError, ValueError, KeyError) as exc:
                            errors.append(route + ': ' + str(exc))
                    candidates = []
                return jsonify(error='Could not connect. Make sure the prepared host package is running. ' + ' '.join(errors[-3:]),
                               hint='LAN uses port 2220. Internet routes use Cloudflare or Pinggy. The host needs no code or password entry.'), 503
            except (ValueError, OSError) as exc:
                return jsonify(error=str(exc)), 400
            finally:
                self.connect_lock.release()

        @app.get('/profiles')
        def profiles():
            return jsonify(computers=self.profiles.list_public())

        @app.post('/profiles')
        def create_profile():
            try:
                body = request.get_json(silent=True) or {}
                if not isinstance(body, dict):
                    raise ValueError('Expected computer settings.')
                profile = self.profiles.create(body.get('name'), body.get('platform'), body.get('password', ''))
                return jsonify(**{key: profile[key] for key in ('id', 'name', 'platform')})
            except (OSError, ValueError) as exc:
                return jsonify(error=str(exc)), 400

        @app.post('/profiles/<profile_id>/package')
        def prepare_package(profile_id):
            if not self.package_lock.acquire(blocking=False):
                return jsonify(error='A host package is already being prepared.'), 409
            try:
                profile = self.profiles.get(profile_id)
                cache = (self.profiles.directory or Path(self.package_directory.name)) / 'host-cache'
                binary = host_binary(profile['platform'], cache)
                destination = Path(self.package_directory.name) / (profile_id + '.zip')
                write_host_package(profile, binary, destination)
                self.packages[profile_id] = destination
                return jsonify(download='/profiles/' + profile_id + '/package', filename='RoomCam-host-' + profile['platform'] + '.zip')
            except (OSError, ValueError) as exc:
                return jsonify(error='Could not prepare the host package: ' + str(exc)), 400
            finally:
                self.package_lock.release()

        @app.get('/profiles/<profile_id>/package')
        def download_package(profile_id):
            path = self.packages.get(profile_id)
            if path is None or not path.is_file():
                return jsonify(error='Prepare this computer’s host package first.'), 404
            return send_file(path, as_attachment=True, download_name='RoomCam-host.zip', mimetype='application/zip')

        @app.get('/connection')
        def connection_status():
            return jsonify(connected=self.remote is not None, route=self.remote.route if self.remote else None)

        @app.post('/disconnect')
        def disconnect():
            with self.connect_lock:
                remote, self.remote = self.remote, None
            if remote:
                remote.stop()
            return jsonify(ok=True)

        allowed = {'/status': {'GET'}, '/devices': {'GET'}, '/monitors': {'GET'}, '/logs': {'GET'},
                   '/video': {'GET'}, '/audio': {'GET'}, '/control/status': {'GET'},
                   '/source/select': {'POST'}, '/camera/select': {'POST'}, '/mic/select': {'POST'},
                   '/start': {'POST'}, '/stop': {'POST'}, '/mic/start': {'POST'}, '/mic/stop': {'POST'},
                   '/desktop-audio/start': {'POST'}, '/desktop-audio/stop': {'POST'},
                   '/terminal': {'GET', 'POST', 'DELETE'}, '/terminal/input': {'POST'}, '/terminal/resize': {'POST'}}

        @app.route('/remote/<path:path>', methods=['GET', 'POST', 'DELETE'])
        def proxy(path):
            path = '/' + path
            if request.method not in allowed.get(path, set()):
                return jsonify(error='Unknown control'), 404
            remote = self.remote
            if remote is None:
                return jsonify(error='Connect to a sharing computer first.'), 409
            suffix = ('?' + request.query_string.decode('ascii')) if request.query_string else ''
            try:
                try:
                    upstream = remote.open(path + suffix, request.method, request.get_json(silent=True))
                except urllib.error.HTTPError as exc:
                    if request.method != 'GET' or exc.code not in (502, 503, 504):
                        raise
                    replacement = self.recover(remote)
                    if replacement is None:
                        raise
                    remote = replacement
                    upstream = remote.open(path + suffix)
                except OSError:
                    if request.method != 'GET':
                        raise
                    replacement = self.recover(remote)
                    if replacement is None:
                        raise
                    remote = replacement
                    upstream = remote.open(path + suffix)
                if path in ('/video', '/audio'):
                    def stream():
                        try:
                            while self.remote is remote:
                                chunk = upstream.read1(16384)
                                if not chunk:
                                    break
                                yield chunk
                        finally:
                            upstream.close()
                    return Response(stream(), content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
                with upstream:
                    return Response(upstream.read(1048576), status=upstream.status, content_type='application/json')
            except urllib.error.HTTPError as exc:
                try:
                    error = json.loads(exc.read(4096)).get('error')
                except (ValueError, AttributeError):
                    error = None
                return jsonify(error=error or f'Host returned HTTP {exc.code}'), exc.code
            except (OSError, ValueError) as exc:
                return jsonify(error='Host connection lost: ' + str(exc)), 502


def run():
    parser = argparse.ArgumentParser(description='RoomCam browser control center')
    parser.add_argument('--no-browser', action='store_true', help='Print the local dashboard link')
    parser.add_argument('--session-file', help=argparse.SUPPRESS)
    parser.add_argument('--data-dir', help=argparse.SUPPRESS)
    args = parser.parse_args()
    listener = Listener(args.data_dir or data_directory())
    web = make_server('127.0.0.1', 0, listener.app, threaded=True)
    listener.origin = f'http://127.0.0.1:{web.server_port}'
    url = listener.origin + '/#launch=' + listener.launch_token
    if args.session_file:
        Path(args.session_file).write_text(json.dumps(dict(url=url)), encoding='utf-8')
    if not args.no_browser:
        webbrowser.open(url)
    print('RoomCam listener: ' + url, flush=True)
    print('Keep this listener running. Ctrl+C closes the connection and remote shell.', flush=True)
    try:
        web.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if listener.remote:
            listener.remote.stop()
        web.server_close()
        listener.package_directory.cleanup()


if __name__ == '__main__':
    run()
