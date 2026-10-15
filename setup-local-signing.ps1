$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$subject = "CN=ComprimiPDF Local Publisher"
$friendlyName = "ComprimiPDF - firma locale"
$certificateFolder = Join-Path $PSScriptRoot "certificates"
$publicCertificate = Join-Path $certificateFolder "ComprimiPDF-Local-Publisher.cer"

$certificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $certificate) {
    Write-Host "Creazione del certificato locale di firma codice..." -ForegroundColor Cyan
    $certificate = New-SelfSignedCertificate `
        -Subject $subject `
        -FriendlyName $friendlyName `
        -Type CodeSigningCert `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(5)
} else {
    Write-Host "Certificato locale già presente." -ForegroundColor DarkCyan
}

New-Item -ItemType Directory -Force -Path $certificateFolder | Out-Null
Export-Certificate -Cert $certificate -FilePath $publicCertificate -Force | Out-Null

# La chiave privata rimane esclusivamente in CurrentUser\My. Nei due archivi
# attendibili viene importata soltanto la parte pubblica del certificato.
Import-Certificate -FilePath $publicCertificate -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
Import-Certificate -FilePath $publicCertificate -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null

$trustedRoot = Get-ChildItem Cert:\CurrentUser\Root\$($certificate.Thumbprint) -ErrorAction SilentlyContinue
$trustedPublisher = Get-ChildItem Cert:\CurrentUser\TrustedPublisher\$($certificate.Thumbprint) -ErrorAction SilentlyContinue
if (-not $trustedRoot -or -not $trustedPublisher) {
    throw "Installazione del certificato negli archivi attendibili non riuscita."
}

Write-Host "Certificato pronto." -ForegroundColor Green
Write-Host "Editore: $($certificate.GetNameInfo('SimpleName', $false))"
Write-Host "Impronta: $($certificate.Thumbprint)"
Write-Host "Scadenza: $($certificate.NotAfter.ToString('dd/MM/yyyy'))"
Write-Host "Certificato pubblico: $publicCertificate"
