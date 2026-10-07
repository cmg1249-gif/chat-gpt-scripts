"""Keep transport, gateway, terminal and UI identical in both platform packages."""
from pathlib import Path
import shutil

root = Path(__file__).parent
source = root / 'camera-desktop-sharing'
target = root / 'linux/camera-desktop-sharing'
for name in ('control_protocol.py', 'control_host.py', 'control_listener.py', 'control_terminal.py', 'control_relay.py', 'control.html', 'test_control.py', 'check_control_center.py'):
    if (source / name).exists():
        shutil.copy2(source / name, target / name)
shutil.copytree(source / 'assets', target / 'assets', dirs_exist_ok=True)
connection = (source / 'connection.py').read_text(encoding='utf-8').replace("/ 'cloudflared.exe'", "/ 'cloudflared'")
(target / 'connection.py').write_text(connection, encoding='utf-8')
