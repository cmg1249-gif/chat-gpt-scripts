BITFORGE — DOWNLOAD FROM POWERSHELL

Both versions, teacher guides, and source code:

$url="https://github.com/cmg1249-gif/chat-gpt-scripts/releases/download/bitforge-v1-v2/Bitforge-both-versions.zip"
$outFile=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bitforge-both-versions.zip'
(New-Object Net.WebClient).DownloadFile($url, $outFile)

Right-click the downloaded ZIP and choose Extract All. Open either:
  Version-1\Bitforge-v1.html  (Classic)
  Version-2\Bitforge.html     (World Campaign)

Only Version 1 Classic:

$url="https://github.com/cmg1249-gif/chat-gpt-scripts/releases/download/bitforge-v1-v2/Bitforge-v1.html"
$outFile=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bitforge-v1.html'
(New-Object Net.WebClient).DownloadFile($url, $outFile)

Only Version 2 World Campaign:

$url="https://github.com/cmg1249-gif/chat-gpt-scripts/releases/download/bitforge-v1-v2/Bitforge.html"
$outFile=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bitforge.html'
(New-Object Net.WebClient).DownloadFile($url, $outFile)

The URL must point directly to the download, not the GitHub profile page.
$outFile must include a filename, not just the Desktop folder.
GetFolderPath finds your actual Desktop, including a redirected Desktop.
Downloading again to the same filename replaces that downloaded file.
Open the downloaded HTML file in your browser to play.

These are Windows PowerShell commands, not commands for the game's simulated
terminal or the default Linux/Kali shell.
