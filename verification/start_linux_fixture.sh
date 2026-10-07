#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../linux/camera-desktop-sharing"
env -u LD_LIBRARY_PATH xvfb-run -a ./dist/CheckConnection.elf --serve --internet --output .build/cross-linux.json
