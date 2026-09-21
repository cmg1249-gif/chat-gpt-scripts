# v2.0.1 — Desktop clarity and display-resize handling

- Refresh desktop capture geometry every second, preventing indefinitely stale capture bounds after VM/display resizing.
- Raise desktop JPEG quality from 70 to 85 and the width limit from 1600 to 1920; use area filtering when downscaling.
- Prevent delayed audio workers from emitting catch-up packets with duplicate timestamps, which also affect video synchronization.
- Remove an extra lossy JPEG recording pass using a lossless FFV1 intermediate. MP4 export now uses H.264 CRF 18.

Download both `webcam_server.exe` and `viewer.exe`. Password setup stays on the listener; the server retains its tray stop control.

Higher quality requires more bandwidth and lossless temporary recordings require more disk space. The desktop frame-rate limit remains 12 fps.

The supplied clip contains two Windows taskbars and only nine frames. Stale capture geometry was found and addressed, but reproducing the exact doubled-taskbar symptom on the guest remains unconfirmed. See VALIDATION.md for the checks actually run on this build.
