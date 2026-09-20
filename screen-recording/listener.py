import argparse
import os
import base64
import getpass
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np
from discovery import discovery_key, signature
from tls import HTTPS_CONTEXT
from retry import retry_delay

NTFY_TOPIC = os.environ.get("DESKTOP_STREAM_TOPIC", "desktop-stream-codex-898ad5640829285844a6d528")
USERNAME = "viewer"
current_session = None


def http_json(url, method="GET", payload=None, username=None, password=None):
    data = None
    headers = {"User-Agent": "desktop-stream-listener/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if username is not None and password is not None:
        raw = f"{username}:{password}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=12, context=HTTPS_CONTEXT) as response:
        return json.loads(response.read().decode("utf-8"))


def find_session(session_id=None, password=None, allow_unpaired=False):
    global current_session
    print("Waiting for a server advertisement...")
    last_status = None
    reconnect_key = discovery_key(password, session_id) if session_id and password else None
    while True:
        delay = 5
        # Use the service's timestamp, not the VM's possibly skewed clock.
        url = f"https://ntfy.sh/{NTFY_TOPIC}/json?poll=1&since=15m"
        try:
            with urllib.request.urlopen(url, timeout=15, context=HTTPS_CONTEXT) as response:
                candidates = []
                for line in response:
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        if not isinstance(msg, dict) or msg.get("event") != "message":
                            continue
                        payload = json.loads(msg.get("message", "{}"))
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("app") != "desktop-stream-v1":
                        continue
                    if session_id and payload.get("session") != session_id:
                        continue
                    if session_id and not payload.get("paired") and not allow_unpaired:
                        continue
                    if not session_id and (payload.get("paired") or not isinstance(payload.get("token"), str)):
                        continue
                    base_url = payload.get("url")
                    if not isinstance(base_url, str) or urllib.parse.urlparse(base_url).scheme != "https":
                        continue
                    candidates.append(payload)
            tried_urls = set()
            for payload in reversed(candidates):
                if payload['url'] in tried_urls:
                    continue
                tried_urls.add(payload['url'])
                try:
                    if session_id and payload.get('paired'):
                        signed = payload.get('signature')
                        if reconnect_key is None or not isinstance(signed, str) or not hmac.compare_digest(signed, signature(payload, reconnect_key)):
                            continue
                        info = http_json(payload['url'].rstrip('/') + '/health', username=USERNAME, password=password)
                        if not info.get('ok') or info.get('session') != session_id:
                            continue
                    else:
                        info = http_json(payload["url"].rstrip("/") + "/pair-info")
                        if not info.get("pairing"):
                            continue
                    current_session = payload.get("session")
                    return payload["url"].rstrip("/"), payload.get("token")
                except (urllib.error.URLError, OSError, ValueError):
                    continue
            status = "Discovery reachable; waiting for a ready server. Ctrl+C to cancel."
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
            delay = retry_delay(exc)
            status = f"Discovery request failed; retrying in {delay}s: {exc}"
        if status != last_status:
            print(status, flush=True)
            last_status = status
        time.sleep(delay)


def read_exact(resp, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = resp.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def stream_video(base_url, password, frames=0, headless=False, monitor=1,
                 frame_callback=None, should_stop=None):
    auth = base64.b64encode(f"{USERNAME}:{password}".encode()).decode()
    req = urllib.request.Request(
        base_url + f"/video?monitor={monitor}",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "desktop-stream-listener/1.0",
        },
    )

    print("Connecting to video stream...")
    with urllib.request.urlopen(req, timeout=20, context=HTTPS_CONTEXT) as resp:
        received = 0
        buffer = b""
        boundary = b"--frame"

        while True:
            if should_stop and should_stop():
                return
            chunk = resp.read1(65536)
            if not chunk:
                raise ConnectionError("stream ended")
            buffer += chunk

            while True:
                start = buffer.find(boundary)
                if start < 0:
                    if len(buffer) > 1024 * 1024:
                        buffer = buffer[-64 * 1024:]
                    break

                if start:
                    buffer = buffer[start:]

                header_end = buffer.find(b"\r\n\r\n")
                if header_end < 0:
                    break

                header_blob = buffer[len(boundary):header_end].decode(
                    "latin1", errors="ignore"
                )
                headers = {}
                for line in header_blob.split("\r\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        headers[key.strip().lower()] = value.strip()

                try:
                    length = int(headers["content-length"])
                except (KeyError, ValueError):
                    buffer = buffer[len(boundary):]
                    continue

                if not 0 < length <= 16 * 1024 * 1024:
                    raise ConnectionError("Invalid frame length")
                frame_start = header_end + 4
                frame_end = frame_start + length
                if len(buffer) < frame_end:
                    break

                jpeg = buffer[frame_start:frame_end]
                buffer = buffer[frame_end:]

                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                if should_stop and should_stop():
                    return

                received += 1
                if frames and received >= frames:
                    print(f"PASS: decoded {received} live frames ({frame.shape[1]}x{frame.shape[0]})", flush=True)
                    return
                if frame_callback:
                    frame_callback(frame)
                    continue
                if headless:
                    continue
                cv2.imshow("Desktop Stream", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty("Desktop Stream", cv2.WND_PROP_VISIBLE) < 1:
                    return


def main():
    parser = argparse.ArgumentParser(description="Desktop stream viewer")
    parser.add_argument("--url", help="Manual server URL")
    parser.add_argument("--token", help="Manual pairing token")
    parser.add_argument("--session-file", help="Read local test connection details")
    parser.add_argument("--frames", type=int, default=0, help="Exit after decoding N frames")
    parser.add_argument("--headless", action="store_true", help="Decode without displaying (test mode)")
    parser.add_argument('--monitor', type=int, default=1, help='Initial monitor number (1-based)')
    parser.add_argument('--list-monitors', action='store_true', help='List remote monitors and exit')
    parser.add_argument('--mute', action='store_true', help='Start with desktop audio muted')
    args = parser.parse_args()
    if args.headless and args.frames <= 0:
        parser.error("--headless requires --frames greater than zero")
    if args.monitor < 1:
        parser.error('--monitor must be at least 1')
    print("=== Desktop Stream Listener ===")
    print("The listener chooses the password; the server never asks you to edit config.")
    print("Choose an 8-128 character password; hidden input works best in a terminal.", flush=True)
    password = os.environ.get("DESKTOP_STREAM_TEST_PASSWORD")
    while password is None or not 8 <= len(password) <= 128:
        if password is not None:
            if os.environ.get("DESKTOP_STREAM_TEST_PASSWORD"):
                raise SystemExit("Test password must be 8-128 characters.")
            print("Password must be 8-128 characters. Try again.", flush=True)
        password = getpass.getpass("Set stream password: ")

    if args.session_file:
        with open(args.session_file) as f:
            session = json.load(f)
        base_url, token = session["url"], session["token"]
    elif args.url and args.token:
        base_url, token = args.url.rstrip("/"), args.token
    else:
        base_url, token = find_session()
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")):
        raise SystemExit("Connection requires HTTPS, except for loopback tests.")
    print(f"Found server: {base_url}")
    print("Pairing...")

    while True:
        try:
            result = http_json(
                base_url + "/pair", method="POST",
                payload={"token": token, "password": password},
            )
            break
        except (urllib.error.URLError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 401, 403, 410):
                if not (args.url or args.session_file) and exc.code in (403, 410):
                    print("Advertisement expired or already claimed; looking again.")
                    time.sleep(2)
                    base_url, token = find_session()
                    continue
                raise SystemExit(f"Pairing rejected ({exc.code}). Restart the server to choose a new password.")
            print(f"Pairing connection unavailable; retrying: {exc}", flush=True)
            time.sleep(retry_delay(exc))
            # A request may have succeeded even if its response was lost.
            try:
                if http_json(base_url + "/health", username=USERNAME, password=password).get("ok"):
                    result = {"ok": True}
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass
            if current_session and not (args.url or args.session_file):
                base_url, fresh_token = find_session(current_session, password, allow_unpaired=True)
                if fresh_token:
                    token = fresh_token

    if not result.get("ok"):
        raise SystemExit(f"Pairing failed: {result}")

    print("Paired. Opening live desktop.")
    if args.list_monitors:
        print(json.dumps(http_json(base_url + '/monitors', username=USERNAME, password=password), indent=2))
        return
    if not args.frames:
        from viewer import DesktopViewer
        DesktopViewer(base_url, password, current_session, http_json, find_session,
                      stream_video, monitor=args.monitor, muted=args.mute).run()
        return
    print("Press Q or Esc in the video window to quit.")

    while True:
        try:
            stream_video(base_url, password, args.frames, args.headless, monitor=args.monitor)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if args.frames:
                raise
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 410):
                raise SystemExit("Session expired or credentials rejected. Restart both programs.")
            print(f"Connection lost: {exc}")
            print("Reconnecting in 2 seconds...")
            time.sleep(2)
            if current_session and not (args.url or args.session_file):
                base_url, _ = find_session(current_session, password)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
