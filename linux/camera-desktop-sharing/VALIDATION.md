# Linux build validation — 2026-09-27

Target: current Arch Linux **x86_64**, with an X11 desktop and PulseAudio or PipeWire-Pulse. These are a Linux adaptation of the v2.0.2 Windows source, not renamed Windows binaries.

Build/test environment: Ubuntu 24.04 under WSL2, x86_64, glibc 2.39, Python 3.12.3, PyInstaller 6.22.3. The build uses an older glibc baseline than current Arch; no claim is made for older Linux distributions, ARM64, or native Wayland desktop capture.

## Checks performed

- 33 source regression checks: pairing and authentication, signed discovery validation, audio mixing/resampling/reconnect behavior, recording and frame-size changes, Linux speaker-monitor selection, failure when no monitor exists, system-tool library isolation, and X11/Wayland checks.
- All three built files have the ELF signature, are x86_64 Linux executables, and successfully display their command-line help.
- The packaged `CheckConnection.elf --self-test` passes the same 33 checks, including recording through its bundled encoder.
- Packaged sharing host starts on loopback with an ephemeral port, accepts viewer-owned password pairing, enumerates the disposable X11 display, and sends 12 decoded frames at 1024×768.
- Packaged viewer receives frames from that packaged host in both headless mode and a GUI on Xvfb. Tests use a disposable virtual desktop, muted playback, and a three-second viewer run.
- The sharing host is stopped after testing. No real camera, microphone, or user's desktop is transmitted in these checks.

## Limits of validation

The tests were performed in Ubuntu/WSL2 with Xvfb, **not on a physical Arch desktop**. Physical webcam/microphone devices, speaker playback and monitor capture through a live Arch PulseAudio/PipeWire session, multi-monitor layouts, optional tray integration, and Linux-to-Windows pairing have not been exercised on real hardware. Internet tunnel/discovery integration was not rerun for these Linux binaries. Shared protocol behavior and generated media are covered by the regression checks, but those checks do not establish every device or network combination.

X11 is required for desktop capture. Wayland portal-based capture is not implemented. Desktop cursor capture is provided by MSS/XFixes; visual cursor appearance on a physical Arch desktop is not verified. Use the default foreground host and Ctrl+C to stop sharing; optional `--tray` requires a compatible system tray.

`SHA256SUMS.txt` inside the Linux download covers its three ELF executables. `LINUX_SHA256SUMS.txt` attached to the GitHub release covers the complete archive.
