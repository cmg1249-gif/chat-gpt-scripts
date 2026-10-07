"""Cross-platform client of a generated-media fixture, never a real desktop."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / ('camera-desktop-sharing' if os.name == 'nt' else 'linux/camera-desktop-sharing')))
from control_listener import Remote, find_internet
from check_connection import read_video, read_audio

parser = argparse.ArgumentParser()
parser.add_argument('session')
parser.add_argument('--expect', required=True)
args = parser.parse_args()
data = json.loads(Path(args.session).read_text())
found = find_internet(data['code'], wait=30)
assert found, 'No signed host advertisement'
base, context, route = found[0]
remote = Remote(base, context, route, data['code'], data['password'])
try:
    status = remote.pair()
    assert status['platform'] == args.expect, status
    print(f'PASS {sys.platform} listener paired with {status["platform"]} host', flush=True)
    remote.open_stream = remote.open
    remote.json('/source/select?source=desktop&monitor=2', 'POST')
    read_video(remote)
    remote.json('/desktop-audio/start', 'POST')
    read_audio(remote, 997)
    remote.json('/terminal', 'POST')
    if args.expect == 'Windows':
        time.sleep(.5)
        remote.json('/terminal/input', 'POST', dict(data='\x1b[?1;2c'))
        command = "Write-Output ('CROSS_PLATFORM_' + 'OK')\r"
    else:
        command = "printf '%s%s\\n' CROSS_PLATFORM_ OK\r"
    time.sleep(.5)
    remote.json('/terminal/input', 'POST', dict(data=command))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        output = remote.json('/terminal')['output']
        if 'CROSS_PLATFORM_OK' in output:
            break
        time.sleep(.2)
    assert 'CROSS_PLATFORM_OK' in output, output
    print('PASS cross-platform interactive shell and generated video/audio', flush=True)
finally:
    remote.stop()
print('PASS remote shell and capture cleanup', flush=True)
