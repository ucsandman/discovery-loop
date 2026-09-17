[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$At = "07:00",
    [string]$BackupRoot = ""
)

# Registers discovery-loop-morning: every day at $At, open the morning brief in the default browser
# (starting the loopback dashboard first if it is not running). Preview by default; -Apply registers.

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
$script = Join-Path $repo "scripts\morning-open.py"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "scripts\morning-open.py is missing"
}
$taskName = "discovery-loop-morning"
$arguments = "`"$script`""
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $repo "runs\task-backups\$stamp"
}
$backupDir = [IO.Path]::GetFullPath($BackupRoot)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$rollback = "Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
if ($existing) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backup = Join-Path $backupDir "$taskName.xml"
    Export-ScheduledTask -TaskName $taskName | Out-File -LiteralPath $backup -Encoding unicode
    $rollback = "schtasks.exe /Create /TN $taskName /XML `"$backup`" /F"
}

$plan = [ordered]@{
    apply_requested = [bool]$Apply
    task = [ordered]@{
        name = $taskName
        trigger = "daily $At"
        action = "$pythonw $arguments"
        settings = [ordered]@{
            execution_time_limit = "PT5M"
            multiple_instances = "IgnoreNew"
            start_when_available = $true
            principal = "current user, interactive, limited (a browser window needs the desktop)"
        }
    }
    rollback = $rollback
}
$plan | ConvertTo-Json -Depth 6
if (-not $Apply) {
    Write-Host "Review only. Re-run with -Apply to register the task."
    exit 0
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Open the discovery-loop morning brief every morning" `
    -Force | Out-Null
$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
[ordered]@{
    registered = $task.TaskName
    state = [string]$task.State
    next_run = $info.NextRunTime
    action = ($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join " | "
} | ConvertTo-Json
