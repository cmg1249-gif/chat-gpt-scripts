# ChatGPT Scripts

A collection of scripts and experimental projects built with ChatGPT.

## Screen-sharing proof of concept (PoC)

[`screen-recording/`](screen-recording/) contains a Windows desktop-sharing **proof of concept**, with standalone server and listener executables distributed through GitHub Releases.

The server runs without a banner or console window and provides a system-tray control to stop sharing. The listener chooses a password, discovers the server, and displays its desktop stream with speaker audio, a monitor selector, and a mute control. Use this PoC on computers you own or have permission to share.

### Validation and limitations

- Thirty-four automated checks cover bundled certificate trust, pairing, authentication, retries, delayed discovery, VM clock differences, reconnect address verification, frame parsing, monitor selection, audio handling, and viewer cleanup.
- The release includes local capture/playback and internet connectivity diagnostics. See [validation details](screen-recording/VALIDATION.md) for the tested artifacts and environments.
- Packaged physical-PC tests verify capture from two real monitors, viewer switching, mute controls, and real speaker-loopback capture. A live internet test verifies generated video and audio before and after replacing the tunnel.
- Win11-DuckyLab (Windows 11, VirtualBox NAT) streamed 12 real desktop frames at 1021×748 to the packaged listener on the physical Windows PC. The missing-root-certificate failure found in that guest was fixed and retested successfully.

This is experimental software, not a production-ready remote-access product. Automatic discovery uses a shared ntfy topic containing the short-lived pairing token; anyone with access to that topic can attempt to claim an unpaired server. The repository and its paired binaries should be shared only with trusted users.

Download `ScreenServer.exe` and `ScreenListener.exe` from Releases. See the [project README](screen-recording/README.md) for usage, rebuilding, and the local executable test.
