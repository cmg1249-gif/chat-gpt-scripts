# Screen Sharing — Proof of Concept (PoC)

This experimental proof of concept demonstrates password-paired desktop streaming between a Windows server and viewer. It is not production-ready remote-access software.

## Run

1. Copy `bin/ScreenServer.exe` to the Windows PC whose screen you want to share and double-click it.
2. Run `bin/ScreenListener.exe` on the viewing Windows PC. Choose an 8–128 character password when prompted.
3. The viewer discovers the server and opens its live desktop. Press Q or Escape, or close the video window, to stop viewing.
4. To stop the server, right-click its green monitor icon in the Windows notification area and choose **Stop sharing**. Windows may place the icon inside the hidden-icons menu.

The server has **no banner and no console window** by default. Its only UI is the tray icon. It does not install a startup task. Python is bundled into each executable; no Python installation is required on the destination PC. Cloudflare is bundled into the server.

Both computers need internet access for automatic discovery and Cloudflare tunneling. Start the listener within ten minutes of starting the server. Restart the server to pair a new viewer or change the password. This build has a separate discovery topic and uses local port 8766, so use this server and listener together rather than mixing them with another copy.

## Test

Double-click `bin/CheckConnection.exe` on an unlocked Windows desktop. It starts the two packaged apps, displays 12 real desktop frames locally, and stops the server after 25 seconds. Results are saved in `bin/connection-test.txt`. This check uses loopback only and does not publish your screen online.

`unit-test-results.txt` records six automated protocol/authentication checks. The framing check uses a synthetic JPEG; the executable integration test uses actual desktop capture. `internet-test-results.txt` records a successful Cloudflare HTTPS connection, ntfy discovery, pairing, and authenticated health request. Internet video playback between two separate PCs has not been tested here.

## Source and rebuild

Use Python 3.12 on Windows x64. In your own virtual environment, install `requirements.txt`, then run `build.ps1 -Python <path-to-python.exe>`. Keep `cloudflared.exe` beside the source; the build bundles it. Run `python -m unittest -v test_stream` for the protocol tests.

The server supports `--local`, `--port`, and optional `--show-banner`. Use `--session-file` and `--stop-after` for local testing. The listener supports `--session-file`, `--frames`, and `--headless` for repeatable integration checks.

Startup failures in tray mode are written to `%LOCALAPPDATA%\CodexScreenServer\last-error.txt`.

The requested Ducky Cam Room GitHub comparison is pending the repository URL; this copy is based on the supplied Python files.

