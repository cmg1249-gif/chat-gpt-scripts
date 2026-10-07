# RoomCam 3.0.1 preview — connection redundancy

October 7, 2026. This update adds an independent internet provider to the existing LAN and Cloudflare routes. It does not promise connectivity on every network.

## What changed

1. Direct encrypted LAN remains the first choice, on TCP 2220. Manual host IPv4 still works when broadcast discovery is blocked. An error opening UDP discovery no longer stops internet fallback.
2. Cloudflare remains available with cloudflared's existing QUIC/HTTP2 protocol fallback on UDP/TCP 7844.
3. An independent Pinggy TLS relay runs alongside Cloudflare using the operating system's OpenSSH client on TCP 443. It uses a disposable generated SSH identity, never the user's private keys or SSH agent. SSH host keys are retained in the app's own known-hosts file; changed keys are rejected. The listener pins the sharing host's signed TLS certificate, so the Pinggy relay does not decrypt application traffic.
4. Initial read-only handshakes retry temporary DNS/network and 502/503/504 failures, with bounded delays. Certificate and authentication failures are not retried as transient errors.
5. Read-only requests can recover through another authenticated route. Shell input and other changing requests are never replayed automatically. The dashboard shows route changes; interrupted media streams may require starting again.
6. **Copy fallback connection details** in the host window supplies signed endpoints directly to the listener's host-code field. This bypasses ntfy discovery. Paste within two minutes. The details contain the session pairing code and must be shared only with the intended listener.

All connection settings remain in the listener. OpenSSH must be available for Pinggy; absent OpenSSH does not stop LAN or Cloudflare.

## Verification

- Windows and Linux source: 30 control regression tests passed on each platform. Tests cover primary-route failure, UDP-discovery failure, copied details bypassing discovery, signature/expiry/certificate rejection, read-only recovery, credential preservation, disconnect races, and no shell-command replay.
- Live independent relay tests passed on both platforms with Cloudflare absent: signed discovery, pairing, 12 camera frames, 12 desktop frames, stereo 48 kHz/997 Hz generated audio, real shell marker, disconnect cleanup, and wrong-certificate rejection.
- A live primary TLS test server was stopped deliberately. An authenticated request recovered through Pinggy while discovery was forced unavailable. Copying signed connection details then paired through the real relay with discovery still unavailable. See `failover-e2e.txt`.
- JavaScript syntax and Git whitespace checks passed.
- Final Windows and Linux diagnostic executables each passed all 30 regression tests and the live Pinggy generated-media/shell/certificate test. Actual host and viewer executables also passed startup, encrypted pairing, shell cleanup, dashboard asset, and browser-bootstrap checks. Linux was checked without the development `LD_LIBRARY_PATH`. Transcripts: `redundancy-packaged-windows-tests.txt`, `redundancy-packaged-windows-relay.txt`, `redundancy-windows-apps.txt`, and the matching Linux files. Archive checksums are provided in the release folder.

The generated-media tests do not capture a real webcam, microphone, person, or desktop. Linux is tested on Ubuntu 24.04/WSL2; its glibc and X11/audio requirements from the original preview still apply. The school network and two physically separate networks were not tested.

## Service limits

Pinggy's free sessions expire after 60 minutes. The existing tunnel supervisor detects process exit, reconnects, and publishes a replacement URL. The test run did not wait an hour to observe a real provider-enforced expiry. Stream interruption during a relay restart remains possible. Neither public free tunnel service offers this app guaranteed availability.

TCP port 443 availability alone is insufficient: Pinggy's host connection carries SSH, which a network allowing only browser HTTPS can still block. Cloudflare, Pinggy, DNS, and discovery endpoints can each be filtered. The app does not modify firewall rules. A VPN, proxy, or school policy can also affect access.

Provider references: [Cloudflare tunnel connectivity](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/), [Pinggy SSH usage](https://pinggy.io/docs/usages/), [Pinggy TLS forwarding](https://pinggy.io/docs/tls_tunnels/), [Pinggy free-session limits](https://pinggy.io/help/).

Use the matching 3.0.1 preview host and listener. GitHub release tag: `v3.0.1` (prerelease).
