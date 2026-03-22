$pidFile = "$env:USERPROFILE\.iflow\guardian.pid"

if (Test-Path $pidFile) {
    $pid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($pid) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) { exit 0 }
    }
}

$PID | Out-File $pidFile -Encoding UTF8
& "C:\Users\55237\iflow-memory-system\iflow_guardian.ps1"