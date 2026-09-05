[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $python = $venvPython
} else {
    $pythonCommand = (Get-Command python -ErrorAction Stop).Source
    $python = (& $pythonCommand -c "import sys; print(sys.executable)").Trim()
}
if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "A concrete Python executable could not be resolved"
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "pythonw.exe was not found beside the selected Python executable"
}
$bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path -LiteralPath $bash -PathType Leaf)) {
    throw "Git Bash executable was not found"
}
$homePath = [Environment]::GetFolderPath("UserProfile")
$meditationRunner = Join-Path $homePath ".claude\scripts\meditation\run-nightly.sh"
$meditationLine = Join-Path $homePath ".claude\meditations\digests\latest-line.txt"
$fleetRunner = Join-Path $homePath ".claude\scripts\fleet-briefing\run-daily.sh"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $repo "runs\task-backups\$stamp"
}
$backupDir = [IO.Path]::GetFullPath($BackupRoot)
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$taskNames = @("discovery-loop-night", "NightlyMeditation", "FleetBriefing7am")
$backups = [ordered]@{}
foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $backup = Join-Path $backupDir "$taskName.xml"
    Export-ScheduledTask -TaskName $taskName | Out-File -LiteralPath $backup -Encoding unicode
    $backups[$taskName] = $backup
}
$dashboardTaskName = "discovery-loop-dashboard"
$dashboardExisting = Get-ScheduledTask -TaskName $dashboardTaskName -ErrorAction SilentlyContinue
if ($dashboardExisting) {
    $dashboardBackup = Join-Path $backupDir "$dashboardTaskName.xml"
    Export-ScheduledTask -TaskName $dashboardTaskName | Out-File -LiteralPath $dashboardBackup -Encoding unicode
    $backups[$dashboardTaskName] = $dashboardBackup
}

$nightScript = Join-Path $repo "night.py"
$morningScript = Join-Path $repo "scripts\morning-research.py"
$nightArguments = "-u `"$nightScript`" --scheduled"
$meditationArguments = "-u `"$morningScript`" --mode meditation-context --next-executable `"$bash`" --next-argument `"$meditationRunner`""
$fleetArguments = "-u `"$morningScript`" --mode fleet --meditation-line `"$meditationLine`" --next-executable `"$bash`" --next-argument `"$fleetRunner`""
$dashboardScript = Join-Path $repo "dashboard.py"
$dashboardArguments = "`"$dashboardScript`""

$plan = [ordered]@{
    apply_requested = [bool]$Apply
    rollback_directory = $backupDir
    tasks = @(
        [ordered]@{
            name = "discovery-loop-night"
            trigger = "daily 22:00"
            action = "$python $nightArguments"
            settings = [ordered]@{
                execution_time_limit = "PT8H15M"
                multiple_instances = "IgnoreNew"
                wake_to_run = $true
                start_when_available = $true
                catch_up_window = "21:50-06:00 enforced by night.py --scheduled"
            }
        },
        [ordered]@{
            name = "NightlyMeditation"
            trigger = "existing daily 06:40"
            action = "$python $meditationArguments"
            settings = [ordered]@{
                execution_time_limit = "PT30M"
                multiple_instances = "IgnoreNew"
                wake_to_run = $false
                start_when_available = $false
                context = "sanitized morning report injected into the existing runner in memory"
            }
        },
        [ordered]@{
            name = "FleetBriefing7am"
            trigger = "existing daily 06:57"
            action = "$python $fleetArguments"
            settings = "all existing settings preserved"
            dependency = "requires latest-line.txt newer than today's NightlyMeditation start"
        },
        [ordered]@{
            name = $dashboardTaskName
            trigger = "at logon for the current user"
            action = "$pythonw $dashboardArguments"
            settings = [ordered]@{
                execution_time_limit = "unlimited"
                multiple_instances = "IgnoreNew"
                wake_to_run = $false
                start_when_available = $true
                visibility = "localhost only; no browser is opened"
            }
        }
    )
    rollback = @(
        "schtasks.exe /Create /TN discovery-loop-night /XML `"$($backups['discovery-loop-night'])`" /F",
        "schtasks.exe /Create /TN NightlyMeditation /XML `"$($backups['NightlyMeditation'])`" /F",
        "schtasks.exe /Create /TN FleetBriefing7am /XML `"$($backups['FleetBriefing7am'])`" /F"
    )
}
if ($dashboardExisting) {
    $plan.rollback += "schtasks.exe /Create /TN $dashboardTaskName /XML `"$($backups[$dashboardTaskName])`" /F"
} else {
    $plan.rollback += "Unregister-ScheduledTask -TaskName $dashboardTaskName -Confirm:`$false"
}

$plan | ConvertTo-Json -Depth 8
if (-not $Apply) {
    Write-Host "Review only. Re-run with -Apply to register these task changes."
    exit 0
}

try {
    $nightAction = New-ScheduledTaskAction -Execute $python -Argument $nightArguments -WorkingDirectory $repo
    $nightTrigger = New-ScheduledTaskTrigger -Daily -At "22:00"
    $nightSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 8 -Minutes 15) `
        -MultipleInstances IgnoreNew `
        -WakeToRun `
        -StartWhenAvailable
    Set-ScheduledTask -TaskName "discovery-loop-night" -Action $nightAction -Trigger $nightTrigger -Settings $nightSettings | Out-Null

    $meditationAction = New-ScheduledTaskAction -Execute $python -Argument $meditationArguments -WorkingDirectory $repo
    $meditationSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -MultipleInstances IgnoreNew
    Set-ScheduledTask -TaskName "NightlyMeditation" -Action $meditationAction -Settings $meditationSettings | Out-Null

    $fleetAction = New-ScheduledTaskAction -Execute $python -Argument $fleetArguments -WorkingDirectory $repo
    Set-ScheduledTask -TaskName "FleetBriefing7am" -Action $fleetAction | Out-Null

    $dashboardAction = New-ScheduledTaskAction -Execute $pythonw -Argument $dashboardArguments -WorkingDirectory $repo
    $dashboardTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
    $dashboardSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable
    $dashboardPrincipal = New-ScheduledTaskPrincipal `
        -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $dashboardTaskName `
        -Action $dashboardAction `
        -Trigger $dashboardTrigger `
        -Settings $dashboardSettings `
        -Principal $dashboardPrincipal `
        -Description "Local discovery-loop evidence dashboard" `
        -Force | Out-Null
} catch {
    foreach ($taskName in $taskNames) {
        schtasks.exe /Create /TN $taskName /XML $backups[$taskName] /F | Out-Null
    }
    if ($dashboardExisting) {
        schtasks.exe /Create /TN $dashboardTaskName /XML $backups[$dashboardTaskName] /F | Out-Null
    } else {
        # RM_OK: rollback an incompletely created task after an explicitly approved -Apply run.
        Unregister-ScheduledTask -TaskName $dashboardTaskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    throw
}

Write-Host "Applied. Rollback XML is in $backupDir"
