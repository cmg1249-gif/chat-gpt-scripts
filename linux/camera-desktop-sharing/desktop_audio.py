"""Linux speaker monitor capture through PulseAudio or PipeWire-Pulse.

Only a sink's monitor source is opened. Microphone capture is handled separately.
"""
import json
import os
import queue
import select
import shutil
import subprocess
import sys
import threading

import sounddevice as sd


class AudioUnavailable(RuntimeError):
    pass


def system_environment():
    """Keep bundled libraries out of Arch's own pactl/parec processes."""
    env = os.environ.copy()
    if getattr(sys, 'frozen', False):
        original = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if original is None:
            env.pop('LD_LIBRARY_PATH', None)
        else:
            env['LD_LIBRARY_PATH'] = original
    return env


def monitor_source():
    if not shutil.which('pactl') or not shutil.which('parec'):
        raise AudioUnavailable('Install libpulse on Arch (pactl and parec), and start PipeWire-Pulse or PulseAudio.')
    try:
        env = system_environment()
        default = subprocess.check_output(['pactl', 'get-default-sink'], text=True, timeout=5, env=env).strip()
        sinks = json.loads(subprocess.check_output(['pactl', '--format=json', 'list', 'sinks'], text=True, timeout=5, env=env))
        for sink in sinks:
            if sink.get('name') == default and sink.get('monitor_source_name'):
                return sink['monitor_source_name'], sink.get('description', default)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise AudioUnavailable('Cannot reach the desktop audio server. Start PipeWire-Pulse or PulseAudio in your login session.') from exc
    raise AudioUnavailable('The default speaker has no monitor source; no microphone will be substituted.')


def audio_info():
    _, name = monitor_source()
    return dict(available=True, device=name, sample_rate=48000, channels=2, format='s16le')


class LoopbackCapture:
    def __init__(self):
        source, self.device_name = monitor_source()
        self.sample_rate = 48000
        self.channels = 2
        self.closed = threading.Event()
        self.pending = bytearray()
        self.process = subprocess.Popen(
            ['parec', '--device=' + source, '--format=s16le', '--rate=48000',
             '--channels=2', '--latency-msec=20', '--raw'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=system_environment())

    def read(self):
        size = 960 * self.channels * 2
        while not self.closed.is_set():
            if len(self.pending) >= size:
                data = bytes(self.pending[:size])
                del self.pending[:size]
                return data
            if self.process.poll() is not None:
                raise AudioUnavailable('Speaker monitor capture stopped. Check your desktop audio server.')
            ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
            if not ready:
                # Keep the mixer live during silence or a suspended output device.
                return bytes(size)
            data = os.read(self.process.stdout.fileno(), size - len(self.pending))
            if not data:
                raise AudioUnavailable('Speaker monitor capture ended.')
            self.pending.extend(data)
        return b''

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process.stdout.close()


class AudioOutput:
    def __init__(self, sample_rate, channels=2):
        self.stream = sd.RawOutputStream(samplerate=sample_rate, channels=channels, dtype='int16')
        self.stream.start()

    def write(self, data):
        self.stream.write(data)

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
                self.stream = None


class AudioSubscription:
    def __init__(self, hub, sample_rate):
        self.hub = hub
        self.sample_rate = sample_rate
        self.chunks = queue.Queue(maxsize=8)
        self.closed = threading.Event()

    def read(self):
        while not self.closed.is_set():
            try:
                chunk = self.chunks.get(timeout=0.2)
            except queue.Empty:
                if self.hub.stopped.is_set():
                    return b''
                continue
            if isinstance(chunk, Exception):
                raise chunk
            return chunk
        return b''

    def close(self):
        self.closed.set()
        with self.hub.lock:
            self.hub.subscribers.discard(self)


class AudioHub:
    """One device-owning thread; reconnecting clients receive independent queues."""
    def __init__(self):
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.error = None
        self.sample_rate = None
        self.subscribers = set()

    def subscribe(self, factory=LoopbackCapture):
        with self.lock:
            if self.stopped.is_set():
                raise AudioUnavailable('Audio server is stopping.')
            if self.thread is None or not self.thread.is_alive():
                self.ready.clear()
                self.error = None
                self.thread = threading.Thread(target=self._run, args=(factory,), daemon=True)
                self.thread.start()
        if not self.ready.wait(10):
            raise AudioUnavailable('Speaker capture startup timed out.')
        with self.lock:
            if self.error is not None:
                raise AudioUnavailable(str(self.error)) from self.error
            subscription = AudioSubscription(self, self.sample_rate)
            self.subscribers.add(subscription)
            return subscription

    @staticmethod
    def _deliver(subscription, chunk):
        if subscription.chunks.full():
            try:
                subscription.chunks.get_nowait()
            except queue.Empty:
                pass
        subscription.chunks.put_nowait(chunk)

    def _run(self, factory):
        capture = None
        try:
            capture = factory()
            with self.lock:
                self.sample_rate = capture.sample_rate
            self.ready.set()
            while not self.stopped.is_set():
                chunk = capture.read()
                if not chunk:
                    raise AudioUnavailable('Speaker capture ended.')
                with self.lock:
                    for subscriber in self.subscribers:
                        self._deliver(subscriber, chunk)
        except Exception as exc:
            with self.lock:
                self.error = exc
                for subscriber in self.subscribers:
                    self._deliver(subscriber, AudioUnavailable(str(exc)))
                self.subscribers.clear()
        finally:
            self.ready.set()
            if capture is not None:
                capture.close()

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
