import argparse
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

PORT = 8765
NTFY_TOPIC = "desktop-stream-codex-898ad5640829285844a6d528"
USERNAME = "viewer"
PAIR_LIFETIME = 10 * 60
PUBLISH_EVERY = 20
FPS = 12
JPEG_QUALITY = 65
MAX_WIDTH = 1600

# Text shown on THIS machine (the one being shared) while the server is running.
# Edit this string to whatever you want the on-screen banner to say.
INDICATOR_TEXT = "Your Screen Server is ON"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096
stop_event = threading.Event()
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


def log(msg):
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
    global password_hash, paired
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
        if paired or time.time() - started_at > PAIR_LIFETIME:
            return {"ok": False, "error": "pairing closed"}, 410
        if not hmac.compare_digest(token.encode("utf-8"), pair_token.encode("utf-8")):
            return {"ok": False, "error": "invalid pairing token"}, 403
        password_hash = hash_password(password)
        paired = True

    log("Listener paired successfully. Password is now set.")
    return {"ok": True}


@app.get("/health")
def health():
    with state_lock:
        is_paired = paired
    if not authorized():
        return auth_required()
    return {"ok": True, "paired": is_paired}


def capture_jpeg(sct, monitor):
    shot = sct.grab(monitor)
    image = Image.frombytes("RGB", shot.size, shot.rgb)

    if image.width > MAX_WIDTH:
        height = round(image.height * MAX_WIDTH / image.width)
        image = image.resize((MAX_WIDTH, height), Image.Resampling.LANCZOS)

    buf = BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


@app.get("/video")
def video():
    if not authorized():
        return auth_required()

    def generate():
        global active_viewers
        with state_lock:
            active_viewers += 1
        try:
            interval = 1.0 / FPS
            with mss.mss() as sct:
                monitor = sct.monitors[1]
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
    lines = queue.Queue()
    def drain():
        for line in tunnel_process.stderr:
            lines.put(line)
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
    payload = json.dumps({
        "app": "desktop-stream-v1",
        "url": url,
        "token": pair_token,
        "created": int(time.time()),
    })
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
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"ntfy returned HTTP {response.status}")


def rendezvous_loop(url):
    while not stop_event.is_set():
        with state_lock:
            if paired or time.time() - started_at > PAIR_LIFETIME:
                return
        try:
            publish_rendezvous(url)
            log("Rendezvous info published.")
        except Exception as exc:
            log(f"ntfy publish failed: {exc}")
        stop_event.wait(PUBLISH_EVERY)


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
        if viewers > 0:
            status.config(text="LIVE - your screen is being shared right now", fg="#c0392b")
        elif is_paired:
            status.config(text="Paired. Ready to stream.", fg="black")
        else:
            status.config(text="Waiting for a viewer to pair...", fg="black")
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
        url = f"http://127.0.0.1:{PORT}" if args.local else open_tunnel()
        log(f"Server URL: {url}")
        log(f"Pairing token: {pair_token}")
        if args.session_file:
            Path(args.session_file).write_text(json.dumps({"url": url, "token": pair_token}))
        if not args.local:
            rendezvous_loop(url)
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
        if tunnel_process is not None:
            tunnel_process.terminate()
            try:
                tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel_process.kill()
        if http_server is not None:
            http_server.shutdown()
            http_server.server_close()


if __name__ == "__main__":
    run_server()
