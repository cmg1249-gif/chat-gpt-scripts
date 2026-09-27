"""Run both packaged applications locally and write a reproducible test report."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import contextlib


def main():
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'bin'
    report = directory / 'connection-test.txt'
    if '--media' in sys.argv:
        import test_media
        with (directory / 'media-test.txt').open('w', buffering=1) as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    test_media.main()
                except Exception:
                    import traceback
                    traceback.print_exc()
                    raise
        return
    if '--internet' in sys.argv:
        import test_internet
        with (directory / 'internet-test.txt').open('w', buffering=1) as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    test_internet.main()
                except Exception:
                    import traceback
                    traceback.print_exc()
                    raise
        return
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with report.open('w', buffering=1) as log, tempfile.TemporaryDirectory(prefix='screen-test-') as scratch:
        session = Path(scratch) / 'session.json'
        log.write('Testing packaged server and viewer over loopback; no public tunnel.\n')
        server = subprocess.Popen([str(directory / 'ScreenServer.exe'), '--local', '--port', '0', '--session-file', str(session), '--stop-after', '25'], stdout=log, stderr=log, creationflags=flags)
        try:
            deadline = time.monotonic() + 20
            while not session.exists():
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Server failed to start; see log above.')
                time.sleep(0.2)
            env = os.environ.copy()
            env['DESKTOP_STREAM_TEST_PASSWORD'] = 'local-test-only-7rT9'
            result = subprocess.run([str(directory / 'ScreenListener.exe'), '--session-file', str(session), '--frames', '12'], env=env, stdout=log, stderr=log, timeout=20, creationflags=flags)
            if result.returncode:
                raise RuntimeError(f'Viewer failed: {result.returncode}')
            log.write('PASS: server EXE captured and listener EXE displayed/decoded 12 real desktop frames.\n')
            server.wait(timeout=30)
            if server.returncode:
                raise RuntimeError(f'Server exit code: {server.returncode}')
            log.write('PASS: server stopped automatically and exited cleanly.\n')
        except Exception as exc:
            log.write(f'FAIL: {exc}\n')
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=5)


if __name__ == '__main__':
    main()
