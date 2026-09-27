#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-python3}"
test -x cloudflared || { echo 'Place the official Linux amd64 cloudflared binary here and chmod +x cloudflared.' >&2; exit 1; }
mkdir -p dist
common=(--noconfirm --clean --onefile --distpath dist --workpath .build --specpath .build)
"$PYTHON" -m PyInstaller "${common[@]}" --name webcam_server.elf --hidden-import pystray._xorg --add-binary "${PWD}/cloudflared:." --add-data "${PWD}/page.html:." webcam_server.py
"$PYTHON" -m PyInstaller "${common[@]}" --name viewer.elf --collect-all imageio_ffmpeg viewer.py
"$PYTHON" -m PyInstaller "${common[@]}" --name CheckConnection.elf --collect-all imageio_ffmpeg --hidden-import pystray._xorg --add-binary "${PWD}/cloudflared:." --add-data "${PWD}/page.html:." check_connection.py
file dist/*.elf
