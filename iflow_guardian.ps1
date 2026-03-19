# iFlow Guardian v2.8 - 守护进程 + 自动记忆记录(内容去重) + AGENTS.md 注入 + 自动归档 + 心跳停滞检测(去重) + DAG 定期维护

param(
      [string]$TaskFile = "$env:USERPROFILE\.iflow\tasks\pending.json",
      [string]$HeartbeatFile = "$env:USERPROFILE\.iflow\heartbeat.json",
      [string]$MemoryFile = "$env:USERPROFILE\.iflow\MEMORY.md",
      [string]$AgentsFile = "$env:USERPROFILE\.iflow\AGENTS.md",
      [string]$ArchiveFile = "$env:USERPROFILE\.iflow\AGENTS_archive.md",
      [string]$StallAlertFile = "$env:USERPROFILE\.iflow\tasks\stall_alert.json",
      [string]$MaintainLogFile = "$env:USERPROFILE\.iflow\logs\dag_maintain.log",
      [int]$PollInterval = 10,
      [int]$IdleThreshold = 60,
      [int]$MaxAgentsLines = 100,  # AGENTS.md 最大行数
      [int]$HeartbeatStallThreshold = 300,  # 心跳停滞阈值（秒），超过则触发提醒
      [int]$DagMaintainIntervalHours = 24,   # DAG 维护间隔（小时）
      [int]$HistoryScanIntervalHours = 6,  # 会话历史扫描间隔（小时）
      [int]$HealthCheckIntervalMinutes = 30  # 自我健康检查间隔（分钟）
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

function Append-To-Agents($summary, $isStallAlert = $false) {
    # 停滞提醒不再写入 AGENTS.md（AGENTS.md 是长期记忆，不应存储临时系统提醒）
    if ($isStallAlert) {
        return "Skipped (stall alerts no longer pollute AGENTS.md)"
    }
    
    $date = Get-Date -Format "yyyy-MM-dd"
    $entry = "- [$date] $summary`n"
    try {
        $content = Get-Content $AgentsFile -Raw -Encoding UTF8
        
        # 普通消息检查前 50 字符
        if ($content -match [regex]::Escape($summary.Substring(0, [Math]::Min(50, $summary.Length)))) {
            return "Duplicate"
        }        
        Add-Content -Path $AgentsFile -Value $entry -Encoding UTF8
        return "OK"
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

function Create-Stall-Alert($stallSeconds, $lastSummary) {
    try {
        $alert = @{
            timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            stallSeconds = $stallSeconds
            lastSummary = $lastSummary
            message = "心跳停滞超过 $HeartbeatStallThreshold 秒，可能需要手动更新心跳或检查会话状态"
            action = "请在下次对话开始时，主动调用 dag_tools.py add 或 update_heartbeat.ps1"
        }
        $alert | ConvertTo-Json -Depth 10 | Out-File $StallAlertFile -Encoding utf8
        return "Alert created"
    } catch {
        return "Error: $_"
    }
}

function Run-DAG-Maintenance {
    Log("Starting DAG maintenance...")
    # 直接使用 python 而不是 conda run，避免环境问题
    $pythonCmd = "python `"$env:USERPROFILE\.iflow\tools\dag_tools.py`" maintain --auto 2>&1"
    try {
        $result = Invoke-Expression $pythonCmd
        # 记录到专门的维护日志
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "=== $timestamp ===" | Out-File $MaintainLogFile -Append -Encoding UTF8
        $result | Out-String | Out-File $MaintainLogFile -Append -Encoding UTF8
        Log("DAG maintenance completed")
        return $result
    } catch {
        Log("DAG maintenance error: $_")
        return "Error: $_"
    }
}

function Get-LastMaintenanceTime {
    if (Test-Path "$env:USERPROFILE\.iflow\.last_maintenance") {
        try {
            return Get-Content "$env:USERPROFILE\.iflow\.last_maintenance" -Raw
        } catch {
            return $null
        }
    }
    return $null
}

function Set-LastMaintenanceTime {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss" | Out-File "$env:USERPROFILE\.iflow\.last_maintenance" -Encoding utf8
}

function Get-LastHistoryScanTime {
    if (Test-Path "$env:USERPROFILE\.iflow\.last_history_scan") {
        try {
            return Get-Content "$env:USERPROFILE\.iflow\.last_history_scan" -Raw
        } catch {
            return $null
        }
    }
    return $null
}

function Set-LastHistoryScanTime {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss" | Out-File "$env:USERPROFILE\.iflow\.last_history_scan" -Encoding utf8
}

function Invoke-SelfHealthCheck {
    Log("Running self health check...")
    $issues = @()
    $fixed = @()
    
    # 1. 检查 AGENTS.md 是否被污染（停滞提醒）
    $agentsContent = Get-Content $AgentsFile -Raw -ErrorAction SilentlyContinue
    if ($agentsContent -match "\[系统提醒\].*心跳停滞") {
        $issues += "AGENTS.md contains stall alerts (pollution)"
        # 自动清理
        $cleanContent = $agentsContent -split "`n" | Where-Object { $_ -notmatch "\[系统提醒\].*心跳停滞" } | Out-String
        $cleanContent | Out-File $AgentsFile -Encoding utf8
        $fixed += "Cleaned stall alerts from AGENTS.md"
    }
    
    # 2. 检查 AGENTS.md 行数
    $agentsLines = (Get-Content $AgentsFile | Measure-Object -Line).Lines
    if ($agentsLines -lt 10) {
        $issues += "AGENTS.md has only $agentsLines lines (possible over-cleaning)"
        # 记录到 DAG，需要人工介入
        python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="【自我检查】AGENTS.md 行数异常($agentsLines行)，可能需要恢复核心知识" --topic="系统健康" 2>&1 | Out-Null
    }
    
    # 3. 检查 DAG 重复率
    $auditResult = python "$env:USERPROFILE\.iflow\tools\dag_tools.py" audit 2>&1 | ConvertFrom-Json
    if ($auditResult.duplication_rate -gt 10) {
        $issues += "DAG duplication rate is $($auditResult.duplication_rate)%"
        # 自动去重
        python "$env:USERPROFILE\.iflow\tools\dag_tools.py" dedup --auto 2>&1 | Out-Null
        $fixed += "Auto-deduped DAG"
    }
    
    # 4. 检查心跳是否长时间未更新（超过1小时）
    if (Test-Path $HeartbeatFile) {
        $heartbeat = Get-Content $HeartbeatFile | ConvertFrom-Json
        $lastActive = [DateTime]::Parse($heartbeat.lastActive)
        $hoursSinceActive = ((Get-Date) - $lastActive).TotalHours
        if ($hoursSinceActive -gt 1) {
            $issues += "Heartbeat not updated for $([int]$hoursSinceActive) hours"
            # 记录到 DAG
            python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="【自我检查】心跳未更新超过$([int]$hoursSinceActive)小时，上次摘要: $($heartbeat.lastSummary)" --topic="系统健康" 2>&1 | Out-Null
        }
    }
    
    # 5. 自动提交到 GitHub（如果有改动）
    $gitStatus = git -C "C:\Users\55237\iflow-memory-system" status --porcelain 2>&1
    if ($gitStatus -and $gitStatus.Count -gt 0) {
        $issues += "Git has uncommitted changes"
        # 自动提交
        $commitMsg = "Guardian auto-sync: health check + improvements"
        git -C "C:\Users\55237\iflow-memory-system" add -A 2>&1 | Out-Null
        git -C "C:\Users\55237\iflow-memory-system" commit -m $commitMsg 2>&1 | Out-Null
        git -C "C:\Users\55237\iflow-memory-system" push origin main 2>&1 | Out-Null
        $fixed += "Auto-committed to GitHub"
        Log("Auto-committed to GitHub: $commitMsg")
    }
    
    # 汇报结果
    if ($issues.Count -eq 0) {
        Log("Health check: All systems healthy")
    } else {
        Log("Health check: Found $($issues.Count) issues, fixed $($fixed.Count)")
        foreach ($i in $issues) { Log("  Issue: $i") }
        foreach ($f in $fixed) { Log("  Fixed: $f") }
        
        # 记录健康检查结果到 DAG
        $summary = "【自我健康检查】发现问题: $($issues.Count), 已修复: $($fixed.Count)"
        python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="$summary" --topic="系统健康" 2>&1 | Out-Null
    }
    
    return @{ issues = $issues; fixed = $fixed }
}

function Scan-SessionHistory {
    Log("Scanning session history for knowledge extraction...")
    $scanScript = "$env:USERPROFILE\.iflow\tools\scan_session_history.py"
    $result = python $scanScript 24 2>&1
    $synced = 0
    foreach ($line in $result -split "`n") {
        if ($line -match "^([a-f0-9]+)\|(.+)$") {
            $sessionId = $Matches[1]
            $keywords = $Matches[2]
            $summary = "会话 $sessionId 关键词: $keywords"
            $dagResult = python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="【历史同步】$summary" --topic="会话历史" 2>&1
            if ($dagResult -like "*success*") {
                $synced++
            }
        }
    }
    Log("History scan synced $synced sessions to DAG")
    return $synced
}

function Consume-Stall-Alert {
    # 检查并消费停滞提醒
    if (Test-Path $StallAlertFile) {
        try {
            $alert = Get-Content $StallAlertFile -Raw | ConvertFrom-Json
            
            # 检查心跳是否已恢复（最近60秒内有更新）
            $heartbeat = Get-Heartbeat
            if ($heartbeat) {
                $lastActive = [DateTime]::Parse($heartbeat.lastActive)
                $idleSeconds = ((Get-Date) - $lastActive).TotalSeconds
                
                if ($idleSeconds -lt 60) {
                    # 心跳已恢复，清理提醒文件
                    Remove-Item $StallAlertFile -Force
                    Log("Stall alert consumed - heartbeat recovered (idle: ${idleSeconds}s)")
                    return "Consumed"
                }
            }
            return "Still stalled"
        } catch {
            Log("Error consuming stall alert: $_")
            return "Error"
        }
    }
    return "No alert"
}

# 单例检测：防止多个 Guardian 同时运行
$lockFile = "$env:USERPROFILE\.iflow\.guardian.lock"
if (Test-Path $lockFile) {
    $lockContent = Get-Content $lockFile -Raw -ErrorAction SilentlyContinue
    try {
        $lockData = $lockContent | ConvertFrom-Json
        $lockTime = [DateTime]::Parse($lockData.timestamp)
        if (((Get-Date) - $lockTime).TotalMinutes -lt 5) {
            # 5分钟内有其他 Guardian 在运行，退出
            Write-Host "Another Guardian instance is running (PID: $($lockData.pid)), exiting..."
            exit 0
        }
    } catch {}
}

# 写入锁文件
@{
    pid = $PID
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
} | ConvertTo-Json | Out-File $lockFile -Encoding utf8

Log("Guardian v3.4 started (singleton lock, session history sync, auto-archiving, content-based dedup, DAG maintenance)")

$lastRecordedSummary = $null  # 改用摘要内容检查
$lastStallAlertTime = $null
$lastMaintenanceTime = Get-LastMaintenanceTime
$lastHistoryScanTime = Get-LastHistoryScanTime
$lastHealthCheckTime = $null

while ($true) {
    # === 0. 自我健康检查 ===
    $shouldHealthCheck = $false
    if ($null -eq $lastHealthCheckTime) {
        $shouldHealthCheck = $true
    } else {
        try {
            $lastCheck = [DateTime]::Parse($lastHealthCheckTime)
            $minutesSinceCheck = ((Get-Date) - $lastCheck).TotalMinutes
            if ($minutesSinceCheck -ge $HealthCheckIntervalMinutes) {
                $shouldHealthCheck = $true
            }
        } catch {
            $shouldHealthCheck = $true
        }
    }
    
    if ($shouldHealthCheck) {
        Log("Triggering self health check (interval: ${HealthCheckIntervalMinutes}min)")
        $healthResult = Invoke-SelfHealthCheck
        $lastHealthCheckTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
    
    # === 1. 消费停滞提醒 ===
    $consumeResult = Consume-Stall-Alert
    
    # === 1. 会话历史扫描 ===
    $shouldScanHistory = $false
    if ($null -eq $lastHistoryScanTime) {
        $shouldScanHistory = $true
    } else {
        try {
            $lastScan = [DateTime]::Parse($lastHistoryScanTime)
            $hoursSinceScan = ((Get-Date) - $lastScan).TotalHours
            if ($hoursSinceScan -ge $HistoryScanIntervalHours) {
                $shouldScanHistory = $true
            }
        } catch {
            $shouldScanHistory = $true
        }
    }
    
    if ($shouldScanHistory) {
        Log("Triggering session history scan (interval: ${HistoryScanIntervalHours}h)")
        $scanResult = Scan-SessionHistory
        Set-LastHistoryScanTime
        $lastHistoryScanTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
    
    # === 1. 任务恢复检测 ===
    $task = Get-PendingTask
    if ($task -and $task.status -ne "recovering") {
        Log("Found pending task: $($task.description)")
        Mark-Recovering $task
        
        $prompt = "[恢复模式] 读取任务文件 $TaskFile 并继续处理"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "iflow -p '$prompt'"
        Log("Started recovery session")
    }
    
    # === 2. DAG 定期维护 ===
    $shouldMaintain = $false
    if ($null -eq $lastMaintenanceTime) {
        $shouldMaintain = $true
    } else {
        try {
            $lastMaint = [DateTime]::Parse($lastMaintenanceTime)
            $hoursSinceMaint = ((Get-Date) - $lastMaint).TotalHours
            if ($hoursSinceMaint -ge $DagMaintainIntervalHours) {
                $shouldMaintain = $true
            }
        } catch {
            $shouldMaintain = $true
        }
    }
    
    if ($shouldMaintain) {
        Log("Triggering scheduled DAG maintenance (interval: ${DagMaintainIntervalHours}h)")
        $maintResult = Run-DAG-Maintenance
        Set-LastMaintenanceTime
        $lastMaintenanceTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
    
    # === 3. 心跳检测 & 自动记录 ===
    $heartbeat = Get-Heartbeat
    if ($heartbeat) {
        try {
            $lastActive = [DateTime]::Parse($heartbeat.lastActive)
            $idleSeconds = ((Get-Date) - $lastActive).TotalSeconds
            $currentSummary = $heartbeat.lastSummary
            
            # === 4. 心跳停滞检测 ===
            if ($idleSeconds -gt $HeartbeatStallThreshold) {
                # 避免重复提醒，每5分钟最多提醒一次
                if ($null -eq $lastStallAlertTime -or ((Get-Date) - $lastStallAlertTime).TotalMinutes -gt 5) {
                    Log("WARNING: Heartbeat stalled for ${idleSeconds}s (threshold: ${HeartbeatStallThreshold}s)")
                    $alertResult = Create-Stall-Alert $idleSeconds $currentSummary
                    Log("Stall alert: $alertResult")
                    $lastStallAlertTime = Get-Date
                    
                    # 同时记录到 AGENTS.md 作为持久提醒（使用停滞提醒去重逻辑）
                    $stallEntry = "[系统提醒] 心跳停滞 ${idleSeconds}秒，最后摘要: $currentSummary"
                    $agentsResult = Append-To-Agents $stallEntry $true
                    Log("Stall notice added to AGENTS.md: $agentsResult")
                }
            }
            
            # === 5. 自动记录（基于摘要内容去重）===
            if ($idleSeconds -gt $IdleThreshold) {
                # 检查摘要内容是否已记录，而非时间戳
                if ($lastRecordedSummary -ne $currentSummary) {
                    Log("Detected idle session (${idleSeconds}s) with new summary, recording...")
                    
                    # 1. 记录到 DAG
                    $dagResult = Record-To-DAG "【自动记录】会话空闲 ${idleSeconds}秒，记录：$currentSummary"
                    Log("DAG: $dagResult")
                    
                    # 2. 同步到 MEMORY.md
                    $memResult = Append-To-Memory "【自动记录】$currentSummary"
                    Log("MEMORY.md: $memResult")
                    
                    # 3. 注入到 AGENTS.md
                    $agentsResult = Append-To-Agents $currentSummary
                    Log("AGENTS.md: $agentsResult")
                    
                    # 4. 检查并归档
                    $archiveResult = Archive-Old-Memories
                    Log("Archive: $archiveResult")
                    
                    # 更新已记录的摘要
                    $lastRecordedSummary = $currentSummary
                } else {
                    # 相同摘要，不重复记录
                    Log("Skipping duplicate summary: $currentSummary")
                }
            }
        } catch {
            Log("Error parsing heartbeat: $_")
        }
    }
    
    Start-Sleep -Seconds $PollInterval
}




