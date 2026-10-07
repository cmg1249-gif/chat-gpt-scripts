"""Real TLS and browser gateway checks using generated media only."""
import argparse
import contextlib
import json
from pathlib import Path
import secrets
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request

from werkzeug.serving import make_server
import webcam_server as server
from check_connection import synthetic_host, read_video, read_audio
from control_host import ControlHost
from control_listener import Listener, Remote
from control_protocol import Discovery, make_certificate, pinned_context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--internet', action='store_true')
    parser.add_argument('--relay', action='store_true', help='Test Pinggy independently of Cloudflare')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output', default='.build/control-session.json')
    args = parser.parse_args()
    if args.self_test:
        import unittest
        import test_control
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_control))
        raise SystemExit(not result.wasSuccessful())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    control = ControlHost(server)
    with tempfile.TemporaryDirectory() as scratch, synthetic_host() as (origin_port, password):
        tls_context, pem = make_certificate(scratch)
        control.certificate = pem
        tls_web = make_server('127.0.0.1', 2220 if args.serve else 0, server.app, threaded=True, ssl_context=tls_context)
        control.port = tls_web.server_port
        control.lan_status = 'Ready on ' + str(control.port)
        control.internet_status = 'Synthetic local test'
        threading.Thread(target=tls_web.serve_forever, daemon=True).start()
        discovery = None
        listener_web = None
        tunnel = None
        try:
            if args.serve:
                discovery = Discovery(control.code, control.identity)
                listener = Listener()
                listener_web = make_server('127.0.0.1', 0, listener.app, threaded=True)
                listener.origin = f'http://127.0.0.1:{listener_web.server_port}'
                threading.Thread(target=listener_web.serve_forever, daemon=True).start()
                data = dict(url=listener.origin + '/#launch=' + listener.launch_token,
                            code=control.code, password=password, host_port=control.port, certificate=pem)
                if args.internet or args.relay:
                    from connection import Tunnel
                    from control_relay import RelayTunnel
                    from control_protocol import topic_for
                    tunnel = (RelayTunnel if args.relay else Tunnel)(control.port if args.relay else origin_port, topic_for(control.code), None, print, control.advert, server.session_id)
                    control.tunnel = tunnel
                    threading.Thread(target=tunnel.run, daemon=True).start()
                output.write_text(json.dumps(data), encoding='utf-8')
                print('Synthetic browser fixture ready: ' + str(output), flush=True)
                deadline = time.monotonic() + 1800
                stop_file = output.with_suffix('.stop')
                while time.monotonic() < deadline and not stop_file.exists():
                    time.sleep(.5)
                if listener.remote:
                    listener.remote.stop()
            else:
                base = f'https://127.0.0.1:{tls_web.server_port}'
                context = pinned_context(pem)
                if args.internet or args.relay:
                    from connection import Tunnel
                    from control_relay import RelayTunnel
                    from control_protocol import topic_for
                    from control_listener import find_internet
                    from tls import HTTPS_CONTEXT
                    tunnel = (RelayTunnel if args.relay else Tunnel)(control.port if args.relay else origin_port, topic_for(control.code), None, print, control.advert, server.session_id)
                    base = tunnel.open()
                    published = tunnel.publish()
                    context = pinned_context(pem) if args.relay else HTTPS_CONTEXT
                    found = find_internet(control.code, wait=15)
                    if not any(item[0] == base for item in found):
                        print('Publish diagnostic: ' + json.dumps(published), flush=True)
                        with urllib.request.urlopen(f'https://ntfy.sh/{topic_for(control.code)}/json?poll=1&since=all', context=HTTPS_CONTEXT, timeout=8) as response:
                            print('Discovery diagnostic: ' + response.read(8192).decode(), flush=True)
                        raise AssertionError('Signed internet discovery failed')
                    print('PASS signed internet discovery and ' + ('Pinggy TLS relay' if args.relay else 'registered Cloudflare tunnel'), flush=True)
                remote = Remote(base, context, 'Test connection', control.code, password)
                try:
                    Remote(base, context, 'Test', 'WRONG', password).pair()
                    raise AssertionError('Wrong pairing code accepted')
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403
                health = remote.pair()
                assert health['version'] == '3.0.1-preview'
                print('PASS verified TLS and listener-owned pairing; wrong code rejected', flush=True)
                remote.open_stream = remote.open
                remote.json('/source/select?source=camera', 'POST')
                read_video(remote)
                remote.json('/source/select?source=desktop&monitor=2', 'POST')
                read_video(remote)
                remote.json('/desktop-audio/start', 'POST')
                read_audio(remote, 997)
                # Gateway routes use the exact same authenticated remote object.
                listener = Listener()
                listener.remote = remote
                client = listener.app.test_client()
                csrf = client.post('/bootstrap', json=dict(token=listener.launch_token)).json['csrf']
                assert client.get('/remote/control/status').status_code == 200
                assert client.post('/remote/terminal').status_code == 403
                assert client.post('/remote/terminal', headers={'X-RoomCam-CSRF': csrf}).status_code == 200
                import os
                if os.name == 'nt':
                    time.sleep(.5)
                    remote.json('/terminal/input', 'POST', dict(data='\x1b[?1;2c'))
                    command = "Write-Output ('GATEWAY_' + 'SHELL_OK')\r"
                else:
                    command = "printf '%s%s\\n' GATEWAY_ SHELL_OK\r"
                time.sleep(.5)
                response = client.post('/remote/terminal/input', headers={'X-RoomCam-CSRF': csrf}, json=dict(data=command))
                assert response.status_code == 200
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    text = client.get('/remote/terminal').json['output']
                    if 'GATEWAY_SHELL_OK' in text:
                        break
                    time.sleep(.1)
                assert 'GATEWAY_SHELL_OK' in text, text
                print('PASS interactive shell through authenticated browser gateway', flush=True)
                process = control.terminal.process
                client.post('/disconnect', headers={'X-RoomCam-CSRF': csrf})
                assert not process.isalive()
                status = remote.json('/status')
                assert not status['active'] and not status['mic'] and not status['desktop_audio']
                print('PASS disconnect closes shell and all capture', flush=True)
                # A different certificate must fail even though both are local.
                if not args.internet:
                    with tempfile.TemporaryDirectory() as other:
                        _, other_pem = make_certificate(other)
                        try:
                            Remote(base, pinned_context(other_pem), 'Test', control.code, password).json('/status')
                            raise AssertionError('Wrong certificate accepted')
                        except urllib.error.URLError:
                            print('PASS wrong TLS certificate rejected', flush=True)
        finally:
            control.close()
            if tunnel:
                tunnel.close()
                tunnel.close_process()
            if discovery:
                discovery.close()
            if listener_web:
                listener_web.shutdown()
                listener_web.server_close()
            tls_web.shutdown()
            tls_web.server_close()


if __name__ == '__main__':
    main()
