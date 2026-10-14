[CmdletBinding()]
param(
    [string]$PythonExe = "python.exe",
    [string]$InnoCompiler = "",
    [string]$SigningCertificateThumbprint = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$specFile = Join-Path $PSScriptRoot "autotaf_downloader.spec"
$installerScript = Join-Path $PSScriptRoot "AutoTAF-Downloader.iss"
$distDirectory = Join-Path $projectRoot "release"
$workDirectory = Join-Path $projectRoot "build\pyinstaller"
$exePath = Join-Path $distDirectory "AutoTAF-Downloader.exe"
$installerPath = Join-Path $distDirectory "AutoTAF-Downloader-Setup.exe"

if (-not (Test-Path -LiteralPath $specFile -PathType Leaf)) {
    throw "PyInstaller specification is missing: $specFile"
}
$null = New-Item -ItemType Directory -Path $distDirectory -Force

& $PythonExe -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not available to '$PythonExe'. Install it in the build environment with: python -m pip install pyinstaller"
}

& $PythonExe -m PyInstaller --clean --noconfirm `
    --distpath $distDirectory `
    --workpath $workDirectory `
    $specFile
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "PyInstaller did not produce $exePath"
}
Write-Host "Built downloader executable: $exePath"

if (-not $InnoCompiler) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        $InnoCompiler = $command.Source
    } else {
        $candidatePaths = @()
        if ($env:ProgramFiles) { $candidatePaths += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe") }
        if (${env:ProgramFiles(x86)}) { $candidatePaths += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe") }
        if ($env:LOCALAPPDATA) { $candidatePaths += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe") }
        $InnoCompiler = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    Write-Error "Inno Setup 6 ISCC.exe was not found. The downloader EXE is built, but the installer is not. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php, then rerun this script."
    exit 2
}

& $InnoCompiler $installerScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Inno Setup did not produce $installerPath"
}

if ($SigningCertificateThumbprint) {
    $signToolPath = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signToolPath -and ${env:ProgramFiles(x86)}) {
        $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
        $sdkSignTools = Get-ChildItem -LiteralPath $sdkRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending
        if ($sdkSignTools) { $signToolPath = ($sdkSignTools | Select-Object -First 1).FullName }
    }
    if (-not $signToolPath) {
        throw "A signing certificate thumbprint was supplied, but signtool.exe was not found in the Windows SDK."
    }
    & $signToolPath sign /fd SHA256 /sha1 $SigningCertificateThumbprint `
        /tr "http://timestamp.digicert.com" /td SHA256 $installerPath
    if ($LASTEXITCODE -ne 0) { throw "Signing the installer failed." }
}

$hash = Get-FileHash -LiteralPath $installerPath -Algorithm SHA256
Write-Host "Installer: $installerPath"
Write-Host "SHA-256: $($hash.Hash)"
