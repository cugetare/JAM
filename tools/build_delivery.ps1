$ErrorActionPreference = "Stop"

$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$DeliveryRoot = Join-Path $ProjectRoot "Delivery"
$PackageRoot = Join-Path $DeliveryRoot "JAM-Virgin"
$ArchivePath = Join-Path $DeliveryRoot "JAM-Virgin-Windows-x64.zip"
$SourcePython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RuntimePython = Join-Path $PackageRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $SourcePython -PathType Leaf)) {
    throw "The development Python environment is missing: $SourcePython"
}

$resolvedProject = [System.IO.Path]::GetFullPath($ProjectRoot)
$resolvedDelivery = [System.IO.Path]::GetFullPath($DeliveryRoot)
$resolvedPackage = [System.IO.Path]::GetFullPath($PackageRoot)
if (-not $resolvedDelivery.StartsWith($resolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Delivery must remain inside the JAM project."
}
if (-not $resolvedPackage.StartsWith($resolvedDelivery, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Package target must remain inside Delivery."
}

New-Item -ItemType Directory -Path $DeliveryRoot -Force | Out-Null
if (Test-Path -LiteralPath $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null

& $SourcePython -m venv $PackageRoot\.venv
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the clean delivery runtime."
}

& $RuntimePython -m pip install --disable-pip-version-check --no-cache-dir `
    -r (Join-Path $ProjectRoot "requirements-runtime.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the delivery runtime dependencies."
}

Copy-Item -LiteralPath (Join-Path $ProjectRoot "JAM.exe") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "streamlit_app.py") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "jam_launcher.py") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "DELIVERY_README.md") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.example.toml") `
    -Destination (Join-Path $PackageRoot "config.toml")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.example.toml") -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "agent_instructions.example.md") `
    -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "candidate_facts.example.md") `
    -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "requirements-runtime.txt") `
    -Destination $PackageRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "jam") `
    -Destination (Join-Path $PackageRoot "jam") -Recurse

$DataRoot = Join-Path $PackageRoot "data"
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DataRoot "Applications") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "agent_instructions.example.md") `
    -Destination (Join-Path $DataRoot "agent_instructions.md")

$forbidden = @(
    (Join-Path $PackageRoot "data\jam.sqlite3"),
    (Join-Path $PackageRoot "data\candidate_profile.json"),
    (Join-Path $PackageRoot "data\candidate_facts.md"),
    (Join-Path $PackageRoot "data\Bewerbungsliste.xlsx")
)
foreach ($path in $forbidden) {
    if (Test-Path -LiteralPath $path) {
        throw "Personal or generated data leaked into the package: $path"
    }
}

$checks = @(
    "import streamlit",
    "import jam",
    "import openai",
    "import docx",
    "import openpyxl",
    "import win32com.client"
)
& $RuntimePython -c ($checks -join "; ")
if ($LASTEXITCODE -ne 0) {
    throw "The clean delivery runtime failed its import check."
}

& (Join-Path $PackageRoot "JAM.exe") --check
if ($LASTEXITCODE -ne 0) {
    throw "The packaged JAM launcher failed its readiness check."
}

Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force -Directory |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force -File -Filter "*.pyc" |
    Remove-Item -Force

$files = Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force -File
$totalBytes = ($files | Measure-Object Length -Sum).Sum
$manifest = [ordered]@{
    package = "JAM-Virgin"
    created_at = (Get-Date).ToString("o")
    architecture = "Windows x64"
    file_count = $files.Count
    uncompressed_bytes = $totalBytes
    contains_candidate_profiles = $false
    contains_application_database = $false
    contains_generated_applications = $false
    launcher_sha256 = (Get-FileHash -LiteralPath (Join-Path $PackageRoot "JAM.exe") -Algorithm SHA256).Hash
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PackageRoot "manifest.json") -Encoding UTF8

Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ArchivePath -CompressionLevel Optimal
$archive = Get-Item -LiteralPath $ArchivePath
$archiveHash = Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256

Write-Host "Delivery folder: $PackageRoot"
Write-Host "Uncompressed bytes: $totalBytes"
Write-Host "Archive: $($archive.FullName)"
Write-Host "Archive bytes: $($archive.Length)"
Write-Host "Archive SHA256: $($archiveHash.Hash)"
