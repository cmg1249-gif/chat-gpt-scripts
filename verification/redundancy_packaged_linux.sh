#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
env -u LD_LIBRARY_PATH xvfb-run -a linux/camera-desktop-sharing/dist/CheckConnection.elf --self-test > verification/redundancy-packaged-linux-tests.txt 2>&1
env -u LD_LIBRARY_PATH xvfb-run -a linux/camera-desktop-sharing/dist/CheckConnection.elf --relay > verification/redundancy-packaged-linux-relay.txt 2>&1
env -u LD_LIBRARY_PATH xvfb-run -a .venv-linux/bin/python verification/check_windows_apps.py > verification/redundancy-linux-apps.txt 2>&1
tail -n 5 verification/redundancy-packaged-linux-tests.txt
cat verification/redundancy-packaged-linux-relay.txt verification/redundancy-linux-apps.txt
