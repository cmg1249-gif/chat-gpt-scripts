#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
root="$PWD"
export LD_LIBRARY_PATH="$HOME/.cache/roomcam-control-libs"
cd linux/camera-desktop-sharing
"$root/.venv-linux/bin/python" -m unittest -v test_control > "$root/verification/redundancy-tests-linux.txt" 2>&1
xvfb-run -a "$root/.venv-linux/bin/python" check_control_center.py --relay > "$root/verification/relay-linux-source-e2e.txt" 2>&1
tail -n 5 "$root/verification/redundancy-tests-linux.txt"
cat "$root/verification/relay-linux-source-e2e.txt"
