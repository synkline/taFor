[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:5000",
    [string]$OutputDirectory = "D:\AutoTAF\AutoPDF\VABB",
    [string]$PythonExe = "",
    [string]$TaskName = "AutoTAF VABB PDF Downloader"
)

$ErrorActionPreference = "Stop"
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$downloaderPath = Join-Path $projectDirectory "taf_downloader.py"

if (-not (Test-Path -LiteralPath $downloaderPath -PathType Leaf)) {
    throw "Downloader script not found: $downloaderPath"
}

if (-not $PythonExe) {
    $pythonCommand = Get-Command python.exe -ErrorAction Stop
    $PythonExe = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python interpreter not found: $PythonExe"
}

& $PythonExe -c "import sys; print(sys.executable); print(sys.version); sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.9 or newer is required. Choose the interpreter that will run the downloader."
}

$baseUri = [Uri]$BaseUrl
if ($baseUri.Scheme -notin @("http", "https") -or -not $baseUri.Host) {
    throw "BaseUrl must be an HTTP or HTTPS URL, such as http://127.0.0.1:5000."
}
if ($BaseUrl.Contains('"')) {
    throw 'BaseUrl cannot contain a double quote.'
}

$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "A task named '$TaskName' already exists. Choose another -TaskName or remove the existing task in Task Scheduler first."
}

$quotedDownloader = '"{0}"' -f $downloaderPath
$quotedBaseUrl = '"{0}"' -f $BaseUrl.TrimEnd('/')
$quotedOutputDirectory = '"{0}"' -f $OutputDirectory
$arguments = "$quotedDownloader --base-url $quotedBaseUrl --output-dir $quotedOutputDirectory --attempts 3 --timeout 600"
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory $projectDirectory

# Four daily triggers, six hours apart, keep the schedule recurring without
# relying on repetition parameters that New-ScheduledTaskTrigger only exposes
# for one-time triggers. StartWhenAvailable catches up after a missed run.
$firstRun = (Get-Date).AddMinutes(1)
$triggers = @()
for ($offsetHours = 0; $offsetHours -lt 24; $offsetHours += 6) {
    $triggerAt = $firstRun.AddHours($offsetHours)
    $triggers += New-ScheduledTaskTrigger -Daily -At $triggerAt -DaysInterval 1
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal `
    -Description "Downloads fresh VABB Long and Short TAFs from the existing Auto-TAF app every six hours." | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "Python: $PythonExe"
Write-Host "Auto-TAF URL: $($BaseUrl.TrimEnd('/'))"
Write-Host "PDF directory: $OutputDirectory"
Write-Host "The task runs as $identity when that user is logged in. Task Scheduler is set to start missed runs when available and ignore overlaps."
Write-Host "Run a one-off manual check with:"
Write-Host "& `"$PythonExe`" `"$downloaderPath`" --base-url `"$($BaseUrl.TrimEnd('/'))`" --output-dir `"$OutputDirectory`""
