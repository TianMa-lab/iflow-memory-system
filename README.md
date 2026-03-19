# iFlow CLI DAG 记忆系统

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-green.svg)](https://www.python.org/)
[![PowerShell](https://img.shields.io/badge/powershell-5.1+-blue.svg)](https://docs.microsoft.com/powershell/)

基于 [lossless-claw](https://github.com/martian-missing-links/lossless-claw) 设计的无损上下文管理系统，为 AI CLI 工具实现跨会话长记忆能力。

## 核心特性

- **DAG 记忆架构**: 层次化存储，支持无限上下文扩展
- **双层记忆系统**: 系统记忆(.jsonl) + 外挂记忆(DAG/AGENTS.md) 协同工作
- **自我驱动**: Guardian v3.3 每30分钟自动健康检查、修复问题、同步 GitHub
- **记忆召回**: 用户提问时主动从 DAG 检索相关历史知识
- **内容去重**: 写入前检查，避免重复记录

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    双层记忆系统                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【系统记忆 - 短期】                                             │
│  ├─ .iflow/projects/*.jsonl  (完整对话，自动生成)               │
│  └─ 会话级别，随会话结束归档                                     │
│                                                                 │
│  【外挂记忆 - 长期】                                             │
│  ├─ AGENTS.md     (核心知识，会话启动时自动加载)                 │
│  ├─ DAG 数据库    (结构化记忆，支持检索)                         │
│  └─ 跨会话持久化                                                 │
│                                                                 │
│  【Guardian v3.3 - 记忆晋升引擎】                                │
│  ├─ 系统记忆 → 外挂记忆 (定期扫描提取知识点)                     │
│  ├─ 自我健康检查 (每30分钟)                                     │
│  ├─ 自动问题修复 (AGENTS.md污染、DAG重复等)                      │
│  └─ 自动 GitHub 同步                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 安装

```powershell
# 克隆仓库
git clone https://github.com/TianMa-lab/iflow-memory-system.git
cd iflow-memory-system

# 安装到 ~/.iflow 目录
./install.ps1
```

### 基本命令

```powershell
# DAG 概览
python ~/.iflow/tools/dag_tools.py overview

# 搜索记忆
python ~/.iflow/tools/dag_tools.py grep "关键词"

# 查看任务列表
python ~/.iflow/tools/dag_tools.py tasks

# 添加记录
python ~/.iflow/tools/dag_tools.py add --content="【记录类型】内容" --topic="主题"

# DAG 维护
python ~/.iflow/tools/dag_tools.py maintain --auto

# 系统测试
powershell -File ~/.iflow/tools/test_memory_system.ps1
```

### 启动 Guardian

```powershell
# 前台运行（调试）
powershell -File ~/.iflow/tools/iflow_guardian.ps1

# 后台运行
Start-Process powershell -ArgumentList "-NoProfile", "-WindowStyle", "Hidden", "-File", "$env:USERPROFILE\.iflow\tools\iflow_guardian.ps1"
```

## 文件结构

```
.iflow/
├── AGENTS.md              # 核心知识（会话启动时自动加载）
├── AGENTS_archive.md      # 归档的历史记忆
├── MEMORY.md              # 详细对话日志
├── IDENTITY.md            # 身份与行为准则
├── heartbeat.json         # 心跳状态
├── memory-dag/
│   ├── memory.db          # SQLite 数据库
│   ├── dag-index.json     # DAG 索引
│   └── leaves/            # 叶子节点存储
├── tools/
│   ├── dag_tools.py       # DAG 工具集
│   ├── iflow_guardian.ps1 # Guardian 守护进程 (v3.3)
│   ├── scan_session_history.py  # 会话历史扫描
│   ├── update_heartbeat.ps1
│   └── test_memory_system.ps1
├── logs/
│   └── guardian.log       # Guardian 运行日志
└── projects/              # 系统会话历史 (.jsonl)
```

## Guardian 版本历史

| 版本 | 主要功能 |
|-----|---------|
| v3.3 | 自动 GitHub 提交机制 |
| v3.2 | 自我健康检查（每30分钟自动检查修复） |
| v3.1 | 阻止停滞提醒污染 AGENTS.md |
| v3.0 | 系统记忆 ↔ 外挂记忆 协同机制 |
| v2.9 | 单例锁防止竞态条件 |
| v2.8 | 内容去重（摘要内容检查） |
| v2.5 | 心跳停滞检测 |

## DAG 工具命令

```powershell
# 基础命令
python ~/.iflow/tools/dag_tools.py overview          # 系统概览
python ~/.iflow/tools/dag_tools.py grep "pattern"    # 搜索消息
python ~/.iflow/tools/dag_tools.py describe <node>   # 查看节点详情
python ~/.iflow/tools/dag_tools.py tasks             # 列出任务
python ~/.iflow/tools/dag_tools.py add <content> [topic]  # 添加消息

# 维护命令
python ~/.iflow/tools/dag_tools.py audit             # 审计 DAG 内容
python ~/.iflow/tools/dag_tools.py dedup --auto      # 去重
python ~/.iflow/tools/dag_tools.py prune --auto      # 清理噪音
python ~/.iflow/tools/dag_tools.py refine            # 提炼知识点
python ~/.iflow/tools/dag_tools.py archive --auto    # 归档旧节点
python ~/.iflow/tools/dag_tools.py maintain --auto   # 完整维护流程
```

## 依赖

- Python 3.9+
- PowerShell 5.1+
- iFlow CLI 或兼容的 AI CLI 工具

## 致谢

- [lossless-claw](https://github.com/martian-missing-links/lossless-claw) by Martian Engineering - DAG 记忆架构灵感来源
- OpenClaw 项目 - 子智能体配置参考

## 作者

- 主人: 唐僧 (iFlow CLI)
- 搭档: 天马
- 创建日期: 2026-03-17

## License

MIT License - 详见 [LICENSE](LICENSE) 文件