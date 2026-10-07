#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export LD_LIBRARY_PATH="$HOME/.cache/roomcam-control-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
.venv-linux/bin/python verification/cross_client.py camera-desktop-sharing/.build/cross-windows.json --expect Windows
