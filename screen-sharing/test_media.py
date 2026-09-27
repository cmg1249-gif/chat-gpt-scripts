"""Opt-in real hardware checks for packaged monitor capture and desktop audio."""
import base64
from pathlib import Path
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import numpy as np
from desktop_audio import AudioOutput
import listener
from tls import HTTPS_CONTEXT
from viewer import audio_format, DesktopViewer


def verify_audio(base_url, password, play_test_tone=False, expect_test_tone=False):
    auth = base64.b64encode(f'viewer:{password}'.encode()).decode()
    request = urllib.request.Request(base_url + '/audio', headers={'Authorization': f'Basic {auth}'})
    with urllib.request.urlopen(request, timeout=15, context=HTTPS_CONTEXT) as response:
        rate, channels = audio_format(response.headers)
        tone_error = []
        def tone():
            output = None
            try:
                output = AudioOutput(rate, channels)
                values = (1500 * np.sin(2 * np.pi * 997 * np.arange(rate) / rate)).astype('<i2')
                output.write(np.repeat(values[:, None], 2, axis=1).tobytes())
            except Exception as exc:
                tone_error.append(exc)
            finally:
                if output:
                    output.close()
        thread = None
        if play_test_tone:
            thread = threading.Thread(target=tone, daemon=True)
            thread.start()
        data = listener.read_exact(response, rate * channels * 2 * 2)
        if thread:
            thread.join(timeout=5)
        if tone_error:
            raise tone_error[0]
        if data is None:
            raise RuntimeError('Audio stream ended early')
        samples = np.frombuffer(data, dtype='<i2').reshape(-1, channels)[:, 0].astype(float)
        rms = float(np.sqrt(np.mean(samples * samples)))
        if play_test_tone or expect_test_tone:
            spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
            frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
            peak = spectrum[(frequencies > 994) & (frequencies < 1000)].max()
            background = np.median(spectrum[(frequencies > 900) & (frequencies < 1100)]) + 1
            if rms < 10 or peak / background < 5:
                raise RuntimeError(f'Expected test tone was not captured (RMS={rms:.1f}, peak/background={peak / background:.1f})')
        print(f'PASS: received two seconds of stereo desktop PCM at {rate} Hz (RMS={rms:.1f}).', flush=True)
        if play_test_tone:
            print('PASS: 997 Hz playback tone detected through real WASAPI loopback and authenticated HTTP.', flush=True)
        elif expect_test_tone:
            print('PASS: 997 Hz synthetic tone detected in delivered audio.', flush=True)


def verify_viewer_controls(base_url, password, monitors):
    viewer = DesktopViewer(base_url, password, None, listener.http_json,
                           listener.find_session, listener.stream_video, muted=True)
    viewer.root.withdraw()  # Exercise UI callbacks without moving focus or the mouse.
    viewer.audio_worker = lambda: viewer.stop.wait()
    received = set()
    errors = []
    original = viewer.put_frame
    def frame(image, monitor):
        received.add(monitor)
        original(image, monitor)
    viewer.put_frame = frame
    target = monitors[-1]['id']
    deadline = time.monotonic() + 15
    def advance():
        try:
            if 1 in received and target not in received:
                index = next(i for i, m in enumerate(viewer.monitors) if m['id'] == target)
                viewer.monitor_box.current(index)
                viewer.monitor_box.event_generate('<<ComboboxSelected>>')
            if target in received:
                viewer.mute_var.set(False)
                viewer.toggle_mute()
                if viewer.muted:
                    raise RuntimeError('Unmute control did not update')
                viewer.mute_var.set(True)
                viewer.toggle_mute()
                if not viewer.muted:
                    raise RuntimeError('Mute control did not update')
                viewer.close()
                return
            if time.monotonic() > deadline:
                raise RuntimeError('Viewer did not switch to the requested monitor')
            viewer.root.after(100, advance)
        except Exception as exc:
            errors.append(exc)
            viewer.close()
    viewer.root.after(100, advance)
    viewer.run()
    if errors:
        raise errors[0]
    print(f'PASS: viewer dropdown received monitors {sorted(received)}; mute/unmute controls changed state.', flush=True)


def main():
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'bin'
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix='screen-media-') as scratch:
        session_path = Path(scratch) / 'session.json'
        server = subprocess.Popen([str(directory / 'ScreenServer.exe'), '--local', '--port', '0',
                                   '--session-file', str(session_path), '--stop-after', '40'],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 20
            while not session_path.exists():
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Packaged media server did not start')
                time.sleep(0.2)
            import json
            session = json.loads(session_path.read_text())
            base_url = session['url']
            listener.http_json(base_url + '/pair', method='POST', payload={'token': session['token'], 'password': password})
            monitors = listener.http_json(base_url + '/monitors', username='viewer', password=password)['monitors']
            print(f'Found {len(monitors)} capture monitor(s).', flush=True)
            env = os.environ.copy()
            env['DESKTOP_STREAM_TEST_PASSWORD'] = password
            for monitor in monitors:
                result = subprocess.run([str(directory / 'ScreenListener.exe'), '--session-file', str(session_path),
                                         '--monitor', str(monitor['id']), '--frames', '12', '--headless'],
                                        env=env, capture_output=True, text=True, timeout=20,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                print(f"PASS: packaged listener decoded monitor {monitor['id']} ({monitor['width']}x{monitor['height']}).", flush=True)
            verify_audio(base_url, password, play_test_tone=True)
            verify_viewer_controls(base_url, password, monitors)
            server.wait(timeout=45)
            if server.returncode:
                raise RuntimeError(f'Server exited with {server.returncode}')
            print('PASS: packaged media checks complete; server stopped cleanly.', flush=True)
        finally:
            if server.poll() is None:
                subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
