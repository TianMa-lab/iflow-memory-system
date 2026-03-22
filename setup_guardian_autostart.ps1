# Guardian Auto-Start Setup Script

param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status
)

$TaskName = "iFlow Guardian"
$ScriptPath = "$env:USERPROFILE\iflow-memory-system\iflow_guardian.ps1"
$WrapperPath = "$env:USERPROFILE\iflow-memory-system\start_guardian.ps1"

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Task Status: $($task.State)"
    } else {
        Write-Host "Task not found"
    }
    exit 0
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Guardian auto-start task removed"
    exit 0
}

if ($Install) {
    $scriptDir = Split-Path $ScriptPath -Parent
    if (-not (Test-Path $scriptDir)) {
        Write-Host "Error: Script directory not found"
        exit 1
    }
    
    # Create wrapper script
    $WrapperContent = @'
$pidFile = "$env:USERPROFILE\.iflow\guardian.pid"

if (Test-Path $pidFile) {
    $pid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($pid) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) { exit 0 }
    }
}

$PID | Out-File $pidFile -Encoding UTF8
& "SCRIPT_PATH_PLACEHOLDER"
'@
    $WrapperContent = $WrapperContent.Replace('SCRIPT_PATH_PLACEHOLDER', $ScriptPath)
    [System.IO.File]::WriteAllText($WrapperPath, $WrapperContent, [System.Text.Encoding]::UTF8)
    Write-Host "Wrapper created: $WrapperPath"
    
    # Create scheduled task
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WrapperPath`""
    $Trigger = New-ScheduledTaskTrigger -AtLogon
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "iFlow Guardian daemon" | Out-Null
    
    Write-Host "Guardian auto-start task created!"
    Write-Host "Will run at next login."
    
    Start-Sleep -Seconds 1
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Task State: $($task.State)"
    }
}
