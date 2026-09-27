$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& '.\.venv\Scripts\python.exe' -m securitywebcam --shutdown
if ($LASTEXITCODE -ne 0) { throw 'O aplicativo ainda está ativo. Desinstalação interrompida.' }
& '.\.venv\Scripts\python.exe' -c "from securitywebcam.config import Config; from securitywebcam.platform import autostart; from pathlib import Path; import os; c=Config(Path(os.environ['LOCALAPPDATA'])/'SecurityWebCam'); autostart(False); c.save({'autostart':False})"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao remover inicialização automática.' }
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SecurityWebCam'
foreach ($name in @('SecurityWebCam.lnk','Encerrar SecurityWebCam.lnk')) {
    $shortcutPath = Join-Path $startMenu $name
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
}
Write-Host 'Aplicativo encerrado e atalhos/autoinicialização removidos. Gravações, configurações, cópias OneDrive e código preservados.'
Write-Host 'Se configurou Tailscale Serve, remova apenas a regra deste aplicativo conforme o README. Você pode excluir manualmente a pasta do código após guardar o que precisar.'
