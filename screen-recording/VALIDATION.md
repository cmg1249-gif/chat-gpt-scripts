# v0.2.0 validation — 2026-09-20

## Completed on the development PC

- Windows 11 x64, Python 3.12 build environment, Cloudflared 2026.9.1.
- 34 regression tests passed, including network retries, stale advertisements, pairing renewal, duplicate pairing after a lost response, VM clock differences, wrong credentials, reconnect address authentication, fragmented frames and viewer cleanup. Media checks cover authenticated endpoints, selected-monitor capture, invalid monitor IDs, unavailable audio, stream cleanup, speaker-loopback enforcement, stereo conversion, audio format validation, and playback worker mute/error behavior. The certificate regression test suppresses loading OS roots and confirms bundled trust remains populated with certificate and hostname verification required.
- Final packaged `CheckConnection.exe --media`: the packaged listener decoded 12 actual frames from each of two physical monitors, at 2560×1440 and 1920×1080. The viewer's actual selection callback switched capture from monitor 1 to monitor 2 and exercised mute/unmute state. The test window remained hidden to avoid disturbing the user's cursor.
- That same packaged media test detected a quiet 997 Hz tone through real default-speaker playback, WASAPI loopback capture, authenticated HTTP, and received stereo PCM at 48000 Hz. The server exited cleanly. The hardware was an Audient EVO4 output; no microphone was opened.
- Final packaged `CheckConnection.exe --internet`: a real Cloudflare HTTPS tunnel and ntfy discovery delivered 12 synthetic 640×360 frames and a generated 997 Hz stereo tone. The tunnel was closed and replaced, the viewer discovered the replacement address with the same session and credentials, and received another 12 frames and the tone.
- Internet diagnostics used generated images and audio. Physical desktop capture and speaker-loopback testing used local loopback without publishing a public tunnel.

## VM test

**PASS:** Win11-DuckyLab (Windows 11 Home) in VirtualBox, adapter 1 using NAT, streamed 12 actual desktop frames at 1021×748 to the packaged listener on the physical development PC. The final server and listener performed public discovery, password pairing and HTTPS video delivery. This test used headless decoding on the receiving PC so it did not interfere with the user's cursor.

The guest's first attempt identified a missing certificate issuer in its fresh Windows trust store, blocking ntfy advertisement publishing. Both programs now supplement OS trust with a bundled Certifi CA file. HTTPS to ntfy also passed with OS root loading disabled in the test environment; certificate and hostname checks remained enabled. Subsequent testing encountered service rate limiting, leading to slower polling and `Retry-After` handling. All three final executable archives were checked for the bundled CA file.

The final v0.2.0 build also passed this VM video test and returned the guest's monitor list. With the original AC97 configuration, Windows exposed no usable speaker-output device: the server reported audio unavailable while video continued. After an orderly guest shutdown, the virtual controller was changed to Intel HD Audio with playback enabled. The final packaged server delivered the guest's known 997 Hz speaker tone as 44100 Hz stereo PCM across the public HTTPS tunnel (measured RMS 471.5), and passed three consecutive audio stream reopen checks. These tests retained metrics only, not captured audio or screenshots.

An earlier feature build intermittently returned a Windows audio-driver error when reopening capture. The final server shares one device capture across viewer connections, with separate bounded queues; regression tests verify shared capture, cleanup, and recovery after a device startup failure. The final VM reconnect checks passed without this error.

NAT settings and Windows certificate/security settings were not changed. The guest had one monitor, so multiple-monitor switching was tested on the physical PC. The test does not demonstrate other hypervisors or guest operating systems.

After testing, the user stopped the server and tone and the original virtual DVD was restored. Intel HD Audio and speaker playback remain enabled for future demos; microphone capture remains disabled.

## Reproduce

Extract the bundle to a writable folder on an unlocked Windows x64 desktop. Run `CheckConnection.exe` and read `connection-test.txt`. Run `CheckConnection.exe --media` for local monitor and speaker checks, and read `media-test.txt`. Run `CheckConnection.exe --internet` from PowerShell and read `internet-test.txt`. Then run `ScreenServer.exe` on the sharing machine and `ScreenListener.exe` on the viewing machine. Use the matching release binaries on both machines.

The tests do not establish operation on locked/secure desktops, disconnected RDP sessions, every Windows version, arbitrary display drivers, or during Cloudflare/ntfy outages or quota restrictions. A full server restart requires a new viewer pairing. Keep the server's tray Stop sharing control accessible.
