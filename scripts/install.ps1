param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Instale Python 3.14 para o usuário atual em https://www.python.org/downloads/windows/ e execute novamente.'
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    throw 'Instale FFmpeg 8.0.1 (ffmpeg e ffprobe no PATH). Consulte README.md.'
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & py -3.14 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente Python 3.14.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
$pythonwPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$launcherPath = Join-Path $projectRoot 'launcher.pyw'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SecurityWebCam'
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startMenu 'SecurityWebCam.lnk'))
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + $launcherPath + '" --open'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7
$shortcut.Save()
$stopShortcut = $shell.CreateShortcut((Join-Path $startMenu 'Encerrar SecurityWebCam.lnk'))
$stopShortcut.TargetPath = $pythonwPath
$stopShortcut.Arguments = '"' + $launcherPath + '" --shutdown'
$stopShortcut.WorkingDirectory = $projectRoot
$stopShortcut.WindowStyle = 7
$stopShortcut.Save()
Write-Host 'Instalado. Use SecurityWebCam no menu Iniciar. Inicialização automática permanece conforme a opção do aplicativo (desativada em instalação nova).'
if (-not $NoLaunch) {
    Start-Process -FilePath $pythonwPath -ArgumentList ('"' + $launcherPath + '" --open') -WorkingDirectory $projectRoot -WindowStyle Hidden
}
