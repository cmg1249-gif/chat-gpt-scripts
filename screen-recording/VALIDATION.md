# v0.1.1 validation — 2026-09-20

## Completed on the development PC

- Windows 11 x64, Python 3.12 build environment, Cloudflared 2026.9.1.
- 21 regression tests passed, including network retries, stale advertisements, pairing renewal, duplicate pairing after a lost response, VM clock differences, wrong credentials, reconnect address authentication, fragmented frames and viewer cleanup. The certificate regression test suppresses loading OS roots and confirms bundled trust remains populated with certificate and hostname verification required.
- Final packaged `CheckConnection.exe`: the packaged server captured and the packaged listener decoded/displayed 12 actual desktop frames at 1600×900 over loopback. The server then exited cleanly.
- Final packaged `CheckConnection.exe --internet`: a real Cloudflare HTTPS tunnel and ntfy discovery delivered 12 synthetic 640×360 frames. The tunnel was closed and replaced, the viewer discovered the replacement address with the same session and credentials, and decoded another 12 frames.
- Internet diagnostics used generated images, not desktop screenshots. Local capture testing did not publish a public tunnel.

## VM test

**PASS:** Win11-DuckyLab (Windows 11 Home) in VirtualBox, adapter 1 using NAT, streamed 12 actual desktop frames at 1021×748 to the packaged listener on the physical development PC. The final server and listener performed public discovery, password pairing and HTTPS video delivery. This test used headless decoding on the receiving PC so it did not interfere with the user's cursor.

The guest's first attempt identified a missing certificate issuer in its fresh Windows trust store, blocking ntfy advertisement publishing. Both programs now supplement OS trust with a bundled Certifi CA file. HTTPS to ntfy also passed with OS root loading disabled in the test environment; certificate and hostname checks remained enabled. Subsequent testing encountered service rate limiting, leading to slower polling and `Retry-After` handling. All three final executable archives were checked for the bundled CA file.

The VM's original virtual DVD was restored after the user stopped the server. NAT settings and Windows certificate/security settings were not changed. The test does not demonstrate other hypervisors or guest operating systems.

## Reproduce

Extract the bundle to a writable folder on an unlocked Windows x64 desktop. Run `CheckConnection.exe` and read `connection-test.txt`. Run `CheckConnection.exe --internet` from PowerShell and read `internet-test.txt`. Then run `ScreenServer.exe` on the sharing machine and `ScreenListener.exe` on the viewing machine. Use the matching release binaries on both machines.

The tests do not establish operation on locked/secure desktops, disconnected RDP sessions, every Windows version, arbitrary display drivers, or during Cloudflare/ntfy outages or quota restrictions. A full server restart requires a new viewer pairing. Keep the server's tray Stop sharing control accessible.
