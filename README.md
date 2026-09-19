# ChatGPT Scripts

A collection of scripts and experimental projects built with ChatGPT.

## Screen-sharing proof of concept (PoC)

[`screen-recording/`](screen-recording/) contains a Windows desktop-sharing **proof of concept**, with standalone server and listener executables distributed through GitHub Releases.

The server runs without a banner or console window and provides a system-tray control to stop sharing. The listener chooses a password, discovers the server, and displays its desktop stream. Use this PoC on computers you own or have permission to share.

### Validation and limitations

- Six automated checks cover pairing, authentication, expiry, multipart frame parsing, and viewer cleanup.
- The packaged server and listener streamed 12 real desktop frames at 1600×900 over loopback and shut down cleanly.
- Cloudflare HTTPS connectivity, ntfy discovery, pairing, and authenticated health checks passed.
- Video playback between two separate PCs has not been verified.

This is experimental software, not a production-ready remote-access product. Automatic discovery uses a shared ntfy topic containing the short-lived pairing token; anyone with access to that topic can attempt to claim an unpaired server. The repository and its paired binaries should be shared only with trusted users.

Download `ScreenServer.exe` and `ScreenListener.exe` from Releases. See the [project README](screen-recording/README.md) for usage, rebuilding, and the local executable test.
