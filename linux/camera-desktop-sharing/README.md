# Camera and desktop sharing for Linux

Linux counterpart of the v2.0.2 Windows camera/desktop application. The server and viewer keep the existing pairing and media protocol. Use only on equipment you own or have permission to share, with the knowledge of anyone being captured.

## Executables

Get **RoomCam_v2.0.2_linux_x86_64.tar.gz** from the [v2.0.2 release](https://github.com/cmg1249-gif/chat-gpt-scripts/releases/tag/v2.0.2). See the [Linux download instructions](../README.md) for Arch packages and commands.

## Run from Python source

Keep every file in this folder together. Python 3.12 is the tested build runtime; the requirements also select `audioop-lts` on Python 3.13 and later, though those runtimes have not been validated.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For internet sharing, download the official **Linux amd64** [cloudflared binary](https://github.com/cloudflare/cloudflared/releases), name it `cloudflared`, place it beside `webcam_server.py`, and run `chmod +x cloudflared`.

On the sharing PC:

```bash
.venv/bin/python webcam_server.py
```

On the viewing PC:

```bash
.venv/bin/python viewer.py
```

Choose an 8–128 character password in the viewer. The host waits for pairing and prints status in its terminal. Stop it with Ctrl+C. There is no automatic startup or background installation. Use a matching server and viewer protocol; each full server restart requires a new pairing.

## Controls

| Key | Action |
|---|---|
| V | Switch camera / desktop |
| B | Next monitor (X11 desktop sharing) |
| C | Next camera |
| N | Next microphone |
| F | Refresh devices |
| M | Toggle host microphone |
| O | Toggle host speaker capture |
| Space | Mute / unmute local playback |
| R or REC button | Start / stop recording |
| Q, Escape, window close | Close viewer and stop capture |
| L | Close viewer and leave capture running |

Use `--mute` for a same-computer test to avoid feedback. The viewer saves recordings beside itself, so use a writable extracted folder. `--browser` opens the browser interface; recording uses the desktop viewer. Browser authentication uses `admin` and the password selected in the viewer by default.

## Build the three ELF executables

On x86_64 Linux, install the requirements and place executable `cloudflared` in this folder, then:

```bash
PYTHON=.venv/bin/python bash build.sh
```

Outputs: `dist/webcam_server.elf`, `dist/viewer.elf`, and `dist/CheckConnection.elf`.

```bash
.venv/bin/python -m unittest -v test_combined test_linux
./dist/CheckConnection.elf --self-test
```

The diagnostic writes `unit-results.txt` beside the executable. Its default check captures the local X11 desktop and plays a brief speaker test tone over localhost. `--internet` tests generated media through the public tunnel; it does not capture real camera, desktop, or microphone content.

## Limitations

Desktop capture uses MSS/XFixes and requires X11. Speaker capture requires `pactl`/`parec` and a working PulseAudio-compatible login session (PulseAudio or PipeWire-Pulse). Native Wayland screen capture is not implemented. The default host uses a foreground terminal; `--tray` is optional and requires a supported system tray.

Initial discovery uses the same shared public ntfy topic as the Windows program. Someone with access to discovery can attempt to claim an unpaired host; use one host per demo and share only with trusted participants. Certificate and hostname checks remain enabled. Internet access and Cloudflare/ntfy availability are required for internet sharing. See [VALIDATION.md](VALIDATION.md).
