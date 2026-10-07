# RoomCam Control Center — 3.0.3 preview

This owner build restores the v2.0.2 setup experience with a browser dashboard, camera/desktop and audio controls, an interactive PowerShell or Bash terminal, and independent internet routes. Windows and Linux hosts and viewers can be mixed.

## Start

1. On a sharing computer you are authorized to administer, download and run **webcam_server.exe** (Windows) or **webcam_server.elf** (Linux). It shows a system tray icon with activity status and **Stop sharing and close shell**. No pairing window, code, approval click or viewer-generated host package is required. Camera, microphone, desktop sound and shell start off.
2. On the viewing computer, run **viewer.exe** or **viewer.elf**. Enter a username and your **private connection password**, then click **Connect to computer**. On the owner's configured viewer, leave the password blank to use the privately saved credential. This also works for a first-ever internet connection.
3. Use **Start viewing**, the audio buttons, or **Terminal → Open terminal**. Shell commands execute on the sharing computer with the sharing user's permissions.
4. Use **Disconnect** to stop capture and close the shell, or use **Stop** from the host's tray. Closing a browser tab alone does not stop the host. The shell closes after 15 minutes without keyboard input.

The public downloads contain the owner's **public verification key only**. The private credential is supplied separately to the owner and never published. These executables accept only that owner's credential; arbitrary newly chosen passwords do not work. An additional authorized viewer can enter the same private credential in its password field, or privately store it as `owner-password.txt` in `%LOCALAPPDATA%/RoomCam/listener` (Windows) or `~/.local/share/RoomCam/listener` (Linux). No credential file belongs on the sharing computer. Keep the private credential and backups private. Changing the owner key requires a matching host build.

Use matching **3.0.3 preview** applications. The host ignores adjacent 3.0.2 private-package settings in its normal control-center mode. Old code/package endpoints remain for legacy diagnostic fixtures; production owner hosts reject first-claim pairing.

## Connections

- **Automatic** tries LAN first, then Cloudflare and an independent Pinggy encrypted relay. Both providers run independently. Generic addresses such as `trycloudflare.com` are rejected.
- LAN uses encrypted TCP **2220** and UDP **2220** discovery. An optional host IPv4 address can be entered in the viewer if broadcast discovery is blocked. Firewall rules and school Wi-Fi isolation can still prevent LAN access.
- Cloudflare has QUIC/HTTP2 transport fallback over UDP/TCP **7844**. Pinggy uses the system's OpenSSH client (`ssh` and `ssh-keygen`) on TCP **443**, with a disposable SSH identity. The app does not install OpenSSH. The relay forwards host TLS; no browser certificate exception is needed. Networks allowing only browser HTTPS may still block SSH on 443.
- Both internet providers currently use **ntfy.sh** for discovery. This is a remaining shared dependency. If discovery or both relays are blocked, ordinary internet access alone does not guarantee a connection. Free Pinggy tunnels expire after an hour; the app reconnects and advertises a new address. Interrupted audio/video streams may need restarting.
- Read-only operations can recover through another route. An authenticated proof from the current host permits reuse of the current session without closing its shell. A host restart requires fresh authorization. Shell commands are never replayed automatically after a connection error.

## Authorization

The viewer signs a fresh, one-use host challenge with Ed25519. A separately generated session password is encrypted to that challenge's X25519 key using HKDF and AES-GCM, and the ciphertext is included in the signature. The signature binds the destination URL and host certificate. The host rejects public tunnel destinations that it does not own; the viewer checks that LAN/Pinggy terminate TLS at the same host supplying the challenge. The private owner credential never leaves the viewer. Wrong signatures, changed payloads, expired challenges and replays are rejected. Each new login rotates the host's API password and closes previous capture and shell activity.

Discovery records are public candidates, not proof of a host's identity. They can be spoofed or blocked. They contain neither the owner credential nor an API password. A spoofed discovery endpoint cannot relay a login proof to another host and obtain its encrypted API password. The local gateway uses a one-use launch token, HttpOnly SameSite cookie, CSRF token, loopback Host/Origin checks and a restricted proxy. The tray makes capture/shell activity visible and provides local Stop. There is no elevation or persistence installation.

Automatic discovery is intended for one active sharing host per owner build. With several hosts running under the same credential, it may choose another owned host; stop other hosts or use the explicit LAN IPv4 option. Named selection of multiple internet hosts is not implemented. Connecting a second viewer to the same host replaces its previous session and closes its old capture/shell.

## Linux and diagnostics

Linux binaries target x86_64 Ubuntu 24.04/WSL2, glibc 2.39. Desktop capture needs X11; native Wayland capture is unsupported. System audio requires PulseAudio/PipeWire-Pulse and `pactl` / `parec`. A VM with no audio device may return an explicit audio-backend error.

Extract the Linux bundle with executable permissions preserved. Normal host operation requires a working tray. `--headless` is an explicit command-line diagnostic option. `CheckConnection` exercises generated media without capturing a real camera, desktop or microphone; `--self-test` runs regression tests, `--internet` tests Cloudflare and `--relay` tests Pinggy. See **verification/OWNER-LOGIN.md** for this release's checks and limits, and **verification/REDUNDANCY.md** for the earlier transport checks.

Source requires Python 3.12 and the platform requirements. Build with `camera-desktop-sharing/build.ps1` or `linux/camera-desktop-sharing/build.sh`; synchronize common modules with `python sync_control_center.py`.
