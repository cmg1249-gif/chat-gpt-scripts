import argparse
import logging
from logging.handlers import RotatingFileHandler
import queue
import os
from pathlib import Path
from werkzeug.serving import make_server
import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

from flask import Flask, Response, request
import mss
from PIL import Image
from io import BytesIO
from discovery import discovery_key, signature
from tls import HTTPS_CONTEXT
from retry import retry_delay
from desktop_audio import AudioHub, LoopbackCapture, audio_info

PORT = 8765
NTFY_TOPIC = os.environ.get("DESKTOP_STREAM_TOPIC", "desktop-stream-codex-898ad5640829285844a6d528")
USERNAME = "viewer"
PAIR_LIFETIME = 10 * 60
PUBLISH_EVERY = 600
FPS = 12
JPEG_QUALITY = 65
MAX_WIDTH = 1600

# Text shown on THIS machine (the one being shared) while the server is running.
# Edit this string to whatever you want the on-screen banner to say.
INDICATOR_TEXT = "Your Screen Server is ON"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096
stop_event = threading.Event()
discovery_changed = threading.Event()
startup_messages = queue.Queue()
tunnel_process = None
http_server = None

state_lock = threading.Lock()
password_hash = None
paired = False
pair_token = secrets.token_urlsafe(32)
started_at = time.time()
tunnel_url = None
active_viewers = 0
active_audio_viewers = 0
audio_hub = AudioHub()
session_id = secrets.token_urlsafe(16)
network_status = "Starting connection"
reconnect_key = None
logger = logging.getLogger("screen-server")


def configure_logging():
    directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CodexScreenServer"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "server.log", maxBytes=1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def set_status(message):
    global network_status
    network_status = message
    log(message)


def log(msg):
    logger.info(msg)
    if sys.stdout is not None:
        print(f"[server] {msg}", flush=True)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1
    )
    return base64.urlsafe_b64encode(salt + digest).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    salt, expected = raw[:16], raw[16:]
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1
    )
    return hmac.compare_digest(actual, expected)


def authorized():
    global paired
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return False
    with state_lock:
        if not paired or password_hash is None:
            return False
        return username == USERNAME and verify_password(password, password_hash)


def auth_required():
    return Response(
        "Authentication required\n",
        401,
        {"WWW-Authenticate": 'Basic realm="Desktop Stream"'},
    )


@app.get("/pair-info")
def pair_info():
    # This endpoint deliberately exposes only whether pairing is still open.
    # The actual pairing token is delivered through the ntfy rendezvous message.
    with state_lock:
        if paired or time.time() - started_at > PAIR_LIFETIME:
            return {"pairing": False}, 410
    return {"pairing": True}


@app.post("/pair")
def pair():
    global password_hash, paired, reconnect_key
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"ok": False, "error": "JSON object required"}, 400
    token = data.get("token", "")
    password = data.get("password", "")
    if not isinstance(token, str) or not isinstance(password, str):
        return {"ok": False, "error": "token and password must be strings"}, 400

    if len(password) < 8 or len(password) > 128:
        return {"ok": False, "error": "password must be 8-128 characters"}, 400

    with state_lock:
        # A lost response must not prevent the same viewer retrying its request.
        if paired:
            if hmac.compare_digest(token.encode(), pair_token.encode()) and verify_password(password, password_hash):
                return {"ok": True}
            return {"ok": False, "error": "pairing closed"}, 410
        if time.time() - started_at > PAIR_LIFETIME:
            return {"ok": False, "error": "pairing closed"}, 410
        if not hmac.compare_digest(token.encode("utf-8"), pair_token.encode("utf-8")):
            return {"ok": False, "error": "invalid pairing token"}, 403
        password_hash = hash_password(password)
        reconnect_key = discovery_key(password, session_id)
        paired = True

    log("Listener paired successfully. Password is now set.")
    discovery_changed.set()
    return {"ok": True}


@app.get("/health")
def health():
    with state_lock:
        is_paired = paired
    if not authorized():
        return auth_required()
    return {"ok": True, "paired": is_paired, "session": session_id}


def capture_jpeg(sct, monitor):
    shot = sct.grab(monitor)
    image = Image.frombytes("RGB", shot.size, shot.rgb)

    if image.width > MAX_WIDTH:
        height = round(image.height * MAX_WIDTH / image.width)
        image = image.resize((MAX_WIDTH, height), Image.Resampling.LANCZOS)

    buf = BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def list_monitors():
    with mss.MSS() as sct:
        return [dict(id=index, name=monitor.get('name', f'Monitor {index}'),
                     width=monitor['width'], height=monitor['height'],
                     left=monitor['left'], top=monitor['top'],
                     primary=bool(monitor.get('is_primary', index == 1)))
                for index, monitor in enumerate(sct.monitors[1:], 1)]


@app.get('/monitors')
def monitors():
    if not authorized():
        return auth_required()
    return {'monitors': list_monitors()}


@app.get('/audio-info')
def desktop_audio_info():
    if not authorized():
        return auth_required()
    try:
        return audio_info()
    except (OSError, ValueError, RuntimeError) as exc:
        return {'available': False, 'error': str(exc)}


@app.get('/audio')
def audio():
    if not authorized():
        return auth_required()
    try:
        capture = audio_hub.subscribe(LoopbackCapture)
    except (OSError, ValueError, RuntimeError) as exc:
        log(f'Desktop audio unavailable: {exc}')
        return {'error': str(exc)}, 503

    def generate():
        global active_audio_viewers
        with state_lock:
            active_audio_viewers += 1
        try:
            while not stop_event.is_set():
                chunk = capture.read()
                if not chunk:
                    return
                yield chunk
        finally:
            capture.close()
            with state_lock:
                active_audio_viewers -= 1

    response = Response(generate(), mimetype='application/octet-stream', headers={
        'X-Audio-Sample-Rate': str(capture.sample_rate), 'X-Audio-Channels': '2',
        'X-Audio-Format': 's16le', 'Cache-Control': 'no-store, no-transform',
        'X-Accel-Buffering': 'no',
    })
    response.call_on_close(capture.close)
    return response


@app.get("/video")
def video():
    if not authorized():
        return auth_required()
    try:
        monitor_id = int(request.args.get('monitor', '1'))
    except ValueError:
        return {'error': 'monitor must be a number'}, 400
    available = list_monitors()
    if not 1 <= monitor_id <= len(available):
        return {'error': 'Monitor is unavailable; refresh the monitor list.'}, 404

    def generate():
        global active_viewers
        with state_lock:
            active_viewers += 1
        try:
            interval = 1.0 / FPS
            with mss.MSS() as sct:
                if monitor_id >= len(sct.monitors):
                    return
                monitor = sct.monitors[monitor_id]
                while not stop_event.is_set():
                    started = time.monotonic()
                    jpeg = capture_jpeg(sct, monitor)
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                           + jpeg + b"\r\n")
                    stop_event.wait(max(0, interval - (time.monotonic() - started)))
        finally:
            with state_lock:
                active_viewers -= 1

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", 'X-Monitor-Id': str(monitor_id)},
    )


def open_tunnel():
    global tunnel_process
    import re
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    binary = bundle / "cloudflared.exe"
    if not binary.is_file():
        raise RuntimeError("cloudflared.exe is missing beside server.py; rebuild the bundle.")
    tunnel_process = subprocess.Popen(
        [str(binary), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines = queue.Queue(maxsize=256)
    process = tunnel_process
    def drain():
        for line in process.stderr:
            if " ERR " in line or " WRN " in line:
                log("Cloudflare: " + line.strip())
            try:
                lines.put_nowait(line)
            except queue.Full:
                pass
    threading.Thread(target=drain, daemon=True).start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not stop_event.is_set():
        if tunnel_process.poll() is not None:
            raise RuntimeError("Cloudflare exited before connecting.")
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            continue
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if match:
            return match.group(0)
    raise RuntimeError("Cloudflare connection timed out or was stopped.")


def publish_rendezvous(url):
    with state_lock:
        details = {
        "app": "desktop-stream-v1",
        "url": url,
        "session": session_id,
        "paired": paired,
        "created": int(time.time()),
        }
        if not paired:
            details["token"] = pair_token
        else:
            details["signature"] = signature(details, reconnect_key)
    payload = json.dumps(details)
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=payload.encode("utf-8"),
        method="POST",
        headers={
            "Title": "desktop-stream",
            "Content-Type": "application/json",
            "Cache": "yes",
            "X-Cache": "yes",
        },
    )
    with urllib.request.urlopen(req, timeout=10, context=HTTPS_CONTEXT) as response:
        if response.status != 200:
            raise RuntimeError(f"ntfy returned HTTP {response.status}")


def rendezvous_loop(url):
    global pair_token, started_at
    while not stop_event.is_set():
        discovery_changed.clear()
        if tunnel_process is not None and tunnel_process.poll() is not None:
            raise RuntimeError("Cloudflare exited; rebuilding tunnel")
        with state_lock:
            if not paired:
                pair_token = secrets.token_urlsafe(32)
                started_at = time.time()
        try:
            publish_rendezvous(url)
            delay = PUBLISH_EVERY
            set_status("Paired; discovery available" if paired else "Ready for viewer; discovery published")
        except Exception as exc:
            delay = retry_delay(exc, default=20)
            set_status(f"Discovery unavailable; retrying in {delay}s: {exc}")
        for _ in range((delay + 1) // 2):
            if stop_event.wait(2):
                return
            if tunnel_process is not None and tunnel_process.poll() is not None:
                raise RuntimeError("Cloudflare exited; rebuilding tunnel")
            if discovery_changed.is_set():
                break


def close_tunnel():
    global tunnel_process
    process, tunnel_process = tunnel_process, None
    if process is not None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def run_indicator(args):
    # Persistent, always-on-top banner on the machine being shared, so whoever
    # is sitting at this screen can SEE it is being streamed and stop it.
    try:
        import tkinter as tk
    except Exception as exc:
        log(f"tkinter unavailable ({exc}); the on-screen banner cannot be shown.")
        log("Refusing to stream without a visible indicator. Stopping.")
        return

    root = tk.Tk()
    root.title("Screen Server")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("+40+40")

    banner = tk.Label(
        root, text=INDICATOR_TEXT, font=("Segoe UI", 15, "bold"),
        fg="white", bg="#c0392b", padx=20, pady=12,
    )
    banner.pack(fill="x")

    status = tk.Label(
        root, text="Waiting for a viewer to pair...",
        font=("Segoe UI", 10), padx=20, pady=8,
    )
    status.pack(fill="x")

    tk.Button(root, text="Stop sharing", command=root.destroy).pack(pady=(0, 12))

    def refresh():
        try:
            message = startup_messages.get_nowait()
            if message.startswith("ERROR:"):
                from tkinter import messagebox
                messagebox.showerror("Screen Server", message, parent=root)
                root.destroy()
                return
        except queue.Empty:
            pass
        with state_lock:
            is_paired = paired
            viewers = active_viewers
        if viewers > 0 or active_audio_viewers > 0:
            status.config(text="LIVE - screen / desktop audio sharing", fg="#c0392b")
        elif is_paired:
            status.config(text="Paired. Ready to stream.", fg="black")
        else:
            status.config(text=network_status, fg="black")
        root.after(500, refresh)

    refresh()
    log("On-screen banner is up. Close it or click 'Stop sharing' to end.")
    root.after(200, lambda: threading.Thread(target=start_network, args=(args,), daemon=True).start())
    if args.stop_after:
        root.after(int(args.stop_after * 1000), root.destroy)
    root.mainloop()
    log("Banner closed. Stopping.")


def start_network(args):
    global http_server, PORT
    try:
        http_server = make_server("127.0.0.1", args.port, app, threaded=True)
        PORT = http_server.server_port
        if stop_event.is_set():
            http_server.server_close()
            return
        threading.Thread(target=http_server.serve_forever, daemon=True).start()
        while not stop_event.is_set():
            try:
                set_status("Connecting tunnel" if not args.local else "Local test ready")
                url = f"http://127.0.0.1:{PORT}" if args.local else open_tunnel()
                if args.session_file:
                    Path(args.session_file).write_text(json.dumps({"url": url, "token": pair_token}))
                if args.local:
                    return
                rendezvous_loop(url)
            except Exception as exc:
                set_status(f"Connection unavailable; retrying in 5 seconds: {exc}")
            finally:
                if not args.local:
                    close_tunnel()
            stop_event.wait(5)
    except Exception as exc:
        log(f"Startup failed: {exc}")
        startup_messages.put(f"ERROR: {exc}")


def run_tray(args):
    import pystray
    from PIL import ImageDraw
    image = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 10, 58, 47), radius=5, fill='#267d46')
    draw.rectangle((28, 47, 36, 55), fill='#267d46')
    draw.rectangle((18, 55, 46, 59), fill='#267d46')
    icon = pystray.Icon('CodexScreenServer', image, 'Screen sharing server is running')
    def stop_sharing():
        stop_event.set()
        icon.stop()
    icon.menu = pystray.Menu(
        pystray.MenuItem('Screen sharing is running', None, enabled=False),
        pystray.MenuItem('Stop sharing', stop_sharing),
    )
    def setup(tray):
        tray.visible = True
        threading.Thread(target=start_network, args=(args,), daemon=True).start()
        if args.stop_after:
            timer = threading.Timer(args.stop_after, stop_sharing)
            timer.daemon = True
            timer.start()
        while not stop_event.wait(0.5):
            tray.title = ("LIVE - screen / desktop audio sharing" if active_viewers or active_audio_viewers else network_status)[:127]
            try:
                message = startup_messages.get_nowait()
            except queue.Empty:
                continue
            if message.startswith('ERROR:'):
                error_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexScreenServer'
                error_dir.mkdir(parents=True, exist_ok=True)
                (error_dir / 'last-error.txt').write_text(message)
                stop_sharing()
                return
    icon.run(setup=setup)


def run_server():
    configure_logging()
    parser = argparse.ArgumentParser(description="Desktop sharing server with system-tray stop control")
    parser.add_argument("--local", action="store_true", help="Loopback only; no internet services")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--session-file", help="Write pairing details for local integration testing")
    parser.add_argument("--stop-after", type=float, default=0, help="Stop automatically after this many seconds")
    parser.add_argument("--show-banner", action="store_true", help="Optionally show the original sharing banner")
    args = parser.parse_args()
    try:
        if args.show_banner:
            run_indicator(args)
        else:
            run_tray(args)
    finally:
        stop_event.set()
        audio_hub.close()
        close_tunnel()
        if http_server is not None:
            http_server.shutdown()
            http_server.server_close()


if __name__ == "__main__":
    run_server()
