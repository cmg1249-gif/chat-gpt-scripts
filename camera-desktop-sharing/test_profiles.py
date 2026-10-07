import io
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from flask import Flask
from control_profiles import ProfileStore, HOST_SETTINGS, read_host_profile, write_host_package, host_binary, VERSION
from control_host import ControlHost, show_host
from control_listener import Listener


class ProfileTests(unittest.TestCase):
    def test_saved_identity_survives_viewer_restart_and_public_list_has_no_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = ProfileStore(directory).create('Classroom laptop', 'windows')
            reopened = ProfileStore(directory)
            self.assertEqual(reopened.get(profile['id']), profile)
            public = json.dumps(reopened.list_public())
            self.assertNotIn(profile['code'], public)
            self.assertNotIn(profile['password'], public)

    def test_each_computer_gets_independent_identity(self):
        store = ProfileStore()
        first = store.create('First', 'windows')
        second = store.create('Second', 'linux')
        self.assertNotEqual(first['code'], second['code'])
        self.assertNotEqual(first['password'], second['password'])

    def test_rejects_invalid_settings_and_path_traversal(self):
        store = ProfileStore()
        for name, platform, password in [('', 'windows', ''), ('test', 'other', ''), ('test', 'linux', 'short'), ('line\nbreak', 'linux', '')]:
            with self.assertRaises(ValueError):
                store.create(name, platform, password)
        for profile_id in ('../secret', '/secret', None, 'not-saved'):
            with self.assertRaises(ValueError):
                store.get(profile_id)

    def test_package_includes_private_settings_and_executable_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            binary = directory / 'fixture-binary'
            binary.write_bytes(b'fixture executable contents')
            for platform, filename in [('windows', 'webcam_server.exe'), ('linux', 'webcam_server.elf')]:
                profile = ProfileStore().create('Test computer', platform)
                package = directory / (platform + '.zip')
                write_host_package(profile, binary, package)
                with zipfile.ZipFile(package) as archive:
                    self.assertEqual(archive.read(filename), binary.read_bytes())
                    self.assertEqual(json.loads(archive.read(HOST_SETTINGS)), profile)
                    self.assertEqual(archive.getinfo(filename).create_system, 3)
                    self.assertEqual((archive.getinfo(filename).external_attr >> 16) & 0o777, 0o755)
                    self.assertNotIn(profile['password'].encode(), archive.read('START-HERE.txt'))

    def test_prepared_host_loads_credentials_without_a_new_pairing_code(self):
        profile = ProfileStore().create('Prepared host', 'windows', 'viewer-chosen-password')
        server = types.SimpleNamespace(app=Flask(__name__), PASSWORD=None)
        control = ControlHost(server, profile)
        self.assertEqual(control.code, profile['code'])
        self.assertEqual(server.PASSWORD, 'viewer-chosen-password')
        self.assertFalse(control.terminal.read()['running'])

    def test_host_loads_only_its_adjacent_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / HOST_SETTINGS
            self.assertIsNone(read_host_profile(directory))
            profile = ProfileStore().create('Prepared host', 'linux')
            path.write_text(json.dumps(profile))
            self.assertEqual(read_host_profile(directory), profile)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                read_host_profile(directory)

    def test_download_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = [io.BytesIO((('0' * 64) + '  webcam_server.exe\n').encode()), io.BytesIO(b'tampered binary')]
            with patch('control_profiles.sys.frozen', True, create=True), patch('control_profiles.sys.executable', str(Path(directory) / 'viewer.exe')), patch('control_profiles.urllib.request.urlopen', side_effect=responses):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    host_binary('windows', Path(directory) / 'cache')
            self.assertFalse((Path(directory) / 'cache/webcam_server.exe').exists())


class ProfileRoutesTests(unittest.TestCase):
    def setUp(self):
        self.listener = Listener()
        self.addCleanup(self.listener.package_directory.cleanup)
        self.listener.origin = 'http://localhost'
        self.client = self.listener.app.test_client()
        csrf = self.client.post('/bootstrap', json={'token': self.listener.launch_token}).json['csrf']
        self.headers = {'X-RoomCam-CSRF': csrf}

    def test_profile_endpoints_require_browser_auth_and_csrf(self):
        other = self.listener.app.test_client()
        self.assertEqual(other.get('/profiles').status_code, 401)
        self.assertEqual(other.get('/profiles/' + 'a' * 32 + '/package').status_code, 401)
        self.assertEqual(self.client.post('/profiles', json={}).status_code, 403)
        self.assertEqual(self.client.post('/profiles/' + 'a' * 32 + '/package').status_code, 403)

    def test_viewer_can_connect_using_saved_computer_only(self):
        result = self.client.post('/profiles', json={'name': 'My computer', 'platform': 'windows'}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        profile = self.listener.profiles.get(result.json['id'])
        self.assertEqual(set(result.json), {'id', 'name', 'platform'})
        remote = Mock()
        remote.pair.return_value = {'version': VERSION, 'host': 'Test', 'platform': 'Windows'}
        with patch('control_listener.find_lan', return_value=[('https://127.0.0.1:2220', None, 'Local network')]), patch('control_listener.Remote', return_value=remote) as constructor:
            connected = self.client.post('/connect', json={'profile': profile['id'], 'mode': 'lan'}, headers=self.headers)
        self.assertEqual(connected.status_code, 200)
        self.assertEqual(constructor.call_args.args[-2:], (profile['code'], profile['password']))

    def test_private_package_requires_creation_and_authentication(self):
        profile = self.listener.profiles.create('My computer', 'windows')
        url = '/profiles/' + profile['id'] + '/package'
        self.assertEqual(self.client.get(url).status_code, 404)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'webcam_server.exe'
            binary.write_bytes(b'test fixture')
            with patch('control_listener.host_binary', return_value=binary):
                result = self.client.post(url, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            response = self.client.get(result.json['download'])
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(json.loads(archive.read(HOST_SETTINGS)), profile)
            response.close()


class TrayTests(unittest.TestCase):
    def test_tray_shows_activity_and_stops_on_host_shutdown(self):
        for shell, capture, expected in [(False, False, 'Capture off'), (False, True, 'Capture active'), (True, False, 'SHELL ACTIVE')]:
            with self.subTest(expected=expected):
                shutdown = threading.Event()
                tray = Mock()
                pystray = Mock()
                pystray.Icon.return_value = tray
                tray.run.side_effect = lambda setup: setup(tray)
                server = types.SimpleNamespace(PASSWORD='private-password', camera=None,
                    desktop_wanted=capture, mic_stream=None, mixer=types.SimpleNamespace(desktop_subscription=None))
                control = types.SimpleNamespace(server=server, terminal=Mock())
                control.terminal.read.return_value = {'running': shell}
                with patch.dict('sys.modules', {'pystray': pystray}), patch.object(shutdown, 'wait', side_effect=lambda delay: shutdown.set() or True):
                    show_host(control, shutdown)
                self.assertTrue(tray.visible)
                self.assertIn(expected, tray.title)
                self.assertNotIn(server.PASSWORD, tray.title)
                self.assertTrue(shutdown.is_set())
                tray.stop.assert_called()
                callback = pystray.MenuItem.call_args.args[1]
                shutdown.clear()
                callback(tray)
                self.assertTrue(shutdown.is_set())

    def test_tray_failure_stops_host_instead_of_running_invisibly(self):
        shutdown = threading.Event()
        pystray = Mock()
        pystray.Icon.return_value.run.side_effect = RuntimeError('No tray backend')
        with patch.dict('sys.modules', {'pystray': pystray}):
            with self.assertRaisesRegex(RuntimeError, 'No tray backend'):
                show_host(Mock(), shutdown)
        self.assertTrue(shutdown.is_set())

    def test_control_center_fatal_error_logs_without_opening_tkinter(self):
        import webcam_server as server
        tkinter = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('sys.modules', {'tkinter': tkinter}), patch.object(server, '_has_console', return_value=False), patch.object(server, '_config_path', return_value=str(Path(directory) / 'settings.ini')), patch('sys.argv', ['webcam_server']), patch('sys.stdout', new_callable=io.StringIO):
                server.report_fatal('Test tray failure')
            self.assertIn('Test tray failure', (Path(directory) / 'roomcam_error.log').read_text())
        tkinter.Tk.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
