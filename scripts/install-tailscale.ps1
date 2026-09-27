$ErrorActionPreference = 'Stop'
$installerPath = Join-Path $env:TEMP 'SecurityWebCam-tailscale-setup.exe'
Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' -OutFile $installerPath
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Tailscale') {
    throw 'Assinatura do instalador Tailscale inválida.'
}
Write-Host 'A instalação do driver/serviço Tailscale pode solicitar aprovação UAC. Depois, entre na sua conta pelo aplicativo Tailscale.'
Start-Process -FilePath $installerPath -Wait -WindowStyle Hidden
