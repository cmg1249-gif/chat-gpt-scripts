# RoomCam Control Center — 3.0.2 preview

A browser dashboard for Windows and Linux sharing hosts, with live camera/desktop viewing, microphone and speaker controls, connection diagnostics, and an interactive PowerShell or Bash terminal.

## Start

1. On the viewing computer, extract the matching release bundle and open **viewer.exe** (Windows) or **viewer.elf** (Linux). Keep the viewer running; it opens the control center in your browser.
2. Enter a computer name, choose the sharing computer's operating system, and click **Create host package**. A password is generated automatically unless you choose one. The viewer saves the connection privately.
3. Transfer that private ZIP to the sharing computer, extract it, and run **webcam_server.exe** or **webcam_server.elf**. Keep `roomcam-host.json` beside it. Nothing needs to be entered, selected, or copied back from the host. In the viewer, select its saved name and click **Connect to computer**.
4. Choose a source and click **Start viewing**. Audio controls are independent. **Terminal → Open terminal** opens a persistent interactive shell on the host.
5. **Disconnect** stops video, microphone, speaker capture, and the shell. Closing the sharing window also stops the host. Close the listener with Ctrl+C to disconnect and exit.

The saved connection survives restarting both applications. Create a separate private package for each sharing computer; do not publish these packages. The public release downloads contain no pre-shared credentials. The generic public host executable alone is not pre-paired: create its package in the viewer first. A standalone viewer downloads a missing host executable from the matching release and verifies its SHA-256 checksum; the same-platform bundle already includes it.

Closing a browser tab alone does not stop sharing; use Disconnect or close the host. A shell closes after 15 minutes without keyboard input. Saved viewer settings live in `%LOCALAPPDATA%/RoomCam/listener` on Windows and `~/.local/share/RoomCam/listener` on Linux. Keep that directory private and back it up if you need to move your viewer.

Use the matching **3.0.2 preview** host and viewer together. Older hosts must be replaced with a new viewer-created package. The old camera/desktop viewer remains available with `--legacy`; the old host mode has no browser shell.

## Same or different networks

- **Automatic** tries direct LAN first, then Cloudflare, then an independent Pinggy TLS relay. Both internet providers run independently so one failing does not stop the other.
- LAN uses encrypted TCP **2220** plus UDP **2220** for discovery. If broadcast discovery is blocked, enter the host's IPv4 address under Connection options on the listener. Windows Firewall or school Wi-Fi isolation may still block device-to-device access; the app does not change firewall rules.
- Cloudflare uses bundled cloudflared and its automatic QUIC/HTTP2 transport fallback over UDP/TCP **7844**. The independent Pinggy route uses the operating system's **OpenSSH client** (`ssh` and `ssh-keygen`) over TCP **443**. Pinggy forwards TLS without decrypting it; the listener pins the host's signed session certificate. SSH on port 443 is still SSH, so networks restricting traffic to browser HTTPS may block it. If OpenSSH is unavailable, Cloudflare and LAN remain usable.
- The browser only connects to the listener's loopback address. The listener verifies the host certificate for local connections; no browser certificate exception is needed.
- Read-only requests can switch to another authenticated route when the current route fails. The dashboard displays the new route. Interrupted video/audio streams may need Start viewing or Listen again. Commands are never replayed automatically after an error because they may already have executed. Transient initial DNS and gateway failures receive bounded retries.
- Internet discovery uses `ntfy.sh` automatically, using the identity already stored in the private package. No host code or fallback details need to be copied. If this discovery service is blocked, internet discovery can fail even if a relay is available; local discovery/direct LAN can still work. Both relay providers currently share this discovery dependency.
- Pinggy free tunnels expire after 60 minutes. The app detects process exit, reconnects, and advertises a new URL. This can interrupt streams. Free relay services do not provide a guarantee of availability; normal internet access alone cannot guarantee either tunnel service is allowed.

## Shell and authentication

The shell runs as the user who launched the sharing app. It does not elevate privileges or install persistence. The host shows when a shell is active and closes the shell during normal shutdown; programs deliberately detached from that shell may outlive it. Shell history is not saved to the user's usual history file.

Each private host package includes a random 128-bit discovery identity and a password that the viewer also stores. The host starts already paired and rejects attempts to claim it with a new password. Discovery is signed; secrets are not published to ntfy. The settings file and private ZIP grant access to that computer, so share them only with its authorized operator.

The local browser gateway uses a one-use launch token, an HttpOnly SameSite cookie, an explicit control token for changes, an exact loopback Host check, an Origin check, and a limited set of proxy endpoints. The terminal has bounded output retention and an idle timeout. Anyone with the code/password can operate the host with the sharing user's permissions.

## Linux

The Linux build targets x86_64 Linux (Ubuntu 24.04/WSL2 test environment; glibc 2.39 baseline). Desktop capture still requires **X11**, not native Wayland. System audio requires PulseAudio or PipeWire-Pulse and `pactl` / `parec`; these device/session requirements are separate from connection settings. The terminal and listener do not require desktop capture to be enabled.

Extract the private ZIP with an archive manager that preserves executable permissions (for example `unzip`). If a graphical host window is unavailable, `./webcam_server.elf --headless` uses the same prepared settings and prints status. No editing of configuration files is needed.

## Diagnostics and builds

`CheckConnection.exe` / `CheckConnection.elf` runs a generated-media TLS, pairing, shell, and cleanup check. `--self-test` runs the control-center regression suite. `--internet` exercises signed discovery and generated media through a real temporary Cloudflare tunnel. `--relay` tests the independent Pinggy route with Cloudflare absent, including rejection of the wrong TLS certificate. It also runs a harmless shell marker. It never captures a real desktop, microphone, or webcam.

Source: Python 3.12 and the platform folder's requirements. Run `python webcam_server.py` on the host and `python viewer.py` on the listener. Cloudflared must be beside source when running the host from Python; it is bundled in releases. Browser terminal assets are bundled locally and require no CDN.

Build using `camera-desktop-sharing/build.ps1` or `linux/camera-desktop-sharing/build.sh`. Common control-center modules are synchronized with `python sync_control_center.py`.

Run the suites as separate processes:

```text
python -m unittest -v test_control test_profiles
python -m unittest -v test_combined test_cursor   # Windows
python -m unittest -v test_combined test_linux    # Linux
python check_control_center.py
python check_control_center.py --internet
python check_control_center.py --relay
```

See **verification/HANDS-FREE.md** for this update, **verification/REDUNDANCY.md** for the previous transport tests, and **verification/RESULTS.md** for the original preview tests and remaining limits. Use the checksums from the matching release.
