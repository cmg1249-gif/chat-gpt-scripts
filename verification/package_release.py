"""Create the public release layout from the already tested preview binaries."""
import hashlib
from pathlib import Path
import shutil
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'release-v3.0.3'
output.mkdir(exist_ok=True)
docs = [(root / 'CONTROL-CENTER.md', 'README.md'),
        (root / 'verification/OWNER-LOGIN.md', 'VALIDATION.md')]

def sources(directory):
    files = list(directory.glob('*.py')) + list(directory.glob('*.html'))
    files += [directory / 'requirements.txt', directory / ('build.ps1' if directory.name == 'camera-desktop-sharing' and directory.parent == root else 'build.sh')]
    files += list((directory / 'assets').glob('*'))
    return [(path, 'source/' + path.relative_to(directory).as_posix()) for path in sorted(files)]

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

windows = root / 'camera-desktop-sharing'
linux = root / 'linux/camera-desktop-sharing'
windows_binaries = [(windows / 'dist' / name, name) for name in ('webcam_server.exe', 'viewer.exe', 'CheckConnection.exe')]
linux_binaries = [(linux / 'dist' / name, name) for name in ('webcam_server.elf', 'viewer.elf', 'CheckConnection.elf')]
for path, name in windows_binaries:
    shutil.copy2(path, output / name)
shutil.copy2(windows / 'viewer.py', output / 'viewer.py')
shutil.copy2(linux / 'dist/webcam_server.elf', output / 'webcam_server.elf')
windows_zip = output / 'RoomCam_ControlCenter_v3.0.3.zip'
with zipfile.ZipFile(windows_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path, name in windows_binaries + docs + sources(windows):
        archive.write(path, name)
with zipfile.ZipFile(windows_zip) as archive:
    assert archive.testzip() is None
    for path, name in windows_binaries:
        assert hashlib.sha256(archive.read(name)).hexdigest() == digest(path)
linux_tar = output / 'RoomCam_v3.0.3_linux_x86_64.tar.gz'
with tarfile.open(linux_tar, 'w:gz') as archive:
    for path, name in linux_binaries + docs + sources(linux):
        info = archive.gettarinfo(str(path), arcname='linux/' + name)
        info.mode = 0o755 if name.endswith(('.elf', '.sh')) else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        with path.open('rb') as stream:
            archive.addfile(info, stream)
with tarfile.open(linux_tar) as archive:
    for path, name in linux_binaries:
        with archive.extractfile('linux/' + name) as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest(path)
assets = [output / name for _, name in windows_binaries] + [output / 'webcam_server.elf', output / 'viewer.py', windows_zip, linux_tar]
(output / 'SHA256SUMS.txt').write_text(''.join(f'{digest(path)}  {path.name}\n' for path in assets))
(output / 'LINUX_SHA256SUMS.txt').write_text(f'{digest(linux_tar)}  {linux_tar.name}\n')
print('PASS archive integrity, source layout, and exact tested-binary hashes')
for path in sorted(output.iterdir()):
    print(path.name, path.stat().st_size)
