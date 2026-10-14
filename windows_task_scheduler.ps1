[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Register", "Enable", "Disable", "Remove", "Status")]
    [string]$Action,
    [string]$TaskName = "AutoTAF VABB PDF Downloader",
    [string]$ExePath = "",
    [string]$Arguments = ""
)

$ErrorActionPreference = "Stop"

function Get-ExistingTask {
    return Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

switch ($Action) {
    "Register" {
        if (-not $ExePath -or -not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
            throw "Downloader executable was not found: $ExePath"
        }

        $executable = [System.IO.Path]::GetFullPath($ExePath)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $triggers = @()
        foreach ($hour in @(0, 6, 12, 18)) {
            $triggers += New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($hour))
        }
        $actionDefinition = New-ScheduledTaskAction `
            -Execute $executable `
            -Argument $Arguments `
            -WorkingDirectory (Split-Path -Parent $executable)
        $settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -WakeToRun `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 5)
        $principal = New-ScheduledTaskPrincipal `
            -UserId $identity `
            -LogonType Interactive `
            -RunLevel Limited

        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $actionDefinition `
            -Trigger $triggers `
            -Settings $settings `
            -Principal $principal `
            -Description "Downloads fresh VABB Long and Short TAF PDFs from the configured Auto-TAF website." `
            -Force | Out-Null
        Write-Output "Registered $TaskName for 00:00, 06:00, 12:00, and 18:00 local time as $identity."
    }
    "Enable" {
        if (-not (Get-ExistingTask)) { throw "Scheduled task '$TaskName' is not installed." }
        Enable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Output "Enabled $TaskName."
    }
    "Disable" {
        if (-not (Get-ExistingTask)) { throw "Scheduled task '$TaskName' is not installed." }
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Output "Disabled $TaskName."
    }
    "Remove" {
        if (Get-ExistingTask) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Output "Removed $TaskName. Downloaded PDFs were not changed."
        }
    }
    "Status" {
        $task = Get-ExistingTask
        if (-not $task) { Write-Output "Not installed"; exit 0 }
        Write-Output ("{0}: {1}" -f $TaskName, $task.State)
    }
}
