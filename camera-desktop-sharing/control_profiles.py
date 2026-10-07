"""Listener-created private host packages; no host-side pairing input."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import urllib.request
import zipfile

from control_protocol import new_code, normalize_code
from tls import HTTPS_CONTEXT

VERSION = '3.0.2-preview'
RELEASE = 'https://github.com/cmg1249-gif/chat-gpt-scripts/releases/download/v3.0.2/'
HOST_SETTINGS = 'roomcam-host.json'
FORMAT = 'roomcam-private-host-v1'


def data_directory():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    return base / 'RoomCam' / 'listener'


def validate_profile(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('Invalid private host settings. Create the host package in the listener.')
    if not isinstance(data.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', data['id']):
        raise ValueError('Invalid saved computer identifier.')
    if data.get('platform') not in ('windows', 'linux'):
        raise ValueError('Choose Windows or Linux.')
    if not isinstance(data.get('name'), str) or not 1 <= len(data['name']) <= 60 or any(ord(c) < 32 for c in data['name']):
        raise ValueError('Give the computer a name of 1–60 characters.')
    if not isinstance(data.get('password'), str) or not 8 <= len(data['password']) <= 128:
        raise ValueError('Choose a password of 8–128 characters, or leave it blank to generate one.')
    normalize_code(data.get('code'))
    return data


def read_host_profile(directory):
    path = Path(directory) / HOST_SETTINGS
    if not path.exists():
        return None
    if path.stat().st_size > 8192:
        raise ValueError('Host settings are too large.')
    return validate_profile(json.loads(path.read_text(encoding='utf-8')))


class ProfileStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else None
        self.memory = {}
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def create(self, name, platform, password=''):
        profile = validate_profile(dict(format=FORMAT, id=secrets.token_hex(16),
            name=name.strip() if isinstance(name, str) else name, platform=platform,
            code=new_code(), password=password or secrets.token_urlsafe(32)))
        if self.directory:
            path = self.directory / (profile['id'] + '.json')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(profile, stream)
        self.memory[profile['id']] = profile
        return profile

    def get(self, profile_id):
        if not isinstance(profile_id, str) or not re.fullmatch('[a-f0-9]{32}', profile_id):
            raise ValueError('Select a saved computer in this listener.')
        if self.directory:
            profile = read_json(self.directory / (profile_id + '.json'))
        else:
            profile = self.memory.get(profile_id)
        return validate_profile(profile)

    def list_public(self):
        profiles = []
        ids = [path.stem for path in self.directory.glob('*.json')] if self.directory else list(self.memory)
        for profile_id in ids:
            try:
                profile = self.get(profile_id)
                profiles.append({key: profile[key] for key in ('id', 'name', 'platform')})
            except (OSError, ValueError):
                continue
        return sorted(profiles, key=lambda item: item['name'].lower())


def read_json(path):
    if path.stat().st_size > 8192:
        raise ValueError('Saved computer settings are too large.')
    return json.loads(path.read_text(encoding='utf-8'))


def host_binary(platform, cache):
    name = 'webcam_server.exe' if platform == 'windows' else 'webcam_server.elf'
    if getattr(sys, 'frozen', False):
        nearby = Path(sys.executable).parent / name
    else:
        source = Path(__file__).parent
        repo = source.parent if source.parent.name != 'linux' else source.parent.parent
        nearby = repo / ('camera-desktop-sharing' if platform == 'windows' else 'linux/camera-desktop-sharing') / 'dist' / name
    if nearby.is_file():
        return nearby
    # A standalone listener can fetch either platform's official host binary.
    # No pairing secret or session password is sent with these public downloads.
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with urllib.request.urlopen(RELEASE + 'SHA256SUMS.txt', context=HTTPS_CONTEXT, timeout=20) as response:
        manifest = response.read(16384).decode('ascii')
    entries = dict((filename, digest) for digest, filename in (line.split() for line in manifest.splitlines() if line.strip()))
    expected = entries.get(name)
    if not expected or not re.fullmatch('[a-f0-9]{64}', expected):
        raise ValueError('The release is missing the requested host checksum.')
    target = cache / name
    if target.is_file() and file_hash(target) == expected:
        return target
    fd, temporary = tempfile.mkstemp(dir=cache, prefix='download-')
    try:
        total = 0
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as stream, urllib.request.urlopen(RELEASE + name, context=HTTPS_CONTEXT, timeout=30) as response:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 512 * 1024 * 1024:
                    raise ValueError('Host download exceeds the expected size limit.')
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('Host download failed checksum verification.')
        os.chmod(temporary, 0o700)
        os.replace(temporary, target)
        return target
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_host_package(profile, binary, destination):
    validate_profile(profile)
    executable = 'webcam_server.exe' if profile['platform'] == 'windows' else 'webcam_server.elf'
    instructions = ('RoomCam — ' + profile['name'] + '\n\n'
        'Extract this folder and run ' + executable + '. Keep roomcam-host.json beside it.\n'
        'No code, password, or address needs to be entered on this computer.\n'
        'In your listener, select this computer and click Connect.\n'
        'Capture and terminal stay off until enabled from the listener.\n'
        'Close the host window to stop sharing.\n\n'
        'This is your private, pre-paired package. Do not publish it or share it with other listeners.\n')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        info = zipfile.ZipInfo(executable)
        info.create_system = 3
        info.external_attr = (0o100755 << 16)
        info.compress_type = zipfile.ZIP_DEFLATED
        with Path(binary).open('rb') as source, archive.open(info, 'w') as target:
            import shutil
            shutil.copyfileobj(source, target, 1024 * 1024)
        info = zipfile.ZipInfo(HOST_SETTINGS)
        info.create_system = 3
        info.external_attr = (0o100600 << 16)
        archive.writestr(info, json.dumps(profile))
        archive.writestr('START-HERE.txt', instructions)
