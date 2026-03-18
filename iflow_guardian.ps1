# iFlow Guardian v2.4 - 守护进程 + 自动记忆记录 + AGENTS.md 注入 + 自动归档

param(
    [string]$TaskFile = "$env:USERPROFILE\.iflow\tasks\pending.json",
    [string]$HeartbeatFile = "$env:USERPROFILE\.iflow\heartbeat.json",
    [string]$MemoryFile = "$env:USERPROFILE\.iflow\MEMORY.md",
    [string]$AgentsFile = "$env:USERPROFILE\.iflow\AGENTS.md",
    [string]$ArchiveFile = "$env:USERPROFILE\.iflow\AGENTS_archive.md",
    [int]$PollInterval = 10,
    [int]$IdleThreshold = 60,
    [int]$MaxAgentsLines = 100  # AGENTS.md 最大行数
)

$logFile = "$env:USERPROFILE\.iflow\logs\guardian.log"

function Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $msg" | Out-File $logFile -Append -Encoding UTF8
}

function Get-PendingTask {
    if (Test-Path $TaskFile) {
        try { return Get-Content $TaskFile -Raw | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

function Mark-Recovering($task) {
    $task | Add-Member -NotePropertyName "status" -NotePropertyValue "recovering" -Force
    $task | ConvertTo-Json -Depth 10 | Out-File $TaskFile -Encoding utf8
}

function Get-Heartbeat {
    if (Test-Path $HeartbeatFile) {
        try { return Get-Content $HeartbeatFile -Raw | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

function Record-To-DAG($summary) {
    $pythonCmd = "conda run -n p311 python `"$env:USERPROFILE\.iflow\tools\dag_tools.py`" add --content=`"$summary`" --topic=`"自动记录`" --role=`"assistant`""
    try {
        $result = Invoke-Expression $pythonCmd 2>&1
        return $result
    } catch {
        return "Error: $_"
    }
}

function Append-To-Memory($summary) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "`n## $timestamp`n$summary`n"
    try {
        Add-Content -Path $MemoryFile -Value $entry -Encoding UTF8
        return "OK"
    } catch {
        return "Error: $_"
    }
}

function Append-To-Agents($summary) {
    $date = Get-Date -Format "yyyy-MM-dd"
    $entry = "- [$date] $summary`n"
    try {
        $content = Get-Content $AgentsFile -Raw -Encoding UTF8
        if ($content -notmatch [regex]::Escape($summary.Substring(0, [Math]::Min(50, $summary.Length)))) {
            Add-Content -Path $AgentsFile -Value $entry -Encoding UTF8
            return "OK"
        }
        return "Duplicate"
    } catch {
        return "Error: $_"
    }
}

function Archive-Old-Memories {
    try {
        $lines = Get-Content $AgentsFile -Encoding UTF8
        if ($lines.Count -gt $MaxAgentsLines) {
            Log("AGENTS.md has $($lines.Count) lines, archiving old memories...")
            
            # 保留前2行（标题）和最后80行（最近记忆）
            $header = $lines[0..1]
            $recent = $lines[($lines.Count - 80)..($lines.Count - 1)]
            
            # 归档旧内容
            $oldContent = $lines[2..($lines.Count - 81)] -join "`n"
            $archiveHeader = "`n## 归档于 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"
            Add-Content -Path $ArchiveFile -Value $archiveHeader -Encoding UTF8
            Add-Content -Path $ArchiveFile -Value $oldContent -Encoding UTF8
            
            # 写入新内容
            $newContent = ($header + $recent) -join "`n"
            [System.IO.File]::WriteAllText($AgentsFile, $newContent, [System.Text.Encoding]::UTF8)
            
            Log("Archived $($lines.Count - 82) old memories")
            return "Archived"
        }
        return "OK"
    } catch {
        Log("Archive error: $_")
        return "Error: $_"
    }
}

Log("Guardian v2.4 started (with auto-archiving, max $MaxAgentsLines lines)")

$lastRecordedTime = $null

while ($true) {
    # === 1. 任务恢复检测 ===
    $task = Get-PendingTask
    if ($task -and $task.status -ne "recovering") {
        Log("Found pending task: $($task.description)")
        Mark-Recovering $task
        
        $prompt = "[恢复模式] 读取任务文件 $TaskFile 并继续处理"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "iflow -p '$prompt'"
        Log("Started recovery session")
    }
    
    # === 2. 心跳检测 & 自动记录 ===
    $heartbeat = Get-Heartbeat
    if ($heartbeat) {
        try {
            $lastActive = [DateTime]::Parse($heartbeat.lastActive)
            $idleSeconds = ((Get-Date) - $lastActive).TotalSeconds
            
            if ($idleSeconds -gt $IdleThreshold) {
                if ($lastRecordedTime -ne $heartbeat.lastActive) {
                    Log("Detected idle session (${idleSeconds}s), recording...")
                    
                    $summary = $heartbeat.lastSummary
                    
                    # 1. 记录到 DAG
                    $dagResult = Record-To-DAG "【自动记录】会话空闲 ${idleSeconds}秒，记录：$summary"
                    Log("DAG: $dagResult")
                    
                    # 2. 同步到 MEMORY.md
                    $memResult = Append-To-Memory "【自动记录】$summary"
                    Log("MEMORY.md: $memResult")
                    
                    # 3. 注入到 AGENTS.md
                    $agentsResult = Append-To-Agents $summary
                    Log("AGENTS.md: $agentsResult")
                    
                    # 4. 检查并归档
                    $archiveResult = Archive-Old-Memories
                    Log("Archive: $archiveResult")
                    
                    $lastRecordedTime = $heartbeat.lastActive
                }
            }
        } catch {
            Log("Error parsing heartbeat: $_")
        }
    }
    
    Start-Sleep -Seconds $PollInterval
}