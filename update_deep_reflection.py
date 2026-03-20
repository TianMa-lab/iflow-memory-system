#!/usr/bin/env python3
"""Update deep-reflection.md with auto-reflection trigger"""

from pathlib import Path

content = Path.home().joinpath('.iflow/skills/deep-reflection.md').read_text(encoding='utf-8')

# Add auto-reflection trigger info
old_trigger = """## 触发条件
- 用户问"你是不是需要深刻自省一下？"
- 会话开始时自动检查
- 发现异常指标时触发"""

new_trigger = """## 触发条件
- 用户问"你是不是需要深刻自省一下？"
- 会话开始时自动检查
- 发现异常指标时触发
- **Guardian v3.9 自动触发**: 健康检查发现问题时自动调用 auto_reflection.py"""

content = content.replace(old_trigger, new_trigger)
Path.home().joinpath('.iflow/skills/deep-reflection.md').write_text(content, encoding='utf-8')
print('deep-reflection.md updated')
