#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
root="$PWD"
mkdir -p .build/linux-libs/runtime
cd .build/linux-libs
dpkg-deb -x ./libportaudio2_*.deb runtime
ln -sf libportaudio.so.2 runtime/usr/lib/x86_64-linux-gnu/libportaudio.so
mkdir -p "$HOME/.cache/roomcam-control-libs"
cp -a runtime/usr/lib/x86_64-linux-gnu/libportaudio.so* "$HOME/.cache/roomcam-control-libs/"
export LD_LIBRARY_PATH="$HOME/.cache/roomcam-control-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$root/linux/camera-desktop-sharing"
"$root/.venv-linux/bin/python" -m unittest -v test_control
xvfb-run -a "$root/.venv-linux/bin/python" -m unittest -v test_combined test_linux
xvfb-run -a "$root/.venv-linux/bin/python" check_control_center.py
