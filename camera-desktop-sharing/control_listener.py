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
from control_protocol import APP, direct_candidate, find_lan, normalize_code, topic_for, tunnel_url, verified, internet_candidate, parse_connection_details, owner_internet_candidate
from control_owner import owner_public, owner_topic, sign_login, saved_owner_secret, valid_username, session_proof
from control_owner_public import OWNER_PUBLIC_KEY
from tls import HTTPS_CONTEXT
from control_profiles import VERSION, ProfileStore, data_directory, host_binary, write_host_package


class Remote:
    def __init__(self, base, context, route, code, password, username='admin', owner_secret=None, previous_password=None):
        self.base, self.context, self.route = base, context, route
        self.code = code
        self.username, self.owner_secret = username, owner_secret
        self.auth = 'Basic ' + base64.b64encode((username + ':' + password).encode()).decode()
        self.password = password
        self.previous_password = previous_password

    def open(self, path, method='GET', data=None, pairing=False):
        headers = {'Authorization': self.auth, 'X-RoomCam-Control': '1'}
        if path.split('?', 1)[0] in ('/owner-challenge', '/owner-auth'):
            headers.pop('Authorization')
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
        if self.owner_secret:
            for attempt in range(3):
                try:
                    challenge = self.json('/owner-challenge?endpoint=' + urllib.parse.quote(self.base, safe=''))
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (502, 503, 504) or attempt == 2:
                        raise
                except urllib.error.URLError as exc:
                    if isinstance(exc.reason, ssl.SSLError) or attempt == 2:
                        raise
                time.sleep(1 + attempt)
            if challenge.get('owner') != owner_public(self.owner_secret):
                raise ValueError('Host does not accept your private connection password.')
            if challenge.get('endpoint') != self.base:
                raise ValueError('Host login belongs to a different destination.')
            if not tunnel_url(self.base):
                # LAN and Pinggy must terminate TLS at the same host that
                # decrypts this login. A forwarded challenge cannot authorize
                # a proxy holding a different TLS certificate.
                certificates = self.context.get_ca_certs(binary_form=True)
                expected = ssl.PEM_cert_to_DER_cert(challenge.get('certificate', ''))
                if len(certificates) != 1 or certificates[0] != expected:
                    raise ValueError('Login host certificate does not match this connection.')
            proof = challenge.get('connection_proof', '')
            if self.previous_password and isinstance(proof, str) and hmac.compare_digest(proof, session_proof(challenge, self.previous_password)):
                self.password = self.previous_password
                self.auth = 'Basic ' + base64.b64encode((self.username + ':' + self.password).encode()).decode()
                self.previous_password = None
                return self.json('/control/status')
            payload = sign_login(self.owner_secret, challenge, self.username, self.password)
            result = self.json('/owner-auth', 'POST', payload)
            self.code = normalize_code(result['code'])
            return self.json('/control/status')
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


def find_internet(code, wait=0, owner=None):
    deadline = time.monotonic() + wait
    while True:
        try:
            found = _internet_snapshot(code, owner) if owner else _internet_snapshot(code)
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            found = []
        if found or time.monotonic() >= deadline:
            return found
        time.sleep(3)


def _internet_snapshot(code, owner=None):
    url = f'https://ntfy.sh/{owner_topic(owner) if owner else topic_for(code)}/json?poll=1&since=2m'
    with urllib.request.urlopen(url, context=HTTPS_CONTEXT, timeout=8) as response:
        lines = response.read(262144).decode().splitlines()
    candidates = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
            data = json.loads(event.get('message', '{}'))
            item = owner_internet_candidate(data, owner) if owner else internet_candidate(data, code)
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
                candidates.extend(find_internet(previous.code, owner=owner_public(previous.owner_secret)) if previous.owner_secret else find_internet(previous.code))
            except (OSError, ValueError):
                pass
            seen = {previous.base}
            for base, context, route in candidates:
                if base in seen:
                    continue
                seen.add(base)
                # An untrusted discovery candidate must never receive an API
                # password from a different route. Every owner login rotates it.
                replacement = (Remote(base, context, route, previous.code, secrets.token_urlsafe(32), previous.username, previous.owner_secret, previous_password=previous.password)
                    if previous.owner_secret else Remote(base, context, route, previous.code, previous.password))
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
                owner_secret, owner, username = None, None, 'admin'
                if data.get('profile'):
                    profile = self.profiles.get(data['profile'])
                    code, password, supplied = profile['code'], profile['password'], []
                elif data.get('code'):
                    raw_code = data.get('code', '')
                    code, supplied = parse_connection_details(raw_code.strip() if isinstance(raw_code, str) else raw_code)
                    password = data.get('password', '')
                else:
                    username = valid_username(data.get('username', 'admin'))
                    owner_secret = data.get('password') or (saved_owner_secret(self.profiles.directory) if self.profiles.directory else None)
                    owner = owner_public(owner_secret)
                    if owner != OWNER_PUBLIC_KEY:
                        raise ValueError('That private connection password does not match this host release.')
                    code, password, supplied = '', secrets.token_urlsafe(32), []
                if not isinstance(password, str) or not 8 <= len(password) <= 128:
                    raise ValueError('Choose a password with 8–128 characters.')
                mode = data.get('mode', 'auto')
                if mode not in ('auto', 'lan', 'internet'):
                    raise ValueError('Unknown connection mode.')
                candidates, errors = [], []
                if mode != 'internet':
                    if data.get('address'):
                        try:
                            candidates.append(direct_candidate(data['address'].strip(), code, owner=owner) if owner else direct_candidate(data['address'].strip(), code))
                        except (OSError, ValueError) as exc:
                            errors.append('Direct LAN: ' + str(exc))
                    else:
                        try:
                            candidates.extend(find_lan(code, owner=owner) if owner else find_lan(code))
                        except OSError as exc:
                            errors.append('LAN discovery: ' + str(exc))
                # Prefer LAN, then discover internet only if needed.
                for stage in ('lan', 'internet'):
                    if stage == 'internet':
                        if mode == 'lan':
                            break
                        try:
                            candidates = supplied or (find_internet(code, wait=15, owner=owner) if owner else find_internet(code, wait=15))
                        except (OSError, ValueError) as exc:
                            errors.append('Internet discovery: ' + str(exc))
                            candidates = []
                    for base, context, route in candidates:
                        try:
                            remote = (Remote(base, context, route, code, secrets.token_urlsafe(32), username, owner_secret)
                                if owner_secret else Remote(base, context, route, code, password))
                            status = remote.pair()
                            if status.get('version') != VERSION:
                                raise ValueError('Incompatible host. Install the matching control-center host and listener.')
                            self.remote = remote
                            self.candidates = list(candidates)
                            self.recovery_after = 0
                            return jsonify(connected=True, route=route, host=status['host'], platform=status['platform'], version=status['version'])
                        except urllib.error.HTTPError as exc:
                            if exc.code in (401, 403):
                                errors.append('Viewer authorization was rejected. Use your private connection password.')
                            elif exc.code == 404:
                                errors.append('Incompatible host: control-center endpoint missing. Update both applications.')
                            else:
                                errors.append(f'{route}: HTTP {exc.code}')
                        except (OSError, ValueError, KeyError) as exc:
                            errors.append(route + ': ' + str(exc))
                    candidates = []
                return jsonify(error='Could not connect. Make sure webcam_server is running. ' + ' '.join(errors[-3:]),
                               hint='LAN uses port 2220. Internet routes use Cloudflare or Pinggy. The host needs no code or password entry.'), 503
            except (ValueError, OSError) as exc:
                return jsonify(error=str(exc)), 400
            finally:
                self.connect_lock.release()

        @app.get('/owner-settings')
        def owner_settings():
            try:
                secret = saved_owner_secret(self.profiles.directory) if self.profiles.directory else None
                return jsonify(saved=bool(secret and owner_public(secret) == OWNER_PUBLIC_KEY))
            except (OSError, ValueError):
                return jsonify(saved=False)

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
