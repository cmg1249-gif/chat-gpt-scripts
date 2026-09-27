"""Linux port checks; no real camera, microphone, or desktop is captured."""
import json
import os
import unittest
from unittest.mock import patch

import desktop_audio
import combined_media


class LinuxTests(unittest.TestCase):
    def test_system_audio_tools_do_not_inherit_bundled_libraries(self):
        with patch.object(desktop_audio.sys, 'frozen', True, create=True), patch.dict(
            os.environ, {'LD_LIBRARY_PATH': '/tmp/bundle', 'LD_LIBRARY_PATH_ORIG': '/usr/local/lib'}, clear=True
        ):
            self.assertEqual(desktop_audio.system_environment()['LD_LIBRARY_PATH'], '/usr/local/lib')

    @patch('desktop_audio.shutil.which', return_value='/usr/bin/tool')
    @patch('desktop_audio.subprocess.check_output')
    def test_capture_selects_default_speaker_monitor(self, command, which):
        command.side_effect = ['speaker\n', json.dumps([
            {'name': 'other', 'monitor_source_name': 'other.monitor'},
            {'name': 'speaker', 'description': 'Speakers', 'monitor_source_name': 'speaker.monitor'},
        ])]
        self.assertEqual(desktop_audio.monitor_source(), ('speaker.monitor', 'Speakers'))

    @patch('desktop_audio.shutil.which', return_value='/usr/bin/tool')
    @patch('desktop_audio.subprocess.check_output')
    def test_missing_monitor_never_falls_back_to_microphone(self, command, which):
        command.side_effect = ['speaker\n', json.dumps([{'name': 'speaker'}])]
        with self.assertRaises(desktop_audio.AudioUnavailable):
            desktop_audio.monitor_source()

    def test_missing_pulse_tools_gives_actionable_error(self):
        with patch('desktop_audio.shutil.which', return_value=None):
            with self.assertRaisesRegex(desktop_audio.AudioUnavailable, 'libpulse'):
                desktop_audio.monitor_source()

    def test_wayland_desktop_capture_is_rejected_even_with_xwayland(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':1'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'X11'):
                combined_media.require_x11()

    def test_x11_desktop_is_accepted(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11', 'DISPLAY': ':1'}, clear=True):
            combined_media.require_x11()


if __name__ == '__main__':
    unittest.main()
