param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"
$resolvedPath = (Resolve-Path -LiteralPath $Path).Path
$subject = "CN=ComprimiPDF Local Publisher"

$certificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object {
        $_.Subject -eq $subject -and
        $_.HasPrivateKey -and
        $_.NotAfter -gt (Get-Date)
    } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $certificate) {
    throw "Certificato di firma non trovato. Eseguire prima setup-local-signing.ps1."
}

Write-Host "Firma Authenticode di $resolvedPath..." -ForegroundColor Cyan
$signature = Set-AuthenticodeSignature `
    -LiteralPath $resolvedPath `
    -Certificate $certificate `
    -HashAlgorithm SHA256 `
    -IncludeChain All

if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Firma non valida: $($signature.Status) - $($signature.StatusMessage)"
}

$verification = Get-AuthenticodeSignature -LiteralPath $resolvedPath
if ($verification.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Verifica Authenticode non riuscita: $($verification.StatusMessage)"
}

Write-Host "Firma valida." -ForegroundColor Green
Write-Host "Editore: $($verification.SignerCertificate.GetNameInfo('SimpleName', $false))"
Write-Host "Impronta: $($verification.SignerCertificate.Thumbprint)"
