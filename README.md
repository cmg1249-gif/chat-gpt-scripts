# ChatGPT Scripts

A collection of scripts and experimental projects built with ChatGPT.

## Screen-sharing proof of concept (PoC)

[`screen-recording/`](screen-recording/) contains a Windows desktop-sharing **proof of concept**, with standalone server and listener executables distributed through GitHub Releases.

The server runs without a banner or console window and provides a system-tray control to stop sharing. The listener chooses a password, discovers the server, and displays its desktop stream. Use this PoC on computers you own or have permission to share.

### Validation and limitations

- Seventeen automated checks cover pairing, authentication, retries, delayed discovery, VM clock differences, reconnect address verification, frame parsing, and viewer cleanup.
- The release includes local capture/playback and internet connectivity diagnostics. See [validation details](screen-recording/VALIDATION.md) for the tested artifacts and environments.
- A live internet test verifies Cloudflare, ntfy, pairing, synthetic video delivery, and rediscovery after replacing the tunnel.
- A VM-to-physical-PC run has not been verified from this development environment; run the included diagnostics and test that pair before the demo.

This is experimental software, not a production-ready remote-access product. Automatic discovery uses a shared ntfy topic containing the short-lived pairing token; anyone with access to that topic can attempt to claim an unpaired server. The repository and its paired binaries should be shared only with trusted users.

Download `ScreenServer.exe` and `ScreenListener.exe` from Releases. See the [project README](screen-recording/README.md) for usage, rebuilding, and the local executable test.
