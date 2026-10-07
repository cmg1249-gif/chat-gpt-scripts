"""One visible, authenticated interactive shell, owned by the host process."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


class Terminal:
    def __init__(self):
        self.process = None
        self.lock = threading.RLock()
        self.output = ''
        self.offset = 0
        self.generation = 0
        self.last_used = 0
        self.exit_reason = 'Not started'

    def start(self):
        with self.lock:
            if self.process is not None and self.process.isalive():
                return
            self.output, self.offset = '', 0
            self.generation += 1
            env = os.environ.copy()
            for key in ('PYTHONHOME', 'PYTHONPATH', '_MEIPASS2'):
                env.pop(key, None)
            if 'LD_LIBRARY_PATH_ORIG' in env:
                env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
            elif getattr(__import__('sys'), 'frozen', False):
                env.pop('LD_LIBRARY_PATH', None)
            if os.name == 'nt':
                from winpty import PtyProcess
                executable = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
                for key in list(env):
                    if key.upper() == 'PSMODULEPATH':
                        del env[key]
                env['PSModulePath'] = os.pathsep.join((str(Path(executable).parent / 'Modules'),
                    str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'WindowsPowerShell/Modules'),
                    str(Path.home() / 'Documents/WindowsPowerShell/Modules')))
                # Frozen applications change the Windows DLL search directory.
                # Restore the system search path while creating a system shell.
                import ctypes
                frozen = getattr(sys, 'frozen', False)
                if frozen:
                    ctypes.windll.kernel32.SetDllDirectoryW(None)
                try:
                    startup = "Add-Type 'using System; using System.Runtime.InteropServices; public static class RoomCamConsole { [DllImport(\"kernel32.dll\")] public static extern bool SetConsoleCtrlHandler(IntPtr handler, bool add); }'; [RoomCamConsole]::SetConsoleCtrlHandler([IntPtr]::Zero, $false) | Out-Null; Set-PSReadLineOption -HistorySaveStyle SaveNothing"
                    process = PtyProcess.spawn([executable, '-NoLogo', '-NoProfile', '-NoExit', '-Command',
                        startup], cwd=str(Path.home()), env=env, dimensions=(28, 100))
                finally:
                    if frozen:
                        ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
            else:
                from ptyprocess import PtyProcessUnicode
                executable = '/bin/bash' if Path('/bin/bash').exists() else '/bin/sh'
                env['TERM'] = 'xterm-256color'
                env['HISTFILE'] = '/dev/null'
                process = PtyProcessUnicode.spawn([executable, '-i'], cwd=str(Path.home()), env=env, dimensions=(28, 100))
            self.process = process
            self.last_used = time.monotonic()
            self.exit_reason = ''
            threading.Thread(target=self._read, args=(process, self.generation), daemon=True).start()
            threading.Thread(target=self._idle_watch, args=(process,), daemon=True).start()

    def _read(self, process, generation):
        try:
            while True:
                text = process.read(4096)
                if not text:
                    if not process.isalive():
                        return
                    time.sleep(.02)
                    continue
                with self.lock:
                    if generation != self.generation:
                        return
                    self.output += text
                    if len(self.output) > 262144:
                        removed = len(self.output) - 262144
                        self.output = self.output[removed:]
                        self.offset += removed
        except (EOFError, OSError):
            pass

    def _idle_watch(self, process):
        while process is self.process and process.isalive():
            time.sleep(2)
            if time.monotonic() - self.last_used > 900:
                self.close('Closed after 15 minutes without keyboard input')
                return

    def write(self, data):
        if not isinstance(data, str) or not data or len(data) > 8192:
            raise ValueError('Terminal input must contain 1–8192 characters.')
        with self.lock:
            if self.process is None or not self.process.isalive():
                raise ValueError('Shell is not running. ' + self.output[-1000:])
            self.last_used = time.monotonic()
            if os.name == 'nt':
                # ConPTY requests Win32 input mode. Encode Ctrl+C as an actual
                # key event so foreground Windows commands receive the signal.
                data = data.replace('\x03', '\x1b[67;46;3;1;8;1_\x1b[67;46;3;0;8;1_')
            self.process.write(data)

    def resize(self, rows, cols):
        if type(rows) is not int or type(cols) is not int or not 5 <= rows <= 100 or not 20 <= cols <= 240:
            raise ValueError('Invalid terminal dimensions.')
        with self.lock:
            if self.process and self.process.isalive():
                self.process.setwinsize(rows, cols)

    def read(self, cursor=0, generation=0):
        with self.lock:
            reset = generation != self.generation or cursor < self.offset or cursor > self.offset + len(self.output)
            if reset:
                cursor = self.offset
            cursor = max(self.offset, cursor)
            return dict(output=self.output[cursor - self.offset:], cursor=self.offset + len(self.output),
                        generation=self.generation, reset=reset, running=bool(self.process and self.process.isalive()),
                        shell='PowerShell' if os.name == 'nt' else 'Bash / sh', reason=self.exit_reason)

    def close(self, reason='Closed by listener'):
        with self.lock:
            process, self.process = self.process, None
            self.exit_reason = reason
        if process and process.isalive():
            if os.name == 'nt':
                killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=5,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if killed.returncode == 0:
                    # taskkill has already terminated the process tree. Sending
                    # another signal races the closed Windows process handle.
                    deadline = time.monotonic() + 5
                    while process.isalive() and time.monotonic() < deadline:
                        time.sleep(.05)
                    if process.isalive():
                        raise RuntimeError('Windows has not confirmed shell shutdown yet.')
                    for resource in (process.fileobj, process._server):
                        resource.close()
                    process.closed = True
                    return
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGHUP)
                except ProcessLookupError:
                    pass
            process.terminate(force=True)
