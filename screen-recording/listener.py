import argparse
import os
import base64
import getpass
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np

NTFY_TOPIC = "desktop-stream-codex-898ad5640829285844a6d528"
USERNAME = "viewer"
LOOK_FOR_SECONDS = 300


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
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def find_session():
    print("Waiting for a server advertisement...")
    deadline = time.time() + LOOK_FOR_SECONDS
    seen = None

    while time.time() < deadline:
        url = f"https://ntfy.sh/{NTFY_TOPIC}/json?poll=1&since=latest"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                for line in response:
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if msg.get("event") != "message":
                        continue
                    if msg.get("id") == seen:
                        continue
                    seen = msg.get("id")
                    payload = json.loads(msg.get("message", "{}"))
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("app") != "desktop-stream-v1":
                        continue
                    if time.time() - int(payload.get("created", 0)) > 90:
                        continue
                    if payload.get("url") and payload.get("token"):
                        return payload["url"].rstrip("/"), payload["token"]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
            pass
        time.sleep(2)

    raise TimeoutError("No live server advertisement was found.")


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


def stream_video(base_url, password, frames=0, headless=False):
    auth = base64.b64encode(f"{USERNAME}:{password}".encode()).decode()
    req = urllib.request.Request(
        base_url + "/video",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "desktop-stream-listener/1.0",
        },
    )

    print("Connecting to video stream...")
    with urllib.request.urlopen(req, timeout=20) as resp:
        received = 0
        buffer = b""
        boundary = b"--frame"

        while True:
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

                received += 1
                if frames and received >= frames:
                    print(f"PASS: decoded {received} live frames ({frame.shape[1]}x{frame.shape[0]})", flush=True)
                    return
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
    args = parser.parse_args()
    if args.headless and args.frames <= 0:
        parser.error("--headless requires --frames greater than zero")
    print("=== Desktop Stream Listener ===")
    print("The listener chooses the password; the server never asks you to edit config.")
    password = os.environ.get("DESKTOP_STREAM_TEST_PASSWORD") or getpass.getpass("Set stream password (8-128 chars): ")
    if not 8 <= len(password) <= 128:
        raise SystemExit("Password must be 8-128 characters.")

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

    try:
        result = http_json(
            base_url + "/pair",
            method="POST",
            payload={"token": token, "password": password},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Pairing failed ({exc.code}): {body}")

    if not result.get("ok"):
        raise SystemExit(f"Pairing failed: {result}")

    print("Paired. Opening live desktop.")
    print("Press Q or Esc in the video window to quit.")

    while True:
        try:
            stream_video(base_url, password, args.frames, args.headless)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if args.frames:
                raise
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 410):
                raise SystemExit("Session expired or credentials rejected. Restart both programs.")
            print(f"Connection lost: {exc}")
            print("Reconnecting in 2 seconds...")
            time.sleep(2)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
