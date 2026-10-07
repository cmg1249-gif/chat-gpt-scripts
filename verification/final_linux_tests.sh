#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
cp "$HOME/.cache/roomcam-control-build/dist/"*.elf linux/camera-desktop-sharing/dist/
env -u LD_LIBRARY_PATH xvfb-run -a linux/camera-desktop-sharing/dist/CheckConnection.elf --self-test > verification/linux-packaged-tests.txt 2>&1
env -u LD_LIBRARY_PATH xvfb-run -a linux/camera-desktop-sharing/dist/CheckConnection.elf > verification/linux-packaged-e2e.txt 2>&1
env -u LD_LIBRARY_PATH xvfb-run -a .venv-linux/bin/python verification/check_windows_apps.py > verification/linux-actual-apps.txt 2>&1
tail -n 5 verification/linux-packaged-tests.txt
cat verification/linux-packaged-e2e.txt verification/linux-actual-apps.txt
