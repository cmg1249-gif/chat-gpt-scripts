# ChatGPT Scripts

A collection of scripts and experimental projects built with ChatGPT.

## Bitforge classroom game — both versions

Learn binary, IPv4, subnetting, and the OSI model while reclaiming networks from an AI overlord. [Bitforge instructions and editable source](games/bitforge/) include **Version 1 Classic** and **Version 2 World Campaign**. [Download both versions](https://github.com/cmg1249-gif/chat-gpt-scripts/releases/tag/bitforge-v1-v2): download an HTML game, then open it in your browser. No Python, installation, or account is needed.

## RoomCam Control Center — v3.0.2 preview

[Download the Windows and Linux release](https://github.com/cmg1249-gif/chat-gpt-scripts/releases/tag/v3.0.2). The browser dashboard includes camera/desktop viewing, audio controls, and an authenticated PowerShell/Bash terminal on the sharing computer. LAN port 2220, Cloudflare, and an independent Pinggy TLS relay provide connection options.

**Start with the viewer.** Create a private host package in its browser dashboard, extract that package on the sharing computer, and run `webcam_server`. Select the saved computer in the viewer and connect: no host code, password entry, or copying details back. See [setup instructions](CONTROL-CENTER.md) and [verification and limits](verification/HANDS-FREE.md). Replace older hosts with the new prepared package.

## Find your program

Each folder is a complete, separate program, like the projects in Claude-Written-Scripts. Keep the files in your chosen folder together; the main Python scripts import the helper files beside them.

| Program / source folder | What it does | Python files to run |
|---|---|---|
| [Camera + desktop sharing](camera-desktop-sharing/) | Webcam or desktop video, microphone and speaker audio, browser viewing, and recording | **webcam_server.py** on the sharing PC; **viewer.py** on the viewing PC |
| [Screen sharing](screen-sharing/) | Desktop video and speaker audio | **server.py** on the sharing PC; **listener.py** on the viewing PC |
| [TCP broker](tcp-broker/) | Pairs an authenticated sender with a prompt-free receiver | **server.py** on the relay host |
| [Linux versions (Arch x86_64)](linux/) | Camera/desktop sharing, viewer, and diagnostics for Linux | **webcam_server.py** and **viewer.py**, or the packaged `.elf` programs |

## Download and run the Python code

1. [Download the current source ZIP](https://github.com/cmg1249-gif/chat-gpt-scripts/archive/refs/heads/main.zip), or use the green **Code > Download ZIP** button above.
2. Extract the ZIP, then open the folder for the program you want. You only need that program's folder; the other program folders can be left behind.
3. Follow **Run from Python source** in that folder's README for installation and the exact launch commands.

For camera/desktop and screen sharing, use **Python 3.12 on Windows x64** and keep all helper `.py` files, `requirements.txt`, and any included HTML together. The `test_*.py` files are development checks; `check_connection.py` is a diagnostic, not the normal app launcher. You do not need to build an EXE to run Python source.

The folders were previously named `combined-media` and `screen-recording`; they are now `camera-desktop-sharing` and `screen-sharing`. Existing release downloads keep their original names. Camera/desktop release notes and executable checksums are inside its own folder.

## Existing EXE downloads and project details

## Screen-sharing proof of concept (PoC)

[`screen-sharing/`](screen-sharing/) contains a Windows desktop-sharing **proof of concept**, with standalone server and listener executables distributed through GitHub Releases.

The server runs without a banner or console window and provides a system-tray control to stop sharing. The listener chooses a password, discovers the server, and displays its desktop stream with speaker audio, a monitor selector, and a mute control. Use this PoC on computers you own or have permission to share.

### Validation and limitations

- Thirty-four automated checks cover bundled certificate trust, pairing, authentication, retries, delayed discovery, VM clock differences, reconnect address verification, frame parsing, monitor selection, audio handling, and viewer cleanup.
- The release includes local capture/playback and internet connectivity diagnostics. See [validation details](screen-sharing/VALIDATION.md) for the tested artifacts and environments.
- Packaged physical-PC tests verify capture from two real monitors, viewer switching, mute controls, and real speaker-loopback capture. A live internet test verifies generated video and audio before and after replacing the tunnel.
- Win11-DuckyLab (Windows 11, VirtualBox NAT) streamed 12 real desktop frames at 1021×748 to the packaged listener on the physical Windows PC. The missing-root-certificate failure found in that guest was fixed and retested successfully.

This is experimental software, not a production-ready remote-access product. Automatic discovery uses a shared ntfy topic containing the short-lived pairing token; anyone with access to that topic can attempt to claim an unpaired server. The repository and its paired binaries should be shared only with trusted users.

Download `ScreenServer.exe` and `ScreenListener.exe` from Releases. See the [project README](screen-sharing/README.md) for usage, rebuilding, and the local executable test.

## Combined camera and desktop sharing — v2.0.2

[`camera-desktop-sharing/`](camera-desktop-sharing/) adds webcam selection, microphone and desktop-speaker mixing, monitor switching, browser controls, and recording. Password setup remains in the listener; the server has a tray stop control and no password popup.

Download the matching **webcam_server.exe** and **viewer.exe** from the [v2.0.2 release](https://github.com/cmg1249-gif/chat-gpt-scripts/releases/tag/v2.0.2). These replace the earlier desktop-only pair for combined sharing. The release adds the Windows mouse pointer to desktop viewing and recordings, preserving the previous clarity and display-resize improvements, with current checks and earlier physical-PC/VirtualBox NAT validation documented in [VALIDATION.md](camera-desktop-sharing/VALIDATION.md).

Camera/microphone and recording functionality originated in [Claude-Written-Scripts](https://github.com/cmg1249-gif/Claude-Written-Scripts/tree/d589473/ducky-cam-web-with-audio); desktop/audio, pairing, and reliability improvements combine work from both repositories.

## TCP broker

See [tcp-broker/](tcp-broker/) for a dependency-free Python server that pairs a token-authenticated sender on port 4444 with a prompt-free receiver on port 4445. Its README documents the protocol and hosting limitations.
