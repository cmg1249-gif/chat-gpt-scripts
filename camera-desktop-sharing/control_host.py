"""Zero-configuration host: encrypted LAN + public tunnel, listener-owned setup."""
import atexit
import hmac
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

from flask import jsonify, request
from werkzeug.serving import make_server
from connection import Tunnel
from control_protocol import APP, PORT, Discovery, make_certificate, new_code, sign, topic_for, relay_url, connection_details
from control_terminal import Terminal

VERSION = '3.0.1-preview'


class ControlHost:
    def __init__(self, server):
        self.server = server
        self.code = new_code()
        self.terminal = Terminal()
        self.certificate = ''
        self.port = PORT
        self.lan_status = 'Starting'
        self.internet_status = 'Starting'
        self.tunnel = None
        self.started = time.monotonic()
        self.install_routes()

    def identity(self, nonce=''):
        return sign(dict(app=APP, version=VERSION, host=platform.node(), platform=platform.system(),
                         port=self.port, certificate=self.certificate, nonce=nonce,
                         created=int(time.time())), self.code)

    def advert(self, url):
        data = dict(app=APP, version=VERSION, url=url, created=int(time.time()), session=self.server.session_id)
        if relay_url(url):
            data['certificate'] = self.certificate
        return sign(data, self.code)

    def connection_details(self):
        urls = getattr(self.tunnel, 'urls', [])
        if not urls:
            return None
        return connection_details(self.code, [self.advert(url) for url in urls])

    def install_routes(self):
        app, server = self.server.app, self.server

        def protect():
            if request.path == '/control/identity':
                return None
            if request.path in ('/pair-info', '/pair'):
                code = request.headers.get('X-RoomCam-Code', '')
                if not hmac.compare_digest(code.encode(), self.code.encode()):
                    return jsonify(error='Pairing code rejected. Use the code on this host.'), 403
            # Browsers talk only to the listener's loopback gateway. All host
            # changes require a custom header and refuse cross-origin requests.
            if request.method != 'GET':
                if request.headers.get('X-RoomCam-Control') != '1' or request.headers.get('Origin'):
                    return jsonify(error='Use the RoomCam listener to control this host.'), 403
            if request.path not in ('/pair-info', '/pair') and not server.is_authorized(request.authorization):
                return jsonify(error='Pair this host from the listener first.'), 401
            return None

        # Replace the legacy first-claim pairing gate for this new entry point.
        app.before_request_funcs[None] = [protect]

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
    code = '-'.join(control.code[i:i+5] for i in range(0, len(control.code), 5))
    if headless:
        print('RoomCam sharing host ' + VERSION, flush=True)
        print('Pairing code: ' + code, flush=True)
        stop.wait()
        return
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception:
        if sys.stdout is None:
            raise RuntimeError('Cannot show the host pairing code. A graphical desktop is required.')
        print('RoomCam pairing code: ' + code, flush=True)
        stop.wait()
        return
    root.title('RoomCam · Sharing host')
    root.geometry('680x450')
    root.configure(bg='#111827')
    tk.Label(root, text='RoomCam is ready to pair', bg='#111827', fg='white', font=('Segoe UI', 20)).pack(pady=(25, 10))
    tk.Label(root, text='Enter this code in the listener. Choose the password there.', bg='#111827', fg='#aebed0').pack()
    entry = tk.Entry(root, justify='center', font=('Consolas', 17), width=36)
    entry.insert(0, code)
    entry.configure(state='readonly')
    entry.pack(pady=15)
    def copy():
        root.clipboard_clear()
        root.clipboard_append(code)
    tk.Button(root, text='Copy pairing code', command=copy).pack()
    def copy_details():
        details = control.connection_details()
        if details:
            root.clipboard_clear()
            root.clipboard_append(details)
            detail_label.configure(text='Copied. Paste into the listener code field within two minutes.')
        else:
            detail_label.configure(text='Waiting for an internet route. LAN pairing still works.')
    tk.Button(root, text='Copy fallback connection details', command=copy_details).pack(pady=(8, 0))
    detail_label = tk.Label(root, text='Use if automatic internet discovery is unavailable.', bg='#111827', fg='#aebed0')
    detail_label.pack()
    label = tk.Label(root, text='', bg='#111827', fg='#8de8c1', wraplength=580)
    label.pack(pady=15)
    def close():
        stop.set()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    tk.Button(root, text='Stop sharing and close shell', command=close).pack()
    def refresh():
        if stop.is_set():
            root.destroy()
            return
        shell = ' · SHELL ACTIVE' if control.terminal.read()['running'] else ''
        paired = 'Paired' if control.server.PASSWORD else 'Waiting for listener'
        internet = control.tunnel.status if control.tunnel else control.internet_status
        label.configure(text=f'{paired}{shell}\nLAN: {control.lan_status} · Internet: {internet}')
        root.after(1000, refresh)
    refresh()
    root.mainloop()


def run(server):
    import argparse
    parser = argparse.ArgumentParser(description='RoomCam sharing host — all setup happens in the listener')
    parser.add_argument('--headless', action='store_true', help='Show pairing code in the terminal instead of a window')
    parser.add_argument('--local', action='store_true', help='Local diagnostic mode; no tunnel or LAN discovery')
    parser.add_argument('--session-file', help=argparse.SUPPRESS)
    parser.add_argument('--stop-after', type=float, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    control = ControlHost(server)
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
                        discovery = Discovery(control.code, control.identity)
                    except OSError as exc:
                        server.log(f'Automatic LAN discovery unavailable: {exc}. Enter the host IP in the listener.')
                if lan:
                    relay_port = lan.server_port
                else:
                    relay_web = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=tls_context)
                    threading.Thread(target=relay_web.serve_forever, daemon=True).start()
                    relay_port = relay_web.server_port
                from control_relay import InternetRoutes
                control.tunnel = InternetRoutes(web.server_port, relay_port, topic_for(control.code), server.log, control.advert, server.session_id)
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
