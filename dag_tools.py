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
        topic = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(dag_add(content, topic), ensure_ascii=False))
    else:
        print("Usage: dag_tools.py <grep|overview|describe|tasks|add> [args]")
