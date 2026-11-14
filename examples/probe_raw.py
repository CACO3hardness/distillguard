#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：尝试读取 ../raw，用来验证 --lock-raw 是否真的断开了原始目录。"""

from pathlib import Path

raw = Path("../raw").resolve()
print(f"probe_raw: {raw}")
print(f"probe_raw: 存在 = {raw.exists()}")
if raw.exists():
    files = [p.name for p in raw.iterdir() if p.is_file()]
    print(f"probe_raw: 可见 {len(files)} 个文件 {files}")
    raise SystemExit(10)
print("probe_raw: 原始目录不可达，锁生效")
