"""Interactive viewer with independent video and speaker-audio workers."""
import base64
import queue
import threading
import tkinter as tk
from tkinter import ttk
import urllib.error
import urllib.request

import cv2
from PIL import Image, ImageOps, ImageTk

from desktop_audio import AudioOutput
from retry import retry_delay
from tls import HTTPS_CONTEXT


def audio_format(headers):
    rate = int(headers.get('X-Audio-Sample-Rate', 0))
    channels = int(headers.get('X-Audio-Channels', 0))
    if not 8000 <= rate <= 192000 or channels != 2 or headers.get('X-Audio-Format') != 's16le':
        raise ValueError('Unsupported desktop-audio format')
    return rate, channels


class DesktopViewer:
    def __init__(self, base_url, password, session_id, http, discover, video, monitor=1, muted=False):
        self.base_url, self.password, self.session_id = base_url, password, session_id
        self.http, self.discover, self.video = http, discover, video
        self.selected = monitor
        self.muted = muted
        self.stop = threading.Event()
        self.refresh = threading.Event()
        self.frames = queue.Queue(maxsize=1)
        self.messages = queue.Queue()
        self.monitors = []
        self.photo = None
        self.root = tk.Tk()
        self.root.title('Desktop Stream')
        self.root.geometry('1100x750')
        self.root.minsize(600, 400)
        toolbar = ttk.Frame(self.root, padding=10)
        toolbar.pack(fill='x')
        ttk.Label(toolbar, text='Monitor').pack(side='left', padx=(0, 8))
        self.monitor_box = ttk.Combobox(toolbar, state='readonly', width=48)
        self.monitor_box.pack(side='left')
        self.monitor_box.bind('<<ComboboxSelected>>', self.select_monitor)
        ttk.Button(toolbar, text='Refresh', command=self.refresh.set).pack(side='left', padx=8)
        self.mute_var = tk.BooleanVar(value=muted)
        ttk.Checkbutton(toolbar, text='Mute desktop audio', variable=self.mute_var,
                        command=self.toggle_mute).pack(side='right')
        self.status = tk.StringVar(value='Connecting video…')
        self.audio_status = tk.StringVar(value='Audio muted' if muted else 'Connecting desktop audio…')
        ttk.Label(self.root, textvariable=self.status, padding=(10, 2)).pack(anchor='w')
        ttk.Label(self.root, textvariable=self.audio_status, padding=(10, 2)).pack(anchor='w')
        self.image_label = tk.Label(self.root, background='#111827')
        self.image_label.pack(fill='both', expand=True, padx=10, pady=(6, 10))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda event: self.close())

    def select_monitor(self, event=None):
        index = self.monitor_box.current()
        if 0 <= index < len(self.monitors):
            self.selected = self.monitors[index]['id']
            self.status.set(f'Switching to monitor {self.selected}…')

    def toggle_mute(self):
        self.muted = self.mute_var.get()
        self.audio_status.set('Audio muted' if self.muted else 'Connecting desktop audio…')

    def put_frame(self, frame, monitor):
        try:
            self.frames.get_nowait()
        except queue.Empty:
            pass
        try:
            self.frames.put_nowait((monitor, frame))
        except queue.Full:
            pass

    def video_worker(self):
        while not self.stop.is_set():
            url = self.base_url
            try:
                self.refresh.clear()
                monitors = self.http(url + '/monitors', username='viewer', password=self.password)['monitors']
                if not monitors:
                    raise RuntimeError('No capture monitors are available on the server.')
                if self.selected not in [m['id'] for m in monitors]:
                    self.selected = monitors[0]['id']
                self.messages.put(('monitors', monitors))
                monitor = self.selected
                self.messages.put(('video', f'Connecting monitor {monitor}…'))
                self.video(url, self.password, monitor=monitor,
                           frame_callback=lambda frame: self.put_frame(frame, monitor),
                           should_stop=lambda: self.stop.is_set() or self.selected != monitor or self.refresh.is_set())
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                self.messages.put(('video', f'Video unavailable; reconnecting: {exc}'))
                if self.stop.wait(retry_delay(exc)):
                    return
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                    self.selected = 1
                    continue
                if self.session_id:
                    self.base_url, _ = self.discover(self.session_id, self.password)

    def audio_worker(self):
        auth = base64.b64encode(f'viewer:{self.password}'.encode()).decode()
        while not self.stop.is_set():
            if self.muted:
                self.stop.wait(0.1)
                continue
            url = self.base_url
            output = None
            try:
                info = self.http(url + '/audio-info', username='viewer', password=self.password)
                if not info.get('available'):
                    raise RuntimeError(info.get('error', 'No speaker-output device on the server.'))
                request = urllib.request.Request(url + '/audio', headers={'Authorization': f'Basic {auth}'})
                with urllib.request.urlopen(request, timeout=10, context=HTTPS_CONTEXT) as response:
                    rate, channels = audio_format(response.headers)
                    output = AudioOutput(rate, channels)
                    self.messages.put(('audio', f'Desktop audio on · {rate // 1000} kHz stereo'))
                    pending = b''
                    while not self.stop.is_set() and not self.muted and self.base_url == url:
                        chunk = response.read1(8192)
                        if not chunk:
                            raise ConnectionError('Audio stream ended')
                        pending += chunk
                        length = len(pending) // (channels * 2) * (channels * 2)
                        if length and not self.muted:
                            output.write(pending[:length])
                        pending = pending[length:]
            except (OSError, ValueError, RuntimeError) as exc:
                self.messages.put(('audio', f'Desktop audio unavailable: {exc}'))
                self.stop.wait(retry_delay(exc))
            finally:
                if output is not None:
                    output.close()

    def refresh_ui(self):
        if self.stop.is_set():
            return
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'monitors':
                    self.monitors = value
                    self.monitor_box['values'] = [f"{m['id']}: {m['name']} ({m['width']} × {m['height']})" for m in value]
                    selected = next((i for i, m in enumerate(value) if m['id'] == self.selected), 0)
                    self.monitor_box.current(selected)
                elif kind == 'video':
                    self.status.set(value)
                elif not self.muted:
                    self.audio_status.set(value)
        except queue.Empty:
            pass
        try:
            monitor, frame = self.frames.get_nowait()
            if monitor == self.selected:
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                size = (max(100, self.image_label.winfo_width()), max(100, self.image_label.winfo_height()))
                image = ImageOps.contain(image, size)
                self.photo = ImageTk.PhotoImage(image)
                self.image_label.configure(image=self.photo)
                self.status.set(f'Live · monitor {monitor}')
        except queue.Empty:
            pass
        self.root.after(30, self.refresh_ui)

    def close(self):
        self.stop.set()
        self.root.destroy()

    def run(self):
        workers = [threading.Thread(target=self.video_worker, daemon=True),
                   threading.Thread(target=self.audio_worker, daemon=True)]
        for worker in workers:
            worker.start()
        self.refresh_ui()
        self.root.mainloop()
        self.stop.set()
        for worker in workers:
            worker.join(timeout=1)
