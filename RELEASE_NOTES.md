# v0.1.1 — Discovery and reconnection fixes

The server no longer becomes permanently undiscoverable when its initial ten-minute pairing window expires. It renews unclaimed tokens, retries discovery and tunnel startup failures, and recreates the tunnel if its process exits. The viewer waits for a reachable server, reports network errors, and rediscovers the same session after a tunnel replacement. Reconnect advertisements are authenticated before credentials are sent. Repeating a successful pairing request with the same token and password is safe when its original response was lost.

Download **both** `ScreenServer.exe` and `ScreenListener.exe` from this release, or extract `Screen_Recording_Codex.zip`. Stop the old server using its tray menu before launching the replacement. Run the new listener instead of an older copy of `script1.py`.

- The server retains its tray status and **Stop sharing** control. It writes rotating diagnostic logs to `%LOCALAPPDATA%\CodexScreenServer\server.log`.
- The listener retries short password entry and explains discovery failures.
- `CheckConnection.exe` tests packaged desktop capture and playback locally. Place it beside both executables.
- `CheckConnection.exe --internet` tests public connectivity and tunnel replacement with synthetic images; it writes `internet-test.txt`.
- Cloudflared 2026.9.1 is bundled. No Python installation or inbound NAT port forwarding is required on the destination Windows x64 machines.

Seventeen automated regression tests pass. A live Cloudflare/ntfy test passed video delivery and rediscovery after tunnel replacement. See `VALIDATION.md` in the bundle for final executable test results and environment coverage.

The exact VM-to-physical-PC demo pair has not been accessible for testing. Run both diagnostics on an unlocked Windows desktop in the VM and on the physical PC, then test the intended pair. This remains a PoC dependent on internet access, service availability and quotas. A full server restart requires restarting the viewer. Initial discovery still uses a shared public topic: use one demo server at a time and a strong unique password; optional matching `DESKTOP_STREAM_TOPIC` values isolate separate demos but do not replace access control.
