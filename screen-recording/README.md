# Screen Sharing — Proof of Concept (PoC)

This experimental proof of concept demonstrates password-paired desktop streaming between a Windows server and viewer. It is not production-ready remote-access software.

## Run

1. Copy `ScreenServer.exe` to the Windows PC whose screen you want to share and double-click it.
2. Run `ScreenListener.exe` on the viewing Windows PC. Choose an 8–128 character password when prompted.
3. The viewer discovers the server and opens its live desktop with speaker audio. Select a display from **Monitor**, use **Refresh** after a display change, and select **Mute desktop audio** to silence playback. Press Escape or close the window to stop viewing.
4. To stop the server, right-click its green monitor icon in the Windows notification area and choose **Stop sharing**. Windows may place the icon inside the hidden-icons menu.

The server has **no banner and no console window** by default. Its only UI is the tray icon. It does not install a startup task. Python is bundled into each executable; no Python installation is required on the destination PC. Cloudflare is bundled into the server.

Both computers need outbound internet access to ntfy and Cloudflare. NAT does not require inbound port forwarding. Use the matching v0.2.0 server and listener. Start either first: the listener keeps waiting, and the server renews unclaimed pairing tokens instead of becoming permanently undiscoverable after ten minutes. Restart the server to choose a different password or pair a different viewer. One server per demo is recommended because automatic discovery uses a shared topic. Advanced users can set the same `DESKTOP_STREAM_TOPIC` environment variable on both machines to isolate concurrent demos.

The server retries tunnel startup and discovery failures. If the tunnel process exits, it recreates the tunnel; the listener rediscovers the same running server session using its existing password. Cloudflared handles transient transport interruptions internally. A complete server restart creates a new session and requires restarting the listener. Hover over the tray icon for connection status.

Both programs include Certifi's CA bundle in addition to the operating system's trusted roots. A fresh Windows installation does not need to populate its root store before the discovery service can be verified. Certificate and hostname verification remain enabled. The system clock still needs to be accurate enough for HTTPS certificate validity checks.

Routine advertisements refresh every ten minutes, with immediate updates after pairing or tunnel replacement. The listener polls a fifteen-minute cache window every five seconds while waiting. HTTP 429/503 responses use at least a sixty-second backoff and honor longer `Retry-After` delays. Tunnel-process failure is still checked every two seconds between advertisements.

## Test

Desktop audio captures the sharing computer's default Windows speaker output through WASAPI loopback. It does not capture the microphone. A working Windows playback device is required, including inside a VM. If audio is unavailable, its status appears in the viewer and video continues. Audio and video use separate streams; precise lip synchronization is not provided. When testing both apps on one PC, start the listener with `--mute` to avoid audio feedback.

After the first audio connection, the server keeps a single local capture open for reconnects until **Stop sharing**. Samples are discarded when no audio viewer is connected and are not saved to disk.

Run `CheckConnection.exe --media` from a writable extracted folder to test every connected monitor, the viewer's monitor selector and mute control, and real speaker capture. It plays a quiet test tone and writes `media-test.txt`. This test uses local loopback and does not publish your desktop online.

Double-click `CheckConnection.exe` on an unlocked Windows desktop. It starts the two packaged apps, displays 12 real desktop frames locally, and stops the server after 25 seconds. Results are saved in `connection-test.txt`. This check uses loopback only and does not publish your screen online.

For an internet diagnostic, run `CheckConnection.exe --internet` from PowerShell in the extracted folder. Read `internet-test.txt` when it finishes. This tests a real Cloudflare tunnel, ntfy discovery, authenticated delivery of generated test images and audio, and discovery after replacing the tunnel. It does not transmit desktop images or capture live audio. Allow up to a few minutes.

Run both diagnostics on each demo machine, including the VM. Use an unlocked, logged-in Windows x64 desktop with a working display. A locked session, secure desktop, headless VM or disconnected remote desktop session is outside the tested capture path. A successful local check verifies screen capture and playback on that machine; the internet check verifies its outbound services. Finally run the server on the VM and listener on the physical PC to validate that exact pair. See `VALIDATION.md` for checks performed for this release and remaining environment coverage.

A source build places its executables and diagnostic reports in the bin/ directory.

## Source and rebuild

Use Python 3.12 on Windows x64. In your own virtual environment, install `requirements.txt`, then run `build.ps1 -Python <path-to-python.exe>`. Keep `cloudflared.exe` beside the source; the build bundles it. Run `python -m unittest -v test_stream` for the protocol tests.

The server supports `--local`, `--port`, and optional `--show-banner`. Use `--session-file` and `--stop-after` for local testing. The listener supports `--monitor N`, `--list-monitors`, and `--mute`, plus `--session-file`, `--frames`, and `--headless` for repeatable integration checks. Frame-count checks do not start audio playback.

Connection progress and failures are recorded in `%LOCALAPPDATA%\CodexScreenServer\server.log`, with two rotated backups. Fatal startup failures in tray mode also write `last-error.txt`. Transient failures stay running and retry; the listener prints discovery errors instead of hiding them. Service outages, firewall restrictions and service rate limits still affect availability.

