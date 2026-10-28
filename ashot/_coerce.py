# -*- coding: utf-8 -*-
"""宽松值解析（单源）：MCP 手写 JSON 与 CLI 字符串共用。

为什么单源：`in (True, "true", "True", "1")` 这种五连写曾在 mcp/cli 里
复制十余处，语义一旦分叉（有人认 "yes"、有人不认）就会出现"同一个参数
两个脸行为不同"的漂移（v0.2.5 审查 S1 的教训）。布尔解析统一走这里。
"""

_FALSE = ("", "0", "false", "no", "off", "none", "null")


def as_bool(v, default=False):
    """布尔保真：bool("false") 是 truthy——MCP/CLI 手写 JSON 的常见输入。
    字符串按词表判定（"false"/"0"/"no"/"off"/""/None 为假），
    未知字符串回退 default（不抛，保持宽松输入契约）。"""
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in _FALSE:
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return bool(default)


def as_int(v, default=0):
    """整数解析：空串/None/坏值回退 default（不抛）。"""
    if v is None or v == "":
        return int(default)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return int(default)
