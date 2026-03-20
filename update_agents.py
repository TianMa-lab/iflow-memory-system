#!/usr/bin/env python3
"""更新 AGENTS.md"""
from pathlib import Path
from datetime import datetime

agents_path = Path.home() / '.iflow' / 'AGENTS.md'
content = agents_path.read_text(encoding='utf-8')

# 添加新记录
new_entry = f'- [{datetime.now().strftime("%Y-%m-%d")}] lossless-claw核心功能实现: CompactionEngine + CondensationEngine + ContextAssembler + Guardian v4.0自动集成\n'

# 找到合适的位置插入
last_entry_idx = content.rfind('- [2026-03-20]')
if last_entry_idx != -1:
    line_end = content.find('\n', last_entry_idx)
    content = content[:line_end+1] + new_entry + content[line_end+1:]
else:
    content = content.rstrip() + '\n' + new_entry

agents_path.write_text(content, encoding='utf-8')
print('AGENTS.md updated')
