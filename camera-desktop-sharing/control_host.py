"""Zero-configuration host: encrypted LAN + public tunnel, listener-owned setup."""
import atexit
import hmac
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse

from flask import jsonify, request
from werkzeug.serving import make_server
from connection import Tunnel
from control_protocol import APP, PORT, Discovery, make_certificate, new_code, sign, topic_for, relay_url, connection_details
from control_terminal import Terminal
from control_profiles import VERSION, read_host_profile
from control_owner import OwnerAuth, owner_topic, session_proof
from control_owner_public import OWNER_PUBLIC_KEY



class ControlHost:
    def __init__(self, server, profile=None, owner_public=None):
        self.server = server
        self.profile = profile
        self.code = profile['code'] if profile else new_code()
        self.owner_auth = OwnerAuth(owner_public, server.session_id) if owner_public else None
        if profile:
            server.PASSWORD = profile['password']
        self.terminal = Terminal()
        self.certificate = ''
        self.port = PORT
        self.lan_status = 'Starting'
        self.internet_status = 'Starting'
        self.tunnel = None
        self.started = time.monotonic()
        self.install_routes()

    def identity(self, nonce=''):
        return sign(dict(app=APP, version=VERSION, owner=self.owner_auth.public if self.owner_auth else None, host=platform.node(), platform=platform.system(),
                         port=self.port, certificate=self.certificate, nonce=nonce,
                         created=int(time.time())), self.code)

    def advert(self, url):
        data = dict(app=APP, version=VERSION, url=url, created=int(time.time()), session=self.server.session_id)
        if self.owner_auth:
            data['owner'] = self.owner_auth.public
        if relay_url(url):
            data['certificate'] = self.certificate
        return sign(data, self.code)

    def connection_details(self):
        urls = getattr(self.tunnel, 'urls', [])
        if not urls:
            return None
        return connection_details(self.code, [self.advert(url) for url in urls])

    def endpoint_allowed(self, endpoint):
        if not isinstance(endpoint, str):
            return False
        if self.tunnel and endpoint in self.tunnel.urls:
            return True
        try:
            url = urllib.parse.urlsplit(endpoint)
            if url.scheme != 'https' or url.path or url.query or url.fragment or url.username or url.password or url.port != self.port:
                return False
            ipaddress.IPv4Address(url.hostname)
            # LAN endpoints are bound to this port and this host's TLS key.
            # The viewer checks the pinned certificate before signing a login.
            # Hostname DNS is not an interface inventory (notably on Linux/WSL).
            return True
        except (ValueError, OSError, TypeError):
            return False

    def install_routes(self):
        app, server = self.server.app, self.server

        def protect():
            if request.path == '/control/identity':
                return None
            if self.owner_auth and request.path in ('/pair-info', '/pair'):
                return jsonify(error='Use your private viewer password.'), 403
            if request.path in ('/pair-info', '/pair'):
                code = request.headers.get('X-RoomCam-Code', '')
                if not hmac.compare_digest(code.encode(), self.code.encode()):
                    return jsonify(error='Pairing code rejected. Use the code on this host.'), 403
            # Browsers talk only to the listener's loopback gateway. All host
            # changes require a custom header and refuse cross-origin requests.
            if request.method != 'GET':
                if request.headers.get('X-RoomCam-Control') != '1' or request.headers.get('Origin'):
                    return jsonify(error='Use the RoomCam listener to control this host.'), 403
            public = ('/pair-info', '/pair') if not self.owner_auth else ('/owner-challenge', '/owner-auth')
            if request.path not in public and not server.is_authorized(request.authorization):
                return jsonify(error='Pair this host from the listener first.'), 401
            return None

        # Replace the legacy first-claim pairing gate for this new entry point.
        app.before_request_funcs[None] = [protect]

        @app.get('/owner-challenge')
        def owner_challenge():
            if not self.owner_auth:
                return jsonify(error='Owner login unavailable'), 404
            try:
                endpoint = request.args.get('endpoint', '')
                if not self.endpoint_allowed(endpoint):
                    return jsonify(error='This address is not a route to this host.'), 403
                challenge = self.owner_auth.challenge(endpoint, self.certificate)
                if server.PASSWORD:
                    challenge['connection_proof'] = session_proof(challenge, server.PASSWORD)
                return jsonify(challenge)
            except RuntimeError as exc:
                return jsonify(error=str(exc)), 429

        @app.post('/owner-auth')
        def owner_auth():
            if not self.owner_auth:
                return jsonify(error='Owner login unavailable'), 404
            try:
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or not self.endpoint_allowed(payload.get('endpoint')) or payload.get('certificate') != self.certificate:
                    raise ValueError('Login destination does not match this host.')
                username, password = self.owner_auth.accept(payload)
            except ValueError as exc:
                return jsonify(error=str(exc)), 403
            with server.pair_lock:
                self.terminal.close('Viewer connected')
                server.stop_camera()
                server.stop_mic()
                server.desktop_wanted = False
                server.camera_wanted = False
                server.mixer.set_desktop(False)
                server.USERNAME, server.PASSWORD = username, password
            server.log('Private owner viewer connected.')
            return jsonify(ok=True, code=self.code)

        @app.get('/control/identity')
        def identity():
            nonce = request.args.get('nonce', '')
            if not re.fullmatch('[a-f0-9]{32}', nonce):
                return jsonify(error='Invalid identity challenge'), 400
            return jsonify(self.identity(nonce))

        @app.get('/control/status', endpoint='control_status')
        def status():
            return jsonify(version=VERSION, host=platform.node(), platform=platform.system(),
                           lan=self.lan_status,
                           internet=self.tunnel.status if self.tunnel else self.internet_status,
                           uptime=int(time.monotonic() - self.started),
                           terminal=self.terminal.read(0)['running'])

        @app.route('/terminal', methods=['GET', 'POST', 'DELETE'])
        def terminal():
            try:
                if request.method == 'POST':
                    self.terminal.start()
                    server.log('Listener opened the interactive shell.')
                elif request.method == 'DELETE':
                    self.terminal.close()
                    server.log('Listener closed the interactive shell.')
                return jsonify(self.terminal.read(int(request.args.get('cursor', 0)), int(request.args.get('generation', 0))))
            except (OSError, RuntimeError, ValueError) as exc:
                return jsonify(error=str(exc)), 400

        @app.post('/terminal/input')
        def terminal_input():
            try:
                self.terminal.write((request.get_json(silent=True) or {}).get('data'))
                return jsonify(ok=True)
            except (ValueError, OSError) as exc:
                return jsonify(error=str(exc)), 400

        @app.post('/terminal/resize')
        def terminal_resize():
            try:
                body = request.get_json(silent=True) or {}
                self.terminal.resize(body.get('rows'), body.get('cols'))
                return jsonify(ok=True)
            except (ValueError, OSError) as exc:
                return jsonify(error=str(exc)), 400

    def close(self):
        self.terminal.close('Sharing host stopped')


def show_host(control, stop, headless=False):
    """Keep normal operation in the tray; never open a pairing window."""
    if headless:
        print('RoomCam sharing host ' + VERSION, flush=True)
        stop.wait()
        return
    import pystray
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (64, 64), '#172b3a')
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 12, 54, 45), outline='#65e3a0', width=4)
    draw.ellipse((24, 22, 40, 38), fill='#65e3a0')

    def close(icon, item=None):
        stop.set()
        icon.stop()

    icon = pystray.Icon('roomcam-control', image, 'RoomCam starting',
        menu=pystray.Menu(pystray.MenuItem('Stop sharing and close shell', close, default=True)))
    failures = []

    def setup(tray):
        try:
            tray.visible = True
            while not stop.is_set():
                shell = control.terminal.read()['running']
                server = control.server
                capture = (server.camera is not None or server.desktop_wanted or
                           server.mic_stream is not None or server.mixer.desktop_subscription is not None)
                state = 'SHELL ACTIVE' if shell else ('Capture active' if capture else 'Capture off')
                paired = 'Paired' if server.PASSWORD else 'Waiting for viewer'
                tray.title = f'RoomCam - {paired} - {state}'
                if stop.wait(.5):
                    break
        except Exception as exc:
            failures.append(exc)
        finally:
            stop.set()
            tray.stop()

    try:
        icon.run(setup=setup)
        if failures:
            raise RuntimeError('RoomCam could not display its tray status.') from failures[0]
    finally:
        stop.set()
        icon.stop()


def run(server):
    import argparse
    parser = argparse.ArgumentParser(description='RoomCam sharing host — all setup happens in the listener')
    parser.add_argument('--headless', action='store_true', help='Run without a tray for command-line diagnostics')
    parser.add_argument('--local', action='store_true', help='Local diagnostic mode; no tunnel or LAN discovery')
    parser.add_argument('--session-file', help=argparse.SUPPRESS)
    parser.add_argument('--stop-after', type=float, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    control = ControlHost(server, owner_public=OWNER_PUBLIC_KEY)
    stop = server.shutdown
    atexit.register(control.close)
    web = lan = relay_web = discovery = None
    with tempfile.TemporaryDirectory(prefix='roomcam-session-') as scratch:
        try:
            tls_context, control.certificate = make_certificate(scratch)
            web = make_server('127.0.0.1', 0, server.app, threaded=True)
            threading.Thread(target=web.serve_forever, daemon=True).start()
            try:
                lan = make_server('127.0.0.1' if args.local else '0.0.0.0', 0 if args.local else PORT,
                                  server.app, threaded=True, ssl_context=tls_context)
                control.port = lan.server_port
                threading.Thread(target=lan.serve_forever, daemon=True).start()
                control.lan_status = f'Ready on {control.port}'
            except (OSError, SystemExit) as exc:
                control.lan_status = f'Unavailable (port {PORT} in use)'
                server.log(f'LAN could not start: {exc}')
            if not args.local:
                if lan:
                    try:
                        discovery = Discovery(control.code, control.identity, topic=owner_topic(OWNER_PUBLIC_KEY))
                    except OSError as exc:
                        server.log(f'Automatic LAN discovery unavailable: {exc}. Enter the host IP in the listener.')
                if lan:
                    relay_port = lan.server_port
                else:
                    relay_web = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=tls_context)
                    threading.Thread(target=relay_web.serve_forever, daemon=True).start()
                    relay_port = relay_web.server_port
                from control_relay import InternetRoutes
                control.tunnel = InternetRoutes(web.server_port, relay_port, owner_topic(OWNER_PUBLIC_KEY), server.log, control.advert, server.session_id)
                server.tunnel = control.tunnel
                threading.Thread(target=control.tunnel.run, daemon=True).start()
            else:
                control.internet_status = 'Local test mode'
            if args.session_file:
                Path(args.session_file).write_text(json.dumps(dict(code=control.code, port=control.port, certificate=control.certificate,
                                                                  origin_port=web.server_port)), encoding='utf-8')
            if args.stop_after:
                threading.Timer(args.stop_after, stop.set).start()
            server.mixer.start()
            show_host(control, stop, args.headless)
        finally:
            stop.set()
            control.close()
            server.stop_camera()
            server.stop_mic()
            server.mixer.close()
            if control.tunnel:
                control.tunnel.close()
                control.tunnel.close_process()
            if discovery:
                discovery.close()
            for listener in (lan, relay_web, web):
                if listener:
                    listener.shutdown()
                    listener.server_close()
