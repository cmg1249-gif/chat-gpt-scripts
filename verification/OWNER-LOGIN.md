# RoomCam 3.0.3 preview — owner-authorized tray host

The v2.0.2-style startup experience is restored with a visible system tray icon, a local Stop action and viewer-only credentials. No Tkinter pairing window, host code, first-connection approval or generated host package is needed. The browser dashboard, shell and independent Cloudflare/Pinggy routes remain.

The production host embeds only the owner's public verification key. The matching private credential stays on authorized viewers and is excluded from source, executables and public archives. A new login signs a fresh challenge, binds the destination URL/certificate, and encrypts the disposable API password to the host's challenge key. This prevents public first-claim enrollment, login replay and cross-destination forwarding. Route recovery checks a fresh proof of the existing API password before sending it to an alternate endpoint, preserving an existing shell session when the same host is reachable.

## Verification

Source regression tests pass on Windows and Linux (62 on each platform), including wrong-owner rejection, signed-field tampering, replay and expiration rejection, cross-host proof relay rejection, bounded challenges, encrypted credentials, disabled old enrollment, custom usernames, unauthorized shell rejection, LAN-first/internet fallback, first-ever internet login without local pairing, rejection of generic Cloudflare names, recovery credential protection, forwarded destination/certificate rejection and LAN authorization without hostname DNS. Diagnostic fixtures use disposable test credentials that do not authorize production builds.

The additional Windows media/cursor suite passed 34 checks; Linux media/platform checks passed 33. Native cursor tests now construct explicit Windows cursor fixtures: this automation environment's stock cursor is transparent. The production cursor renderer is unchanged. Arrow, I-beam, monochrome XOR, clipping, cleanup and retention in recordings are checked without moving the real mouse or capturing the real desktop.

Packaged executable, browser and live internet results are recorded in the accompanying owner verification transcripts. Final archive creation verifies exact binary hashes and archive integrity. A separate private audit scans public sources, executables, embedded Python modules and every archive member for the real owner's password and private signing seed; neither is published.

- Both final diagnostic binaries passed all 62 control/security tests. Their generated-media checks verified camera/desktop frames, stereo audio, TLS pin rejection, shell execution and disconnect cleanup without recording actual devices.
- Actual Windows and Linux hosts/viewers passed username/password-only LAN connection and restart using viewer-only saved credentials. Both providers accepted first-ever owner internet logins and executed harmless shell markers. A live primary failure recovered through Pinggy, preserved the current shell and session password, and disconnected successfully while discovery was deliberately unavailable.
- The packaged Linux viewer connected to the actual Windows `webcam_server.exe` over Cloudflare, executed a PowerShell marker and disconnected. No host code or generated host package was used.
- The final Windows browser dashboard connected using its saved credential, opened the host terminal, displayed a harmless command's output and returned cleanly to the connection form after Disconnect. The form and terminal layout were visually inspected. Stylesheets, bundled terminal assets and favicon load locally; the empty data stylesheet import is absent.

## Limits

These checks cannot establish that the school network permits these services or that two physically separate school/college networks work. Internet tests use real external services from the available environment. Discovery is public and can be spoofed or denied; it is not host authentication. Both internet routes share the ntfy service. Automatic discovery assumes one active host for this owner build; several owned hosts can compete for selection. Free provider expiry, network blocking, missing audio devices and Linux desktop-session requirements remain documented in CONTROL-CENTER.md.

The actual Windows tray entry point was verified on the owner PC, including viewer-only authentication, capture/shell initially off and normal shutdown without headless mode. The authorized VirtualBox VM displayed a black screen during the attempted GUI check; a completed VM tray/connection test is not claimed. Its temporary read-only test share was removed. No Windows security setting or firewall rule was changed.
