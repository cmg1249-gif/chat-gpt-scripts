# RoomCam 3.0.2 preview — viewer-prepared hosts

October 7, 2026. Connection setup now happens in the viewer. Create a private host package there, extract it on the sharing computer, and run the host. No code, password, address, or fallback details need to be entered or copied back from the sharing computer.

## Changes

- The viewer saves a separate random discovery identity and password for each named computer. It packages the matching executable with those private settings. A prepared host starts already authenticated; its password cannot be replaced by first-claim pairing.
- Saved settings survive restarting the host and viewer. The host status window remains visible and retains its Stop button. Camera, microphone, desktop audio, and shell remain off until enabled from the viewer.
- Windows and Linux viewers support creating packages for either platform. Bundles include their own platform's host binary. Missing binaries are downloaded from this exact release and checked against its SHA-256 manifest. The Linux host binary is also published individually for this purpose.
- The dashboard no longer asks for a host code or fallback details. Its empty stylesheet import has been removed, its favicon is bundled, and terminal polling stops immediately when Disconnect or Close shell is clicked. In-flight polling responses are ignored after closure.
- A desktop-audio HTTP 503 remains an explicit device/backend error. A VM without an available loopback device may return it; hiding that failure would incorrectly report working audio.

## Verification

- Forty regression tests passed in each platform's diagnostic executable. Coverage includes saved-profile persistence, independent identities, invalid settings, path traversal rejection, private-package authentication/CSRF checks, metadata without credentials, executable permissions, tampered-download rejection, and saved-ID-only connections, in addition to the existing transport/shell tests.
- `check_handsfree.py` uses the actual packaged viewer to create and download a private host ZIP. It extracts and starts that actual host without supplying credentials as arguments, connects using only the saved computer ID, executes a harmless shell marker, confirms capture is off, disconnects, restarts both applications, and reconnects. Local discovery supplies the host address automatically.
- Windows and Linux both completed this flow, including restarting both applications. Windows connected through real Cloudflare and Linux through the independent Pinggy encrypted relay using only the saved computer. Transcripts: `handsfree-windows.txt` and `handsfree-linux.txt`.
- A real browser exercised the packaged Windows dashboard: package creation, saved-computer connection, PowerShell output (`BROWSER_OK`), and disconnect with terminal polling active. The disconnected dashboard showed no error. Its form and terminal layout were visually inspected.
- Final executable smoke checks assert the new setup form, absence of the old code field, absence of the empty CSS import, successful favicon and bundled-asset requests, authenticated browser bootstrap, host startup, shell execution, and cleanup.
- The Linux diagnostic also checks generated camera/desktop frames and stereo 48 kHz/997 Hz audio through local TLS, shell execution, disconnect cleanup, and wrong-certificate rejection, without a development `LD_LIBRARY_PATH`.
- Public archive contents and binary SHA-256 values are verified by `package_release.py`. Private host ZIPs and viewer profiles are temporary test data and are not published.

## Limits

The school network and two physically separate networks were not available for testing. Internet tests use real external relay connections from this test environment. Actual camera/microphone recording was not needed for these tests; generated media avoids capturing private content. A VM audio failure does not establish that physical-device audio is broken or working.

LAN, Cloudflare, and Pinggy remain available, but both internet routes use ntfy discovery. If that service or both relays are blocked, internet connectivity alone is insufficient. The manual copy-back fallback from 3.0.1 is no longer part of the hands-free interface. Interrupted streams may need restarting. The previous release's live provider-failover tests and service limits remain documented in `REDUNDANCY.md`; this update does not claim an hour-long free-relay expiry test.

Linux targets x86_64 Ubuntu 24.04/WSL2 (glibc 2.39); native Wayland capture is unsupported, and system audio needs an available PulseAudio/PipeWire-Pulse session. ZIP extraction must preserve Linux executable permissions. Use the matching 3.0.2 viewer and its newly generated host packages.
