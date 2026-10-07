param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:PYTHONUSERBASE = Join-Path $PSScriptRoot '.build\python-user'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build\cache'
    $ui = @('--add-data', "${PSScriptRoot}\control.html;.", '--add-data', "${PSScriptRoot}\assets;assets")
    $ptyRoot = & $Python -c 'import pathlib,winpty; print(pathlib.Path(winpty.__file__).parent)'
    if ($LASTEXITCODE) { throw 'Install pywinpty before building the Windows host' }
    $pty = @('--add-binary', "${ptyRoot}\OpenConsole.exe;winpty", '--add-binary', "${ptyRoot}\winpty-agent.exe;winpty")
    & $Python -m PyInstaller --noconfirm --onefile --windowed --hidden-import pystray._win32 @pty --name webcam_server --distpath dist --workpath .build\server --specpath .build --add-binary "${PSScriptRoot}\cloudflared.exe;." --add-data "${PSScriptRoot}\page.html;." webcam_server.py
    if ($LASTEXITCODE) { throw 'Server build failed' }
    & $Python -m PyInstaller --noconfirm --onefile --collect-all imageio_ffmpeg @ui --name viewer --distpath dist --workpath .build\viewer --specpath .build viewer.py
    if ($LASTEXITCODE) { throw 'Viewer build failed' }
    & $Python -m PyInstaller --noconfirm --onefile --collect-all imageio_ffmpeg @ui @pty --name CheckConnection --distpath dist --workpath .build\check --specpath .build --add-binary "${PSScriptRoot}\cloudflared.exe;." --add-data "${PSScriptRoot}\page.html;." check_control_center.py
    if ($LASTEXITCODE) { throw 'Diagnostic build failed' }
} finally { Pop-Location }
