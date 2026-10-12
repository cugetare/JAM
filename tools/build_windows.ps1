$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Dist = Join-Path $ProjectRoot "dist"
$Work = Join-Path $ProjectRoot "build\pyinstaller"
$Spec = Join-Path $ProjectRoot "build"
$Launcher = Join-Path $ProjectRoot "jam_launcher.py"
$Output = Join-Path $ProjectRoot "JAM.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing virtual environment: $Python"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name JAM `
    --distpath $Dist `
    --workpath $Work `
    --specpath $Spec `
    $Launcher

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Copy-Item -LiteralPath (Join-Path $Dist "JAM.exe") -Destination $Output -Force
$Artifact = Get-Item -LiteralPath $Output
$Hash = Get-FileHash -LiteralPath $Output -Algorithm SHA256
Write-Host "Built $($Artifact.FullName)"
Write-Host "Size: $($Artifact.Length) bytes"
Write-Host "SHA256: $($Hash.Hash)"
