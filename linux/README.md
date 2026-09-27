# Linux downloads (Arch Linux x86_64)

The v2.0.2 release includes **RoomCam_v2.0.2_linux_x86_64.tar.gz**. Extract it to get one `linux/` folder containing:

| File | Purpose |
|---|---|
| `webcam_server.elf` | Run on the computer sharing camera/desktop and audio |
| `viewer.elf` | Run on the computer viewing or recording |
| `CheckConnection.elf` | Optional diagnostics |
| `source/` | Matching Python source, dependencies, and build script |

[Download the Linux folder](https://github.com/cmg1249-gif/chat-gpt-scripts/releases/download/v2.0.2/RoomCam_v2.0.2_linux_x86_64.tar.gz)

These are native Linux ELF executables. Python and the app's Python packages are bundled. The sharing host also bundles the Linux Cloudflare tunnel; the viewer bundles the recording encoder. The existing Windows `.exe` assets are separate.

## Run on Arch

Use a current **x86_64 Arch Linux** desktop. Install the desktop libraries if missing:

```bash
sudo pacman -S --needed portaudio libpulse alsa-plugins libxcb libxkbcommon-x11 libglvnd ttf-dejavu
tar -xzf RoomCam_v2.0.2_linux_x86_64.tar.gz
cd linux
chmod +x *.elf
```

Your login session must already have a working PulseAudio server or PipeWire with `pipewire-pulse` for speaker-output capture. `pactl` and `parec` come from Arch's `libpulse` package. Do not run the apps with sudo.

On the sharing computer, open a terminal in the extracted folder:

```bash
./webcam_server.elf
```

Leave this terminal open. **Press Ctrl+C to stop sharing.** On the viewing computer, open a terminal in its extracted folder:

```bash
./viewer.elf
```

Choose the password in the viewer. Camera, microphone, desktop, recording, and viewer controls follow the [program instructions](camera-desktop-sharing/README.md). Optional: `./viewer.elf --browser` or `./webcam_server.elf --tray` (requires a compatible X11 system tray).

## Desktop compatibility

- **Desktop sharing requires an X11 login session.** Log out and select an X11/Xorg session at your display manager. Wayland screen capture through the desktop portal is not implemented; the app rejects it instead of streaming an incomplete XWayland desktop.
- Speaker capture uses only the default output device's monitor source. It never substitutes a microphone when a monitor is unavailable.
- ARM64 is not supported by this download.
- These Linux builds are derived from the v2.0.2 source with Linux-specific adaptations. See [validation details](camera-desktop-sharing/VALIDATION.md) for what was actually tested.

## Source code

The complete program is in [camera-desktop-sharing/](camera-desktop-sharing/). Keep its helper files together. The archive's `source/` folder has the same code. A loose `viewer.py` also requires `connection.py`, `discovery.py`, `retry.py`, `tls.py`, and the installed Python dependencies.

References: [Arch PipeWire documentation](https://wiki.archlinux.org/title/PipeWire), [Arch libpulse package](https://archlinux.org/packages/extra/x86_64/libpulse/), [PyInstaller platform requirements](https://www.pyinstaller.org/en/stable/usage.html).
