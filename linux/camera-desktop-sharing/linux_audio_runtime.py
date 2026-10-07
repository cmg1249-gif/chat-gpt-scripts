"""Use the bundled PortAudio in frozen Linux apps, without an OS install."""
import ctypes.util
from pathlib import Path
import sys

_system_find_library = ctypes.util.find_library


def _find_library(name):
    if name == 'portaudio':
        for filename in ('libportaudio.so.2', 'libportaudio.so.2.0.0'):
            candidate = Path(sys._MEIPASS) / filename
            if candidate.is_file():
                return str(candidate)
    return _system_find_library(name)


ctypes.util.find_library = _find_library
