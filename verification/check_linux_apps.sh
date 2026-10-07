#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
env -u LD_LIBRARY_PATH xvfb-run -a .venv-linux/bin/python verification/check_windows_apps.py
