# update_heartbeat.ps1 - 更新心跳文件
param(
    [string]$Summary = "对话进行中"
)

$heartbeatFile = "$env:USERPROFILE\.iflow\heartbeat.json"

$heartbeat = @{
    lastActive = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    lastSummary = $Summary
    pid = $PID
}

$heartbeat | ConvertTo-Json | Out-File $heartbeatFile -Encoding utf8
Write-Host "Heartbeat updated: $Summary"
