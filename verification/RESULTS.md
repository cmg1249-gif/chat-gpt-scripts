# Verification record — RoomCam 3.0.0 preview

Test environment: Windows x64 and Ubuntu 24.04 x86_64 in WSL2, October 6–7, 2026. These are local preview builds, not the existing GitHub v2.x assets.

## Confirmed findings in v2.x

- The Cloudflare parser could accept `https://api.trycloudflare.com` from an error message as a tunnel address. The new parser rejects the API hostname, the bare domain, and other nongenerated addresses.
- The old tunnel flow could report readiness before Cloudflare registered a connection. The new flow waits for registration and preserves failure diagnostics.
- The v2.0.1 and v2.0.2 connection, discovery, viewer, and Windows host source files compared were identical. The version difference does not establish the cause of the school failure.
- The exact school failure remains unconfirmed without its original logs or a repeat test on that network. A successful SSH connection to Bandit on port 2220 does not establish that LAN traffic, HTTPS discovery, or Cloudflare tunnel traffic is allowed.

## Checks performed

- Windows and Linux control regression suites: 20 tests each, including pairing, signed discovery, certificate validation, authentication, CSRF/Origin/Host checks, tunnel error handling, interactive shell state, Ctrl+C, input limits, and cleanup.
- Existing Windows media/cursor suites: 34 tests passed. Existing Linux media/platform suites: 33 tests passed.
- Generated-media end-to-end checks: TLS pairing, incorrect-code rejection, camera and desktop streams (12 frames each, 640×360), stereo 48 kHz audio with a verified 997 Hz tone, shell output, and disconnect cleanup.
- A real temporary Cloudflare tunnel exercised signed internet discovery and media/shell transport. Linux listener → Windows test host and Windows listener → packaged Linux test host both passed.
- Actual browser checks: pairing, generated video preview, terminal input/output, shell close, stop capture, disconnect, and browser console inspection. Screenshot: `control-center.png`.
- Actual host/listener executable startup checks use local diagnostic mode and verify encrypted pairing, shell output, bundled dashboard assets, browser bootstrap, and authenticated connection status.
- Windows packaging includes the required pywinpty console helpers. Linux packaging includes PortAudio and is checked with the development `LD_LIBRARY_PATH` removed.

Final packaged test transcripts are saved beside this record. The release archive hashes are in `release-v3.0.0-preview/SHA256SUMS.txt`.

## Limits

- Generated video/audio verifies the application pipeline without recording a real person, webcam, microphone, or desktop. Physical capture devices and drivers were not revalidated by these tests.
- Cross-platform internet tests used Windows and WSL on this machine through public Cloudflare tunnels. Two physically separate networks and the school network were not tested.
- Linux testing covers Ubuntu 24.04/WSL2. The binary requires compatible x86_64 Linux/glibc (2.39 baseline). Desktop capture requires X11; system audio requires a working PulseAudio/PipeWire-Pulse session and its tools.
- Port 2220 is the direct LAN port. Internet mode still depends on Cloudflare and ntfy connectivity. The application cannot guarantee access through a network that blocks those services.
- One final Windows internet attempt reached registered-tunnel and signed-discovery success, then failed to resolve the newly generated Cloudflare hostname. A second attempt using the same binary passed all checks with a new tunnel. Both outcomes are preserved in `windows-internet-dns-failure.txt` and `windows-packaged-internet.txt`. This is an observed intermittent failure, not proof of what happened at school.
- Use the new host and listener together; v3 pairing is incompatible with v2 hosts. This record describes the original local preview; see REDUNDANCY.md for the v3.0.1 release update.

## Recheck at school

Run `CheckConnection.exe --internet` (Windows) or `./CheckConnection.elf --internet` (Linux) from a terminal. It uses generated media and a harmless shell marker, then closes its test tunnel. Save its output if it fails; that distinguishes tunnel creation, discovery, pairing, media, and shell failures without assuming that a completed download means connectivity succeeded.
