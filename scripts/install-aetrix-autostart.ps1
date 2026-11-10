param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'show')]
    [string]$Action = 'show'
)

# =============================================================================
#  Registers (or removes) the Windows logon task that brings the stack up after
#  a reboot, using the same entry point a manual start uses.
#
#  The task runs `scripts\aetrix-stack.ps1 start`, which is idempotent: if the
#  stack is already managed it re-verifies the connection instead of starting a
#  second backend or a second Funnel route.
#
#  Registering a task needs an elevated prompt on most machines. This script
#  never elevates itself; it reports what Windows said and stops.
# =============================================================================

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Stack = Join-Path $PSScriptRoot 'aetrix-stack.ps1'
$TaskName = 'Aetrix V5.5 stack'
$PowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Description = 'Starts the Aetrix backend, the Tailscale Funnel route and the supervisor after logon.'

if (-not (Test-Path $Stack)) { throw "Missing $Stack." }

function Get-ExistingTask {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { return $null }
    return $task
}

switch ($Action) {
    'install' {
        $arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" start' -f $Stack
        # Names must not collide with the validated $Action parameter: PowerShell
        # variable names are case-insensitive, so $action would be re-validated
        # against the install/uninstall/show set and fail.
        $taskAction = New-ScheduledTaskAction -Execute $PowerShell -Argument $arguments -WorkingDirectory $Root
        $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
        try {
            Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger `
                -Settings $taskSettings -Description $Description -Force | Out-Null
        } catch {
            Write-Host "[ERROR] Could not register the logon task: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host '        Run this from an elevated PowerShell, or create the task manually with the'
            Write-Host '        trigger and command printed by: AUTOSTART_AETRIX.bat show'
            exit 1
        }
        Write-Host "[OK] Logon task '$TaskName' registered." -ForegroundColor Green
        Write-Host "     Runs: $PowerShell $arguments"
        Write-Host '     It is safe to run START_AETRIX.bat yourself while the task is starting.'
    }
    'uninstall' {
        if ($null -eq (Get-ExistingTask)) {
            Write-Host "[OK] No '$TaskName' task is registered; nothing to remove." -ForegroundColor Green
            exit 0
        }
        try {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        } catch {
            Write-Host "[ERROR] Could not remove the task: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host '        Run this from an elevated PowerShell.'
            exit 1
        }
        Write-Host "[OK] Logon task '$TaskName' removed." -ForegroundColor Green
    }
    'show' {
        $task = Get-ExistingTask
        if ($null -eq $task) {
            Write-Host "No '$TaskName' task is registered. Install it with: AUTOSTART_AETRIX.bat install"
            Write-Host ''
            Write-Host 'Equivalent manual registration (elevated PowerShell):'
            Write-Host ('  Register-ScheduledTask -TaskName "{0}" -Trigger (New-ScheduledTaskTrigger -AtLogOn) ' -f $TaskName)
            Write-Host ('    -Action (New-ScheduledTaskAction -Execute "{0}" -Argument ''-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{1}" start'')' -f $PowerShell, $Stack)
            exit 0
        }
        Write-Host "Task: $TaskName" -ForegroundColor Cyan
        $task | Select-Object TaskName, State | Format-List
        $task.Triggers | Format-List
        $task.Actions | Select-Object Execute, Arguments, WorkingDirectory | Format-List
    }
    default {
        Write-Host 'Usage: install-aetrix-autostart.ps1 [install|uninstall|show]'
        exit 2
    }
}
