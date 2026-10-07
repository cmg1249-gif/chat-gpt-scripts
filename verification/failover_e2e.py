"""Kill a real primary connection and recover through the independent relay."""
from pathlib import Path
import os
import sys
import tempfile
import threading
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')))
from werkzeug.serving import make_server
import webcam_server as server
from check_connection import synthetic_host
from control_host import ControlHost
from control_listener import Listener, Remote
from control_protocol import make_certificate, pinned_context, topic_for, connection_details
from control_relay import RelayTunnel

control = ControlHost(server)
with tempfile.TemporaryDirectory() as scratch, synthetic_host() as (_, password):
    context, pem = make_certificate(scratch)
    control.certificate = pem
    primary = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=context)
    backup = make_server('127.0.0.1', 0, server.app, threaded=True, ssl_context=context)
    for web in (primary, backup):
        threading.Thread(target=web.serve_forever, daemon=True).start()
    tunnel = RelayTunnel(backup.server_port, topic_for(control.code), None, print, control.advert, server.session_id)
    listener = Listener()
    client = listener.app.test_client()
    csrf = client.post('/bootstrap', json={'token': listener.launch_token}).json['csrf']
    try:
        url = tunnel.open()
        route = (url, pinned_context(pem), 'Pinggy encrypted relay')
        listener.remote = Remote(f'https://127.0.0.1:{primary.server_port}', pinned_context(pem), 'Primary test connection', control.code, password)
        listener.remote.pair()
        listener.candidates = [route]
        assert client.get('/remote/control/status').status_code == 200
        primary.shutdown()
        primary.server_close()
        with patch('control_listener.find_internet', side_effect=OSError('Injected discovery outage')):
            response = client.get('/remote/control/status')
            assert response.status_code == 200, response.json
            assert client.get('/connection').json['route'] == 'Pinggy encrypted relay'
            print('PASS real primary server stopped; authenticated read recovered over Pinggy while discovery was unavailable', flush=True)
            client.post('/disconnect', headers={'X-RoomCam-CSRF': csrf})
            details = connection_details(control.code, [control.advert(url)])
            response = client.post('/connect', json={'code': details, 'password': password, 'mode': 'internet'}, headers={'X-RoomCam-CSRF': csrf})
            assert response.status_code == 200, response.json
            print('PASS copied signed connection details paired over the real relay with discovery unavailable', flush=True)
    finally:
        if listener.remote:
            listener.remote.stop()
        control.close()
        tunnel.close()
        tunnel.close_process()
        for web in (primary, backup):
            web.shutdown()
            web.server_close()
