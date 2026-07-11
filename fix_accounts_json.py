"""修复 accounts.json 中的内嵌引号"""
import json
import re
import sys
from pathlib import Path

input_file = Path(__file__).parent / "accounts.json"
output_file = Path(__file__).parent / "accounts_fixed.json"

if not input_file.exists():
    print(f"❌ 未找到 {input_file}")
    sys.exit(1)

raw = input_file.read_text(encoding="utf-8-sig")

# 尝试直接解析
try:
    data = json.loads(raw)
    print("✅ JSON 格式正确，无需修复")
    sys.exit(0)
except json.JSONDecodeError:
    print("❌ JSON 解析失败，正在修复内嵌引号...")

# 修复方案：按行处理，提取每个 { } 块
# 找到所有 account 对象
fixed = []
# 用 state 机逐字符解析，找到最外层的 { }
i = 0
while i < len(raw):
    if raw[i] == '{':
        depth = 1
        j = i + 1
        while j < len(raw) and depth > 0:
            if raw[j] == '{':
                depth += 1
            elif raw[j] == '}':
                depth -= 1
            j += 1
        block = raw[i:j]
        i = j

        # 提取 username
        m = re.search(r'"username"\s*:\s*"([^"]+)"', block)
        if not m:
            continue
        username = m.group(1)

        # 提取 cookie（可能有内嵌引号，用正则尽量匹配）
        mc = re.search(r'"cookie"\s*:\s*"(.+)"', block, re.DOTALL)
        if not mc:
            continue
        cookie_raw = mc.group(1)

        # 去除尾部可能的 }, 干扰
        # 反其道而行：把内嵌的 " 替换成 \"
        # 简单策略：把 cookie 中所有 " 转义，但 JSON 边界 " 不受影响
        # 已经知道格式是 "cookie": "xxx"，所以 xxx 部分的 " 都需要转义
        # 直接对 cookie_raw 做转义
        cookie_escaped = cookie_raw.replace('\\', '\\\\').replace('"', '\\"')

        fixed.append({"username": username, "cookie": cookie_escaped})
    else:
        i += 1

if fixed:
    output_file.write_text(
        json.dumps(fixed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    print(f"✅ 修复完成！共 {len(fixed)} 个账号 → {output_file.name}")
    print(f"运行: uv run python manage_accounts.py import {output_file.name}")
else:
    print("❌ 无法解析账号，请手动检查 JSON")
