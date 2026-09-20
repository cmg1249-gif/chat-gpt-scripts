# v0.2.0 — Desktop audio and monitor selection

The viewer now plays the sharing computer's default speaker output and provides a monitor selector, display refresh, and a desktop-audio mute control. Missing audio hardware is reported without interrupting video. Audio uses Windows WASAPI speaker loopback; microphones are not captured.

Audio connections share one device capture with independent bounded buffers. This avoids reopening the virtual sound card while an earlier tunnel request is still closing. Device failures reach the viewer and can be retried without stopping video.

Use the matching server and listener from this release. Stop the old server through **Stop sharing** in its tray menu before replacing it. Close the viewer with Escape or its window close button. For same-PC viewing, start with `ScreenListener.exe --mute` to prevent audio feedback.

`CheckConnection.exe --media` tests connected displays, monitor switching, and speaker capture with a quiet test tone. Run it from a writable extracted folder and read `media-test.txt`. The internet diagnostic now checks generated audio as well as video before and after tunnel replacement.

Thirty-four automated checks pass. Packaged tests on the physical Windows PC decoded both actual monitors (2560×1440 and 1920×1080), switched the viewer between them, exercised mute controls, and detected a known tone through actual WASAPI capture and authenticated transport. The public tunnel test delivered generated stereo audio and video before and after replacing the tunnel. See `VALIDATION.md` for VM coverage.

Audio and video are separate streams without precise lip synchronization. Audio requires a working Windows playback device in the sharing computer or guest VM. The existing PoC discovery and service-availability limitations below still apply.

## v0.1.1 — Discovery and reconnection fixes

The server no longer becomes permanently undiscoverable when its initial ten-minute pairing window expires. It renews unclaimed tokens, retries discovery and tunnel startup failures, and recreates the tunnel if its process exits. The viewer waits for a reachable server, reports network errors, and rediscovers the same session after a tunnel replacement. Reconnect advertisements are authenticated before credentials are sent. Repeating a successful pairing request with the same token and password is safe when its original response was lost.

Download **both** `ScreenServer.exe` and `ScreenListener.exe` from this release, or extract `Screen_Recording_Codex.zip`. Stop the old server using its tray menu before launching the replacement. Run the new listener instead of an older copy of `script1.py`.

- The server retains its tray status and **Stop sharing** control. It writes rotating diagnostic logs to `%LOCALAPPDATA%\CodexScreenServer\server.log`.
- The listener retries short password entry and explains discovery failures.
- Discovery polls and advertisements are reduced, with `Retry-After` backoff for service rate limits. A quiet server publishes every ten minutes while tunnel-process monitoring remains responsive.
- Both programs bundle trusted CA certificates to fix `unable to get local issuer certificate` on fresh Windows VMs, while retaining certificate and hostname verification and locally installed trusted roots.
- `CheckConnection.exe` tests packaged desktop capture and playback locally. Place it beside both executables.
- `CheckConnection.exe --internet` tests public connectivity and tunnel replacement with synthetic images; it writes `internet-test.txt`.
- Cloudflared 2026.9.1 is bundled. No Python installation or inbound NAT port forwarding is required on the destination Windows x64 machines.

Twenty-one automated regression tests pass, including HTTPS trust with an empty operating-system certificate store. A live Cloudflare/ntfy test passed video delivery and rediscovery after tunnel replacement. See `VALIDATION.md` in the bundle for final executable test results and environment coverage.

Validated on the actual demo pair: **Win11-DuckyLab with VirtualBox NAT streamed 12 real desktop frames at 1021×748 to the packaged listener on the physical Windows PC.** The VM's missing certificate issuer was reproduced in its log, fixed with the bundled CA trust, and the final build passed discovery, pairing and video delivery. The VM test decoded frames without opening a viewer window; physical-PC loopback testing also exercised display.

This remains a PoC dependent on internet access, service availability and quotas. A full server restart requires restarting the viewer. Initial discovery still uses a shared public topic: use one demo server at a time and a strong unique password; optional matching `DESKTOP_STREAM_TOPIC` values isolate separate demos but do not replace access control. Other Windows versions, locked sessions and arbitrary VM/display configurations have not been validated.
