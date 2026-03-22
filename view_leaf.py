#!/usr/bin/env python3
"""View leaf node content"""
import json
import sys
from pathlib import Path

leaf_dir = Path.home() / ".iflow" / "memory-dag" / "leaves"

if len(sys.argv) > 1:
    leaf_id = sys.argv[1]
    leaf_path = leaf_dir / f"{leaf_id}.json"
else:
    # List all leaves
    for f in sorted(leaf_dir.glob("leaf-*.json")):
        try:
            data = json.loads(f.read_text(encoding='utf-8-sig'))
            print(f"{f.stem}: {len(data.get('messages', []))} messages")
        except Exception as e:
            print(f"{f.stem}: Error - {e}")
    sys.exit(0)

if not leaf_path.exists():
    print(f"Leaf not found: {leaf_id}")
    sys.exit(1)

data = json.loads(leaf_path.read_text(encoding='utf-8-sig'))
print(f"=== {leaf_id} ===")
print(f"Messages: {len(data.get('messages', []))}")
print()

for i, msg in enumerate(data.get('messages', []), 1):
    content = msg.get('content', '')
    role = msg.get('role', 'unknown')
    if len(content) > 120:
        content = content[:120] + "..."
    print(f"{i}. [{role}] {content}")
