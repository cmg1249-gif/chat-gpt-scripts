"""Native Windows rendering tests; never move the user's mouse or show windows."""
import ctypes as ct
from ctypes import wintypes as wt
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
import desktop_cursor as cursor
import combined_media as media
import viewer


@unittest.skipUnless(sys.platform == 'win32', 'Windows cursor rendering')
class CursorTests(unittest.TestCase):
    def setUp(self):
        load = cursor._bind(cursor._user, 'LoadCursorW',
                            [wt.HINSTANCE, ct.c_void_p], wt.HANDLE)
        self.handle = load(None, ct.c_void_p(32512))
        self.assertTrue(self.handle)
        self.position = (80, 60)
        self.flags = 1
        self.bounds = dict(left=0, top=0, width=240, height=160)

    def get_cursor(self, pointer):
        info = ct.cast(pointer, ct.POINTER(cursor.CURSORINFO)).contents
        info.flags = self.flags
        info.hCursor = self.handle
        info.ptScreenPos = wt.POINT(*self.position)
        return 1

    def render(self, frame=None, bounds=None):
        if frame is None:
            frame = np.full((160, 240, 3), 110, np.uint8)
        with patch.object(cursor, '_get_cursor', side_effect=self.get_cursor):
            return cursor.draw_cursor(frame, bounds or self.bounds)

    def test_native_arrow_and_ibeam_change_only_cursor_region(self):
        for resource in (32512, 32513, 32649):
            self.handle = cursor._user.LoadCursorW(None, ct.c_void_p(resource))
            image = self.render()
            changed = np.any(image != 110, axis=2)
            self.assertGreater(changed.sum(), 5)
            y, x = np.where(changed)
            self.assertTrue(30 <= x.min() <= 90 and x.max() < 145)
            self.assertTrue(10 <= y.min() <= 70 and y.max() < 125)

    def test_negative_monitor_origin_and_hotspot(self):
        expected = self.render()
        self.position = (-1840, -1020)
        actual = self.render(bounds=dict(left=-1920, top=-1080))
        np.testing.assert_array_equal(actual, expected)

    def test_clipping_at_every_edge_matches_full_render(self):
        center = self.render(np.full((320, 480, 3), 110, np.uint8))
        # Crop around the same cursor to create a reference for every edge.
        for origin_x, origin_y in ((85, 0), (0, 65), (-150, 0), (0, -90)):
            # A larger reference canvas permits negative clipping origins.
            self.position = (240, 160)
            full = self.render(np.full((480, 720, 3), 110, np.uint8))
            ox, oy = origin_x + 160, origin_y + 100
            expected = full[oy:oy+160, ox:ox+240]
            actual = self.render(bounds=dict(left=ox, top=oy))
            np.testing.assert_array_equal(actual, expected)
        self.assertTrue(center.size)

    def test_hidden_suppressed_unavailable_and_other_monitor_leave_pixels_unchanged(self):
        frame = np.full((160, 240, 3), 110, np.uint8)
        for flags in (0, 2):
            self.flags = flags
            np.testing.assert_array_equal(self.render(frame), frame)
        self.flags = 1
        for position in ((1000, 1000), (-1000, -1000)):
            self.position = position
            np.testing.assert_array_equal(self.render(frame), frame)
        with patch.object(cursor, '_get_cursor', return_value=0):
            self.assertIs(cursor.draw_cursor(frame, self.bounds), frame)
        with patch.object(cursor, '_copy_icon', return_value=None):
            self.assertIs(self.render(frame), frame)

    def test_repeated_capture_does_not_leak_gdi_objects(self):
        kernel = ct.WinDLL('kernel32')
        current = cursor._bind(kernel, 'GetCurrentProcess', [], wt.HANDLE)
        count = cursor._bind(cursor._user, 'GetGuiResources', [wt.HANDLE, wt.DWORD], wt.DWORD)
        self.render()
        before = count(current(), 0)
        for _ in range(200):
            self.render()
        self.assertLessEqual(count(current(), 0), before + 1)

    def test_stream_resizes_cursor_and_recording_keeps_it(self):
        capture = Mock()
        capture.__enter__ = Mock(return_value=capture)
        capture.__exit__ = Mock(return_value=False)
        capture.monitors = [{}, self.bounds]
        capture.grab.return_value = np.full((160, 240, 4), 110, np.uint8)
        with patch.object(media.mss, 'MSS', return_value=capture), \
             patch.object(cursor, '_get_cursor', side_effect=self.get_cursor):
            stream = media.desktop_frames(1, lambda: True, width=120)
            try:
                jpeg = next(stream).split(b'\r\n\r\n', 1)[1][:-2]
            finally:
                stream.close()
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (80, 120, 3))
        self.assertGreater(np.abs(decoded[20:55, 25:65].astype(float)-110).max(), 30)
        with tempfile.TemporaryDirectory() as directory:
            recorder = viewer.Recorder(directory, 'mp4')
            recorder.start(decoded, 48000, 2)
            for _ in range(12):
                recorder.write_video(decoded)
                recorder.write_audio(bytes(4800 * 4))
            path = recorder.stop()
            video = cv2.VideoCapture(path)
            try:
                ok, recorded = video.read()
                self.assertTrue(ok)
                self.assertGreater(np.abs(recorded[20:55, 25:65].astype(float)-110).max(), 25)
            finally:
                video.release()

    def test_native_allocation_failure_preserves_video(self):
        for name in ('_create_dc', '_create_dib', '_get_icon', '_draw'):
            with self.subTest(name=name), patch.object(cursor, name, return_value=0):
                np.testing.assert_array_equal(self.render(), np.full((160, 240, 3), 110, np.uint8))


if __name__ == '__main__':
    unittest.main()

