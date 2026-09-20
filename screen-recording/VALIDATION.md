# v0.1.1 validation — 2026-09-20

## Completed on the development PC

- Windows 11 x64, Python 3.12 build environment, Cloudflared 2026.9.1.
- 17 regression tests passed, including network retries, stale advertisements, pairing renewal, duplicate pairing after a lost response, VM clock differences, wrong credentials, reconnect address authentication, fragmented frames and viewer cleanup.
- Final packaged `CheckConnection.exe`: the packaged server captured and the packaged listener decoded/displayed 12 actual desktop frames at 1600×900 over loopback. The server then exited cleanly.
- Final packaged `CheckConnection.exe --internet`: a real Cloudflare HTTPS tunnel and ntfy discovery delivered 12 synthetic 640×360 frames. The tunnel was closed and replaced, the viewer discovered the replacement address with the same session and credentials, and decoded another 12 frames.
- Internet diagnostics used generated images, not desktop screenshots. Local capture testing did not publish a public tunnel.

## VM test

The intended test guest is Win11-DuckyLab in VirtualBox, with adapter 1 set to NAT. Its cross-machine test is pending. Do not interpret the development-PC checks as proof of VM-to-PC video delivery.

## Reproduce

Extract the bundle to a writable folder on an unlocked Windows x64 desktop. Run `CheckConnection.exe` and read `connection-test.txt`. Run `CheckConnection.exe --internet` from PowerShell and read `internet-test.txt`. Then run `ScreenServer.exe` on the sharing machine and `ScreenListener.exe` on the viewing machine. Use the matching release binaries on both machines.

The tests do not establish operation on locked/secure desktops, disconnected RDP sessions, every Windows version, arbitrary display drivers, or during Cloudflare/ntfy outages or quota restrictions. A full server restart requires a new viewer pairing. Keep the server's tray Stop sharing control accessible.
