"""Stop a primary server and preserve an owner-authorized shell over Pinggy."""
from pathlib import Path
import os
import secrets
import sys
import tempfile
import threading
import types
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')))
from werkzeug.serving import make_server
import webcam_server as server
from check_connection import synthetic_host
from control_host import ControlHost
from control_listener import Listener, Remote
from control_owner import owner_public, owner_topic
from control_protocol import make_certificate, pinned_context
from control_relay import RelayTunnel

# Ephemeral secret: unlike unit-test fixtures, a live internet host must never
# accept a credential that is published in source or in the diagnostic binary.
secret = secrets.token_urlsafe(32)
control = ControlHost(server, owner_public=owner_public(secret))
with tempfile.TemporaryDirectory() as scratch, synthetic_host() as (_, _):
    context, pem = make_certificate(scratch)
    control.certificate = pem
    primary = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=context)
    control.port = primary.server_port
    backup = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=context)
    for web in (primary, backup):
        threading.Thread(target=web.serve_forever, daemon=True).start()
    tunnel = RelayTunnel(backup.server_port, owner_topic(owner_public(secret)), None, print, control.advert, server.session_id)
    listener = Listener()
    client = listener.app.test_client()
    csrf = client.post('/bootstrap', json={'token': listener.launch_token}).json['csrf']
    try:
        url = tunnel.open()
        control.tunnel = types.SimpleNamespace(urls=[url], status='Pinggy test route')
        route = (url, pinned_context(pem), 'Pinggy encrypted relay')
        listener.remote = Remote(f'https://127.0.0.1:{primary.server_port}', pinned_context(pem), 'Primary test connection', '', secrets.token_urlsafe(32), 'owner-test', secret)
        listener.remote.pair()
        listener.remote.json('/terminal', 'POST')
        assert listener.remote.json('/control/status')['terminal']
        before = listener.remote.password
        listener.candidates = [route]
        primary.shutdown()
        primary.server_close()
        with patch('control_listener.find_internet', side_effect=OSError('Injected discovery outage')):
            response = client.get('/remote/control/status')
            assert response.status_code == 200, response.json
            assert response.json['terminal'], 'Route recovery closed the active shell'
            assert listener.remote.password == before
            assert client.get('/connection').json['route'] == 'Pinggy encrypted relay'
            print('PASS primary server stopped: owner-authorized reads recovered through real Pinggy while discovery was unavailable', flush=True)
            print('PASS host challenge proved the existing session; active shell and API credentials were preserved', flush=True)
            assert client.post('/disconnect', headers={'X-RoomCam-CSRF': csrf}).status_code == 200
            assert not control.terminal.read()['running']
            print('PASS fallback disconnect closed the shell and capture', flush=True)
    finally:
        if listener.remote:
            listener.remote.stop()
        control.close()
        tunnel.close()
        tunnel.close_process()
        listener.package_directory.cleanup()
        for web in (primary, backup):
            web.shutdown()
            web.server_close()
