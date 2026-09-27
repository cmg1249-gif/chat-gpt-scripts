# v2.0.2 — Mouse pointer in desktop viewing and recordings

Desktop sharing now includes the sharing computer's visible Windows mouse pointer automatically. Its current shape and hotspot are drawn before video resizing, so the pointer appears in live desktop viewing and saved recordings. Hidden/suppressed cursors stay hidden; monitor offsets and edge clipping are handled.

Replace `webcam_server.exe` on the sharing computer. The ZIP contains the matching server, viewer, and diagnostic executables. No settings change is required.

Validation was performed locally on Windows without a VM. See the bundled VALIDATION.md for the exact checks and limits.

Also corrects an audio pacing issue found during release verification: Windows timer resolution could produce duplicate audio timestamps. Scheduling now uses a high-resolution clock while preserving the shared audio/video timestamp timebase.
