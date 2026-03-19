#!/usr/bin/env python3
"""DAG Memory Tools - Fast Version"""

import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

DEFAULT_DAG_PATH = Path.home() / ".iflow" / "memory-dag"
DEFAULT_DB_PATH = DEFAULT_DAG_PATH / "memory.db"
DEFAULT_INDEX_PATH = DEFAULT_DAG_PATH / "dag-index.json"


class DAGIndex:
    def __init__(self, index_path: Path = DEFAULT_INDEX_PATH):
        self.index_path = index_path
        self.data = self._load()
    
    def _load(self) -> dict:
        if self.index_path.exists():
            with open(self.index_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        return {"nodes": {}, "edges": []}
    
    def save(self):
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


def dag_grep(pattern: str, use_regex: bool = False) -> List[Dict]:
    """Search messages"""
    results = []
    index = DAGIndex()
    flags = 0 if use_regex else re.IGNORECASE
    
    try:
        regex = re.compile(pattern if use_regex else re.escape(pattern), flags)
    except re.error as e:
        return [{"error": str(e)}]
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    leaf_data = json.load(f)
                    matches = []
                    for msg in leaf_data.get("messages", []):
                        content = msg.get("content", "")
                        if regex.search(content):
                            matches.append({"role": msg.get("role"), "content": content[:100]})
                    if matches:
                        results.append({"node_id": node_id, "matches": matches[:5]})
    return results


def dag_overview() -> Dict:
    """System overview"""
    index = DAGIndex()
    nodes = index.data.get("nodes", {})
    return {
        "total_nodes": len(nodes),
        "meta": index.data.get("meta", {}),
        "recent": list(nodes.keys())[-5:]
    }


def dag_describe(node_id: str) -> Dict:
    """Describe node"""
    index = DAGIndex()
    node_meta = index.data.get("nodes", {}).get(node_id)
    if not node_meta:
        return {"error": f"Node {node_id} not found"}
    
    result = {"node_id": node_id, "type": node_meta.get("type"), "topic": node_meta.get("topic")}
    
    if node_meta.get("type") == "leaf":
        leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
        if leaf_path.exists():
            with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                leaf_data = json.load(f)
                result["messages"] = leaf_data.get("messages", [])
                result["count"] = len(result["messages"])
    return result


def dag_add(content: str, topic: str = "", role: str = "user") -> Dict:
    """Add message"""
    index = DAGIndex()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Find or create leaf
    leaf_id = None
    for nid, nmeta in index.data.get("nodes", {}).items():
        if nmeta.get("type") == "leaf" and date_str in nid and nmeta.get("status") != "summarized":
            leaf_id = nid
            break
    
    if not leaf_id:
        existing = [n for n in index.data.get("nodes", {}) if n.startswith(f"leaf-{date_str}")]
        leaf_id = f"leaf-{date_str}-{len(existing)+1:03d}"
        index.data.setdefault("nodes", {})[leaf_id] = {"type": "leaf", "topic": topic or date_str, "status": "active"}
    
    leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{leaf_id}.json"
    leaf_data = {"id": leaf_id, "messages": []}
    if leaf_path.exists():
        with open(leaf_path, 'r', encoding='utf-8-sig') as f:
            leaf_data = json.load(f)
    
    # 去重检查：检查是否已存在相同内容的消息
    existing_contents = [msg.get("content", "") for msg in leaf_data.get("messages", [])]
    # 使用前80字符作为去重key
    content_key = content[:80] if len(content) > 80 else content
    for existing in existing_contents:
        existing_key = existing[:80] if len(existing) > 80 else existing
        if content_key == existing_key:
            return {"success": True, "leaf_id": leaf_id, "count": len(leaf_data["messages"]), "duplicate": True}
    
    leaf_data.setdefault("messages", []).append({"role": role, "content": content})
    
    with open(leaf_path, 'w', encoding='utf-8') as f:
        json.dump(leaf_data, f, ensure_ascii=False, indent=2)
    
    index.save()
    return {"success": True, "leaf_id": leaf_id, "count": len(leaf_data["messages"])}


def dag_tasks() -> List[Dict]:
    """List tasks"""
    results = []
    index = DAGIndex()
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    for msg in json.load(f).get("messages", []):
                        content = msg.get("content", "")
                        if "任务" in content:
                            match = re.search(r"任务名[：:]\s*([^\|]+)", content)
                            if match:
                                results.append({
                                    "task": match.group(1).strip(),
                                    "status": "完成" if "完成" in content else "进行中"
                                })
    return results


# ============ DAG 维护命令 ============

def dag_audit() -> Dict:
    """审计 DAG 内容，统计重复率、噪音率等"""
    index = DAGIndex()
    stats = {
        "total_nodes": 0,
        "total_messages": 0,
        "duplicates": 0,
        "test_noise": 0,
        "auto_records": 0,
        "valuable_content": 0,
        "duplicate_groups": [],
        "noise_items": []
    }
    
    content_counts = {}  # 用于检测重复
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            stats["total_nodes"] += 1
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    leaf_data = json.load(f)
                    for msg in leaf_data.get("messages", []):
                        stats["total_messages"] += 1
                        content = msg.get("content", "")
                        
                        # 检测测试噪音
                        if any(x in content for x in ["TEST_", "SECRET_CODE", "测试记录", "--content=TEST"]):
                            stats["test_noise"] += 1
                            stats["noise_items"].append({"node": node_id, "content": content[:50]})
                        
                        # 检测自动记录
                        elif "【自动记录】" in content:
                            stats["auto_records"] += 1
                            # 提取摘要部分用于去重
                            match = re.search(r"记录[：:]\s*(.+)", content)
                            if match:
                                summary = match.group(1).strip()
                                if summary not in content_counts:
                                    content_counts[summary] = []
                                content_counts[summary].append({"node": node_id, "full": content})
                        
                        else:
                            stats["valuable_content"] += 1
    
    # 统计重复
    for summary, items in content_counts.items():
        if len(items) > 1:
            stats["duplicates"] += len(items) - 1
            if len(stats["duplicate_groups"]) < 10:  # 只保留前10组
                stats["duplicate_groups"].append({
                    "summary": summary[:60],
                    "count": len(items),
                    "nodes": [i["node"] for i in items]
                })
    
    stats["duplicate_rate"] = round(stats["duplicates"] / max(stats["total_messages"], 1) * 100, 1)
    stats["noise_rate"] = round(stats["test_noise"] / max(stats["total_messages"], 1) * 100, 1)
    
    return stats


def dag_dedup(dry_run: bool = True) -> Dict:
    """去重：合并重复的自动记录"""
    index = DAGIndex()
    result = {"removed": 0, "kept": 0, "details": []}
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    leaf_data = json.load(f)
                
                seen_summaries = set()
                new_messages = []
                
                for msg in leaf_data.get("messages", []):
                    content = msg.get("content", "")
                    
                    # 自动记录去重
                    if "【自动记录】" in content:
                        match = re.search(r"记录[：:]\s*(.+)", content)
                        if match:
                            summary = match.group(1).strip()
                            if summary not in seen_summaries:
                                seen_summaries.add(summary)
                                new_messages.append(msg)
                                result["kept"] += 1
                            else:
                                result["removed"] += 1
                        else:
                            new_messages.append(msg)
                    else:
                        new_messages.append(msg)
                
                # 写入清理后的数据
                if not dry_run and len(new_messages) < len(leaf_data.get("messages", [])):
                    leaf_data["messages"] = new_messages
                    with open(leaf_path, 'w', encoding='utf-8') as f:
                        json.dump(leaf_data, f, ensure_ascii=False, indent=2)
    
    return result


def dag_prune(dry_run: bool = True) -> Dict:
    """清理测试/噪音数据"""
    index = DAGIndex()
    result = {"removed": 0, "patterns": {}}
    
    noise_patterns = ["TEST_", "SECRET_CODE", "测试记录", "--content=TEST", "--content=【秘密测试】"]
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    leaf_data = json.load(f)
                
                new_messages = []
                for msg in leaf_data.get("messages", []):
                    content = msg.get("content", "")
                    is_noise = any(p in content for p in noise_patterns)
                    
                    if is_noise:
                        result["removed"] += 1
                        for p in noise_patterns:
                            if p in content:
                                result["patterns"][p] = result["patterns"].get(p, 0) + 1
                    else:
                        new_messages.append(msg)
                
                if not dry_run and len(new_messages) < len(leaf_data.get("messages", [])):
                    leaf_data["messages"] = new_messages
                    with open(leaf_path, 'w', encoding='utf-8') as f:
                        json.dump(leaf_data, f, ensure_ascii=False, indent=2)
    
    return result


def dag_refine(dry_run: bool = True) -> Dict:
    """提炼知识点：从原始对话中提取精华"""
    index = DAGIndex()
    result = {"refined": 0, "knowledge_points": []}
    
    for node_id, node_meta in index.data.get("nodes", {}).items():
        if node_meta.get("type") == "leaf":
            leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
            if leaf_path.exists():
                with open(leaf_path, 'r', encoding='utf-8-sig') as f:
                    leaf_data = json.load(f)
                
                for msg in leaf_data.get("messages", []):
                    content = msg.get("content", "")
                    
                    # 提取系统改进类知识点
                    if "【系统改进】" in content or "【优化迭代" in content:
                        match = re.search(r"(【[^】]+】[^\|]+)", content)
                        if match:
                            result["knowledge_points"].append({
                                "type": "系统改进",
                                "summary": match.group(1).strip(),
                                "node": node_id
                            })
                            result["refined"] += 1
                    
                    # 提取经验总结类
                    elif "经验" in content or "总结" in content:
                        if len(content) > 50 and "自动记录" not in content:
                            result["knowledge_points"].append({
                                "type": "经验总结",
                                "summary": content[:100],
                                "node": node_id
                            })
                            result["refined"] += 1
    
    return result


def dag_archive(days_old: int = 30, dry_run: bool = True) -> Dict:
    """归档旧的 leaf 节点"""
    from datetime import datetime, timedelta
    
    index = DAGIndex()
    result = {"archived": 0, "nodes": []}
    
    cutoff = datetime.now() - timedelta(days=days_old)
    archive_path = DEFAULT_DAG_PATH / "archive"
    
    for node_id, node_meta in list(index.data.get("nodes", {}).items()):
        if node_meta.get("type") == "leaf":
            # 从 node_id 提取日期
            match = re.search(r"leaf-(\d{4}-\d{2}-\d{2})", node_id)
            if match:
                node_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                if node_date < cutoff:
                    result["archived"] += 1
                    result["nodes"].append(node_id)
                    
                    if not dry_run:
                        # 移动文件到归档目录
                        archive_path.mkdir(exist_ok=True)
                        leaf_path = DEFAULT_DAG_PATH / "leaves" / f"{node_id}.json"
                        if leaf_path.exists():
                            import shutil
                            shutil.move(str(leaf_path), str(archive_path / f"{node_id}.json"))
                        
                        # 更新索引
                        index.data["nodes"][node_id]["status"] = "archived"
    
    if not dry_run:
        index.save()
    
    return result


def dag_maintain(auto: bool = False) -> Dict:
    """执行完整维护流程"""
    results = {}
    
    # 1. 审计
    results["audit"] = dag_audit()
    
    # 2. 去重
    results["dedup"] = dag_dedup(dry_run=not auto)
    
    # 3. 清理噪音
    results["prune"] = dag_prune(dry_run=not auto)
    
    # 4. 归档（超过30天）
    results["archive"] = dag_archive(days_old=30, dry_run=not auto)
    
    # 5. 提炼知识点
    results["refine"] = dag_refine(dry_run=not auto)
    
    return results


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if cmd == "grep" and len(sys.argv) > 2:
        print(json.dumps(dag_grep(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "overview":
        print(json.dumps(dag_overview(), ensure_ascii=False, indent=2))
    elif cmd == "describe" and len(sys.argv) > 2:
        print(json.dumps(dag_describe(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "tasks":
        tasks = dag_tasks()
        if tasks:
            for i, t in enumerate(tasks, 1):
                icon = "✅" if t["status"] == "完成" else "🔄"
                print(f"{i}. {icon} {t['task']}")
        else:
            print("No tasks found")
    elif cmd == "add" and len(sys.argv) > 2:
        content = sys.argv[2]
        # 处理 --content= 前缀
        if content.startswith("--content="):
            content = content[10:]  # 去除 --content= 前缀
        topic = sys.argv[3] if len(sys.argv) > 3 else ""
        # 处理 --topic= 前缀
        if topic.startswith("--topic="):
            topic = topic[8:]
        print(json.dumps(dag_add(content, topic), ensure_ascii=False))
    
    # ============ 维护命令 ============
    elif cmd == "audit":
        result = dag_audit()
        print(f"DAG 审计报告")
        print(f"=" * 40)
        print(f"总节点数: {result['total_nodes']}")
        print(f"总消息数: {result['total_messages']}")
        print(f"重复消息: {result['duplicates']} ({result['duplicate_rate']}%)")
        print(f"测试噪音: {result['test_noise']} ({result['noise_rate']}%)")
        print(f"自动记录: {result['auto_records']}")
        print(f"有价值内容: {result['valuable_content']}")
        if result['duplicate_groups']:
            print(f"\n重复组示例:")
            for g in result['duplicate_groups'][:5]:
                print(f"  - {g['summary']} (x{g['count']})")
    
    elif cmd == "dedup":
        auto = "--auto" in sys.argv
        result = dag_dedup(dry_run=not auto)
        mode = "执行" if auto else "预览"
        print(f"去重 {mode}: 移除 {result['removed']} 条重复，保留 {result['kept']} 条")
        if not auto:
            print("使用 --auto 参数执行实际清理")
    
    elif cmd == "prune":
        auto = "--auto" in sys.argv
        result = dag_prune(dry_run=not auto)
        mode = "执行" if auto else "预览"
        print(f"噪音清理 {mode}: 移除 {result['removed']} 条")
        for p, c in result['patterns'].items():
            print(f"  - {p}: {c} 条")
        if not auto:
            print("使用 --auto 参数执行实际清理")
    
    elif cmd == "refine":
        result = dag_refine(dry_run=True)
        print(f"知识提炼: 发现 {result['refined']} 条知识点")
        for kp in result['knowledge_points'][:10]:
            print(f"  [{kp['type']}] {kp['summary'][:80]}")
    
    elif cmd == "archive":
        auto = "--auto" in sys.argv
        days = 30
        for i, arg in enumerate(sys.argv):
            if arg.startswith("--days="):
                days = int(arg.split("=")[1])
        result = dag_archive(days_old=days, dry_run=not auto)
        mode = "执行" if auto else "预览"
        print(f"归档 {mode}: {result['archived']} 个节点（超过 {days} 天）")
        if result['nodes']:
            print(f"节点: {', '.join(result['nodes'][:5])}")
        if not auto:
            print("使用 --auto 参数执行实际归档")
    
    elif cmd == "maintain":
        auto = "--auto" in sys.argv
        result = dag_maintain(auto=auto)
        mode = "执行" if auto else "预览"
        print(f"DAG 完整维护 {mode}")
        print("=" * 40)
        print(f"审计: {result['audit']['total_messages']} 条消息, {result['audit']['duplicate_rate']}% 重复")
        print(f"去重: 移除 {result['dedup']['removed']} 条重复")
        print(f"清理: 移除 {result['prune']['removed']} 条噪音")
        print(f"归档: {result['archive']['archived']} 个旧节点")
        print(f"提炼: {result['refine']['refined']} 条知识点")
        if not auto:
            print("\n使用 --auto 参数执行实际维护")
    
    else:
        print("DAG Memory Tools v2.0")
        print("")
        print("基础命令:")
        print("  grep <pattern>    - 搜索消息")
        print("  overview          - 系统概览")
        print("  describe <node>   - 查看节点详情")
        print("  tasks             - 列出任务")
        print("  add <content> [topic] - 添加消息")
        print("")
        print("维护命令:")
        print("  audit             - 审计 DAG 内容")
        print("  dedup [--auto]    - 去重（--auto 执行实际清理）")
        print("  prune [--auto]    - 清理噪音")
        print("  refine            - 提炼知识点")
        print("  archive [--auto] [--days=N] - 归档旧节点")
        print("  maintain [--auto] - 完整维护流程")
