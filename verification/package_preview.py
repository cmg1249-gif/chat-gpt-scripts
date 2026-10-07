"""Package only the tested binaries and public documentation, never session files."""
import hashlib
from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'release-v3.0.1-preview'
output.mkdir(exist_ok=True)
docs = [(root / 'CONTROL-CENTER.md', 'README.md'), (root / 'verification/REDUNDANCY.md', 'TEST-RESULTS.md'), (root / 'verification/RESULTS.md', 'ORIGINAL-TEST-RESULTS.md')]
windows = [(root / 'camera-desktop-sharing/dist' / name, name) for name in ('webcam_server.exe', 'viewer.exe', 'CheckConnection.exe')]
linux = [(root / 'linux/camera-desktop-sharing/dist' / name, name) for name in ('webcam_server.elf', 'viewer.elf', 'CheckConnection.elf')]
for path, _ in windows + linux + docs:
    assert path.is_file(), path
with zipfile.ZipFile(output / 'RoomCam_ControlCenter_windows_x64.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path, name in windows + docs:
        archive.write(path, name)
with tarfile.open(output / 'RoomCam_ControlCenter_linux_x86_64.tar.gz', 'w:gz') as archive:
    for path, name in linux + docs:
        info = archive.gettarinfo(str(path), arcname=name)
        info.mode = 0o755 if name.endswith('.elf') else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        with path.open('rb') as source:
            archive.addfile(info, source)
checksums = []
for path in sorted(output.iterdir()):
    if path.suffix in ('.zip', '.gz'):
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        checksums.append(f'{digest}  {path.name}')
(output / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n')
print('\n'.join(checksums))
