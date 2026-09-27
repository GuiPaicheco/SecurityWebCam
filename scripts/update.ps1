$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (git status --porcelain) { throw 'Há alterações locais. Faça commit ou backup antes de atualizar.' }
& '.\.venv\Scripts\python.exe' -m securitywebcam --shutdown
if ($LASTEXITCODE -ne 0) { throw 'O aplicativo ainda está ativo. Atualização interrompida.' }
& git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar o repositório.' }
& (Join-Path $PSScriptRoot 'install.ps1') -NoLaunch
if ($LASTEXITCODE -ne 0) { throw 'Falha na reinstalação.' }
Write-Host 'Atualizado. Abra o aplicativo pelo menu Iniciar.'
