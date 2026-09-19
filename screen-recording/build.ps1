param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:PYTHONUSERBASE = Join-Path $PSScriptRoot '.build\python-user'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build\cache'
    & $Python -m PyInstaller --noconfirm --onefile --windowed --hidden-import pystray._win32 --name ScreenServer --distpath bin --workpath .build\server --specpath .build --add-binary "${PSScriptRoot}\cloudflared.exe;." server.py
    if ($LASTEXITCODE) { throw 'Server build failed' }
    & $Python -m PyInstaller --noconfirm --onefile --name ScreenListener --distpath bin --workpath .build\listener --specpath .build listener.py
    if ($LASTEXITCODE) { throw 'Listener build failed' }
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name CheckConnection --distpath bin --workpath .build\check --specpath .build check_connection.py
    if ($LASTEXITCODE) { throw 'Test runner build failed' }
} finally { Pop-Location }
