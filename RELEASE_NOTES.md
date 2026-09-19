# v0.1.0 — Screen Sharing PoC

Initial proof-of-concept release of the Windows screen-sharing server and listener.

- `ScreenServer.exe`: desktop-sharing server with no banner or console window; system-tray Stop sharing control.
- `ScreenListener.exe`: password-paired viewer with automatic discovery and live video playback.
- `CheckConnection.exe`: local executable integration check; place it beside both executables.
- `Screen_Recording_Codex.zip`: complete source, executable, and test-results bundle.

Validated: six automated protocol checks; 12 real desktop frames at 1600×900 between the packaged executables over loopback; clean shutdown; Cloudflare HTTPS connectivity; ntfy discovery; pairing and authenticated health requests.

Not yet validated: video playback between two separate PCs. This is experimental PoC software. Only use it on computers you own or are authorized to share. The shared discovery topic and short-lived pairing token are not a substitute for production-grade identity and access control.
