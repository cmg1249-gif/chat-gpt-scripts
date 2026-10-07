#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-python3}"
test -x cloudflared || { echo 'Place the official Linux amd64 cloudflared binary here and chmod +x cloudflared.' >&2; exit 1; }
mkdir -p dist
portaudio="$("$PYTHON" -c "import os,pathlib; roots=os.environ.get('LD_LIBRARY_PATH','').split(':')+['/usr/lib/x86_64-linux-gnu','/lib/x86_64-linux-gnu','/usr/lib']; print(next(str(pathlib.Path(p)/'libportaudio.so.2') for p in roots if p and (pathlib.Path(p)/'libportaudio.so.2').is_file()))")"
common=(--noconfirm --onefile --distpath dist --workpath .build --specpath .build --runtime-hook "${PWD}/linux_audio_runtime.py" --add-binary "${portaudio}:." --add-data "${PWD}/control.html:." --add-data "${PWD}/assets:assets")
"$PYTHON" -m PyInstaller "${common[@]}" --name webcam_server.elf --hidden-import pystray._xorg --add-binary "${PWD}/cloudflared:." --add-data "${PWD}/page.html:." webcam_server.py
"$PYTHON" -m PyInstaller "${common[@]}" --name viewer.elf --collect-all imageio_ffmpeg viewer.py
"$PYTHON" -m PyInstaller "${common[@]}" --name CheckConnection.elf --collect-all imageio_ffmpeg --hidden-import pystray._xorg --add-binary "${PWD}/cloudflared:." --add-data "${PWD}/page.html:." check_control_center.py
file dist/*.elf
