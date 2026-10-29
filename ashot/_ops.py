# -*- coding: utf-8 -*-
"""ops 内部标记类型（v0.6.4）。

`ResolvedOp` 表示"已由 dom.apply_selectors 乘过页面 dpr 的 op"。
用 **dict 子类**而不是 `op["__resolved__"] = True`：JSON 反序列化只能
产出普通 dict，客户端无法伪造这个类型来跳过 dpr 缩放。
"""


class ResolvedOp(dict):
    """已解析 selector/ref、坐标已是物理像素的 op。"""
