# RoomCam Control Center — 3.0.1 preview

A browser dashboard for Windows and Linux sharing hosts, with live camera/desktop viewing, microphone and speaker controls, connection diagnostics, and an interactive PowerShell or Bash terminal.

## Start

1. On the sharing computer, open **webcam_server.exe** (Windows) or **webcam_server.elf** (Linux). It opens a status window with a generated pairing code. There are no host settings to fill out.
2. On the viewing computer, open **viewer.exe** or **viewer.elf**. Keep the listener running; it opens the control center in your browser.
3. Paste the host's code into the dashboard and choose a session password. Click **Connect to host**. Everything is set from the listener.
4. Choose a source and click **Start viewing**. Audio controls are independent. **Terminal → Open terminal** opens a persistent interactive shell on the host.
5. **Disconnect** stops video, microphone, speaker capture, and the shell. Closing the sharing window also stops the host. Close the listener with Ctrl+C to disconnect and exit.

The host's code and password are session-only. Restarting the host creates a new code and allows a new password. Reconnecting to the same host session requires the same code and password. Closing a browser tab alone does not stop sharing; use Disconnect or close the host. A shell closes after 15 minutes without keyboard input.

Use the matching **3.0.1 preview** host and listener together. This pairing protocol is intentionally different from the old public first-claim protocol. The new listener cannot pair with v2.x hosts. The old camera/desktop viewer remains available from source or packaged viewer with `--legacy`; the old host mode has no browser shell.

## Same or different networks

- **Automatic** tries direct LAN first, then Cloudflare, then an independent Pinggy TLS relay. Both internet providers run independently so one failing does not stop the other.
- LAN uses encrypted TCP **2220** plus UDP **2220** for discovery. If broadcast discovery is blocked, enter the host's IPv4 address under Connection options on the listener. Windows Firewall or school Wi-Fi isolation may still block device-to-device access; the app does not change firewall rules.
- Cloudflare uses bundled cloudflared and its automatic QUIC/HTTP2 transport fallback over UDP/TCP **7844**. The independent Pinggy route uses the operating system's **OpenSSH client** (`ssh` and `ssh-keygen`) over TCP **443**. Pinggy forwards TLS without decrypting it; the listener pins the host's signed session certificate. SSH on port 443 is still SSH, so networks restricting traffic to browser HTTPS may block it. If OpenSSH is unavailable, Cloudflare and LAN remain usable.
- The browser only connects to the listener's loopback address. The listener verifies the host certificate for local connections; no browser certificate exception is needed.
- Read-only requests can switch to another authenticated route when the current route fails. The dashboard displays the new route. Interrupted video/audio streams may need Start viewing or Listen again. Commands are never replayed automatically after an error because they may already have executed. Transient initial DNS and gateway failures receive bounded retries.
- Discovery normally uses `ntfy.sh`. If it is unavailable, click **Copy fallback connection details** in the host window and paste into the listener's host-code field within two minutes. The signed details include active endpoints and bypass the discovery service. They contain the pairing code; share them only with your intended listener. This requires no host configuration.
- Pinggy free tunnels expire after 60 minutes. The app detects process exit, reconnects, and advertises a new URL. This can interrupt streams. Free relay services do not provide a guarantee of availability; normal internet access alone cannot guarantee either tunnel service is allowed.

## Shell and authentication

The shell runs as the user who launched the sharing app. It does not elevate privileges or install persistence. The host shows when a shell is active and closes the shell during normal shutdown; programs deliberately detached from that shell may outlive it. Shell history is not saved to the user's usual history file.

Initial discovery is signed with a random 128-bit host code. The code and pairing token are not published to ntfy. Possessing the code allows the listener to set the session password. Keep the code with the people authorized to control that host.

The local browser gateway uses a one-use launch token, an HttpOnly SameSite cookie, an explicit control token for changes, an exact loopback Host check, an Origin check, and a limited set of proxy endpoints. The terminal has bounded output retention and an idle timeout. Anyone with the code/password can operate the host with the sharing user's permissions.

## Linux

The Linux build targets x86_64 Linux (Ubuntu 24.04/WSL2 test environment; glibc 2.39 baseline). Desktop capture still requires **X11**, not native Wayland. System audio requires PulseAudio or PipeWire-Pulse and `pactl` / `parec`; these device/session requirements are separate from connection settings. The terminal and listener do not require desktop capture to be enabled.

If a graphical host window is unavailable, run `./webcam_server.elf --headless` to show the generated code in the terminal. No host configuration file is required.

## Diagnostics and builds

`CheckConnection.exe` / `CheckConnection.elf` runs a generated-media TLS, pairing, shell, and cleanup check. `--self-test` runs the control-center regression suite. `--internet` exercises signed discovery and generated media through a real temporary Cloudflare tunnel. `--relay` tests the independent Pinggy route with Cloudflare absent, including rejection of the wrong TLS certificate. It also runs a harmless shell marker. It never captures a real desktop, microphone, or webcam.

Source: Python 3.12 and the platform folder's requirements. Run `python webcam_server.py` on the host and `python viewer.py` on the listener. Cloudflared must be beside source when running the host from Python; it is bundled in releases. Browser terminal assets are bundled locally and require no CDN.

Build using `camera-desktop-sharing/build.ps1` or `linux/camera-desktop-sharing/build.sh`. Common control-center modules are synchronized with `python sync_control_center.py`.

Run the suites as separate processes:

```text
python -m unittest -v test_control
python -m unittest -v test_combined test_cursor   # Windows
python -m unittest -v test_combined test_linux    # Linux
python check_control_center.py
python check_control_center.py --internet
python check_control_center.py --relay
```

See **verification/REDUNDANCY.md** for this update and **verification/RESULTS.md** for the original preview tests and remaining limits. Do not use the old v2.0.2 checksums to verify these preview binaries.
