# iFlow CLI DAG 记忆系统

基于 [lossless-claw](https://github.com/martian-missing-links/lossless-claw) 设计的无损上下文管理系统，为 iFlow CLI 实现跨会话长记忆能力。

## 功能特性

- **DAG 记忆架构**: 层次化存储，支持无限上下文
- **自动记录**: Guardian 守护进程检测空闲并自动记录
- **三重存储**: DAG + MEMORY.md + AGENTS.md 同步保障
- **自动归档**: AGENTS.md 超过 100 行自动归档
- **子智能体**: memory-analyst 记忆分析专家

## 架构

```
用户对话 → 心跳更新 → Guardian 检测空闲
                              ↓
                    DAG + MEMORY.md + AGENTS.md
                              ↓
                    超过100行 → 自动归档
                              ↓
下次会话 → iFlow CLI 自动加载 AGENTS.md → 拥有历史记忆
```

## 文件结构

```
.iflow/
├── AGENTS.md              # 系统自动加载的记忆
├── AGENTS_archive.md      # 归档的历史记忆
├── MEMORY.md              # 详细对话日志
├── IDENTITY.md            # 身份与行为准则
├── memory-dag/
│   ├── memory.db          # SQLite 数据库
│   ├── dag-index.json     # DAG 索引
│   ├── leaves/            # 叶子节点
│   └── summaries/         # 摘要节点
├── tools/
│   ├── dag_tools.py       # DAG 工具集
│   ├── iflow_guardian.ps1 # Guardian 守护进程
│   ├── update_heartbeat.ps1
│   └── test_memory_system.ps1
└── agents/
    └── memory-analyst.md  # 记忆分析师配置
```

## 快速命令

```powershell
# DAG 概览
python ~/.iflow/tools/dag_tools.py overview

# 搜索记忆
python ~/.iflow/tools/dag_tools.py grep "关键词"

# 查看任务
python ~/.iflow/tools/dag_tools.py tasks

# 添加记录
python ~/.iflow/tools/dag_tools.py add --content="内容" --topic="主题"

# 系统测试
powershell -File ~/.iflow/tools/test_memory_system.ps1
```

## 依赖

- Python 3.9+
- PowerShell 5.1+
- iFlow CLI

## 致谢

- [lossless-claw](https://github.com/martian-missing-links/lossless-claw) by Martian Engineering
- OpenClaw 项目

## 作者

- 主人: 唐僧 (iFlow CLI)
- 搭档: 天马
- 日期: 2026-03-17