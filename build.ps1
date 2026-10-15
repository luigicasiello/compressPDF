$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installazione dipendenze..." -ForegroundColor Cyan
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Installazione delle dipendenze non riuscita (codice $LASTEXITCODE)."
}

$defaultDist = Join-Path $PSScriptRoot "dist"
$defaultExe = Join-Path $defaultDist "ComprimiPDF.exe"
$defaultRunning = Get-CimInstance Win32_Process -Filter "Name = 'ComprimiPDF.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $defaultExe }

# Un eseguibile Windows in uso non può essere sostituito. In quel caso la nuova
# build viene pubblicata in una sottocartella, senza interrompere l'app aperta.
$distPath = if ($defaultRunning) { Join-Path $defaultDist "release" } else { $defaultDist }
$outputExe = Join-Path $distPath "ComprimiPDF.exe"
$targetRunning = Get-CimInstance Win32_Process -Filter "Name = 'ComprimiPDF.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $outputExe }
if ($targetRunning) {
    throw "Anche la versione di destinazione è in esecuzione: $outputExe"
}

Write-Host "Creazione dell'eseguibile standalone..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ComprimiPDF" `
    --distpath $distPath `
    --icon "assets\dog_mascot.ico" `
    --add-data "assets;assets" `
    --collect-all pymupdf `
    app.py

if ($LASTEXITCODE -ne 0) {
    throw "Creazione dell'eseguibile non riuscita (codice $LASTEXITCODE)."
}

$signingCertificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq "CN=ComprimiPDF Local Publisher" -and $_.NotAfter -gt (Get-Date) } |
    Select-Object -First 1
if (-not $signingCertificate) {
    Write-Host "Configurazione iniziale della firma locale..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "setup-local-signing.ps1")
}

& (Join-Path $PSScriptRoot "sign-executable.ps1") -Path $outputExe

Write-Host "" 
Write-Host "Eseguibile creato in: $outputExe" -ForegroundColor Green
