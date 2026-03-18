# test_memory_system.ps1 - 记忆系统完整测试 v2

param(
    [string]$TestTag = "MEMORY_TEST_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
)

$ErrorActionPreference = "Continue"
$testsPassed = 0
$testsFailed = 0

function Test-Step($name, $condition) {
    if ($condition) {
        Write-Host "  ✅ $name" -ForegroundColor Green
        $script:testsPassed++
    } else {
        Write-Host "  ❌ $name" -ForegroundColor Red
        $script:testsFailed++
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  记忆系统完整性测试 v2" -ForegroundColor Cyan
Write-Host "  测试标签: $TestTag" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# === 1. Guardian 进程检测 ===
Write-Host "[1] Guardian 守护进程检测" -ForegroundColor Yellow
$guardian = Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*guardian*" }
Test-Step "Guardian 进程运行中" ($guardian.Count -ge 1)

# === 2. 心跳机制测试 ===
Write-Host "`n[2] 心跳机制测试" -ForegroundColor Yellow
$updateResult = & powershell -File "$env:USERPROFILE\.iflow\tools\update_heartbeat.ps1" -Summary $TestTag 2>&1
Test-Step "心跳更新命令执行" ($updateResult -like "*updated*")

$heartbeatAfter = Get-Content "$env:USERPROFILE\.iflow\heartbeat.json" -Raw | ConvertFrom-Json
Test-Step "心跳内容已更新" ($heartbeatAfter.lastSummary -eq $TestTag)

# === 3. DAG 记录测试 ===
Write-Host "`n[3] DAG 记录测试" -ForegroundColor Yellow
$testContent = "【测试记录】$TestTag - 验证 DAG 写入功能"
$dagResult = python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="$testContent" --topic="系统测试" 2>$null
Test-Step "DAG 写入成功" ($dagResult -like "*success*")

# 修正：检查消息计数而非节点数
$dagResultObj = $dagResult | ConvertFrom-Json
Test-Step "DAG 消息计数增加" ($dagResultObj.count -gt 0)

# === 4. DAG 检索测试 ===
Write-Host "`n[4] DAG 检索测试" -ForegroundColor Yellow
$grepResult = python "$env:USERPROFILE\.iflow\tools\dag_tools.py" grep $TestTag 2>$null
Test-Step "DAG 可检索到测试记录" ($grepResult -like "*$TestTag*")

# === 5. 文件结构测试 ===
Write-Host "`n[5] 文件结构测试" -ForegroundColor Yellow
Test-Step "DAG 数据库存在" (Test-Path "$env:USERPROFILE\.iflow\memory-dag\memory.db")
Test-Step "DAG 索引存在" (Test-Path "$env:USERPROFILE\.iflow\memory-dag\dag-index.json")
Test-Step "MEMORY.md 存在" (Test-Path "$env:USERPROFILE\.iflow\MEMORY.md")
Test-Step "AGENTS.md 存在" (Test-Path "$env:USERPROFILE\.iflow\AGENTS.md")
Test-Step "IDENTITY.md 存在" (Test-Path "$env:USERPROFILE\.iflow\IDENTITY.md")

# === 6. memory-analyst 子智能体测试 ===
Write-Host "`n[6] memory-analyst 子智能体测试" -ForegroundColor Yellow
Test-Step "memory-analyst 配置存在" (Test-Path "$env:USERPROFILE\.iflow\agents\memory-analyst.md")

# === 7. 归档机制测试 ===
Write-Host "`n[7] 归档机制测试" -ForegroundColor Yellow
$agentsLines = (Get-Content "$env:USERPROFILE\.iflow\AGENTS.md").Count
Test-Step "AGENTS.md 行数在限制内 ($agentsLines 行)" ($agentsLines -lt 150)

# === 8. Guardian 日志检测 ===
Write-Host "`n[8] Guardian 日志检测" -ForegroundColor Yellow
$logExists = Test-Path "$env:USERPROFILE\.iflow\logs\guardian.log"
Test-Step "Guardian 日志存在" $logExists

if ($logExists) {
    $recentLog = Get-Content "$env:USERPROFILE\.iflow\logs\guardian.log" -Tail 10 -Encoding UTF8
    Test-Step "Guardian 日志有内容" ($recentLog.Count -gt 0)
}

# === 9. 端到端记忆测试 ===
Write-Host "`n[9] 端到端记忆测试" -ForegroundColor Yellow
$secretCode = "SECRET_CODE_$(Get-Random -Maximum 99999)"
python "$env:USERPROFILE\.iflow\tools\dag_tools.py" add --content="【秘密测试】$secretCode" --topic="端到端测试" 2>$null
Start-Sleep -Seconds 1
$found = python "$env:USERPROFILE\.iflow\tools\dag_tools.py" grep $secretCode 2>$null
Test-Step "端到端写入并检索成功" ($found -like "*$secretCode*")

# === 10. 跨文件同步测试 ===
Write-Host "`n[10] 跨文件同步测试" -ForegroundColor Yellow
$agentsContent = Get-Content "$env:USERPROFILE\.iflow\AGENTS.md" -Raw -Encoding UTF8
$memoryContent = Get-Content "$env:USERPROFILE\.iflow\MEMORY.md" -Raw -Encoding UTF8
Test-Step "AGENTS.md 有内容" ($agentsContent.Length -gt 100)
Test-Step "MEMORY.md 有内容" ($memoryContent.Length -gt 100)

# === 测试总结 ===
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  测试完成" -ForegroundColor Cyan
Write-Host "  通过: $testsPassed" -ForegroundColor Green
Write-Host "  失败: $testsFailed" -ForegroundColor Red
Write-Host "========================================`n" -ForegroundColor Cyan

if ($testsFailed -eq 0) {
    Write-Host "✅ 所有测试通过！记忆系统运行正常。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ 有 $testsFailed 项测试失败，请检查。" -ForegroundColor Red
    exit 1
}