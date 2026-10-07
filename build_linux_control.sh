#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
root="$PWD"
export LD_LIBRARY_PATH="$HOME/.cache/roomcam-control-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHON="$root/.venv-linux/bin/python"
build_dir="$HOME/.cache/roomcam-control-build"
mkdir -p "$build_dir/assets"
cp linux/camera-desktop-sharing/*.py linux/camera-desktop-sharing/*.html linux/camera-desktop-sharing/build.sh linux/camera-desktop-sharing/cloudflared "$build_dir/"
cp linux/camera-desktop-sharing/assets/* "$build_dir/assets/"
chmod +x "$build_dir/cloudflared"
cd "$build_dir"
bash build.sh
mkdir -p "$root/linux/camera-desktop-sharing/dist"
cp dist/*.elf "$root/linux/camera-desktop-sharing/dist/"
env -u LD_LIBRARY_PATH xvfb-run -a dist/CheckConnection.elf --self-test
env -u LD_LIBRARY_PATH xvfb-run -a dist/CheckConnection.elf
