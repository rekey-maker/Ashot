# -*- coding: utf-8 -*-
"""Ashot.vector —— ops 几何编译器：JSON ops -> GDI+ 渲染指令。

模块纪律：只做几何（纯数学，可单测），不碰像素/进程——光栅化交给
_gdi_render.ps1（System.Drawing 抗锯齿），编排归 annotate_gdi。

形状双轨：
  矢量形状（rect/ellipse/line/arrow/step/number/text）编译为
    stroke（路径点列+宽，GDI+ Pen RoundCap/Join 抗锯齿）/ fill（多边形）/
    text / dot（圆底+居中数字）四类指令；
  像素操作（mosaic/blur/spotlight/smarterase）原样传回，由纯像素画布处理
    （它们是邻域统计，无抗锯齿概念）。
"""
import math

DEFAULT_COLOR = "#FF3B30"
DEFAULT_WIDTH = 3
DEFAULT_FONT = "Microsoft YaHei UI"   # v0.1.9 前写死于渲染脚本，现提为缺省值


def _hex(color):
    if not color:
        return DEFAULT_COLOR
    c = str(color).lstrip("#")
    if len(c) != 6:
        raise ValueError("颜色须 #RRGGBB：%r" % color)
    int(c, 16)   # 非法 hex 直接抛
    return "#" + c


def _nums(op, keys):
    if all(op.get(k) is None for k in keys):
        joined = op.get("coords") or op.get("area")
        if isinstance(joined, str):
            parts = [int(x) for x in str(joined).replace(" ", "").split(",")]
            if len(parts) == 4:
                return parts
    out = []
    for k in keys:
        if op.get(k) is None:
            raise ValueError("op 缺坐标键 %s：%r" % (k, op))
        out.append(float(op.get(k)))
    return out


def _rect_path(x, y, w, h, radius):
    """矩形/圆角矩形路径点列（radius>0 时四角 16 段圆弧）。"""
    if radius <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    r = max(0.0, min(radius, w / 2, h / 2))
    pts = []
    corners = ((x + w - r, y + r, -math.pi / 2, 0),
               (x + w - r, y + h - r, 0, math.pi / 2),
               (x + r, y + h - r, math.pi / 2, math.pi),
               (x + r, y + r, math.pi, math.pi * 1.5))
    first = True
    for cx, cy, a0, a1 in corners:
        for i in range(17):
            a = a0 + (a1 - a0) * i / 16
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            if first and i == 0:
                pts.append(pts[-1])   # 保证首段有长度
                first = False
    pts.append(pts[0])
    return pts


def _ellipse_path(x, y, w, h):
    """椭圆参数方程 96 段闭合路径。"""
    cx, cy, a, b = x + w / 2, y + h / 2, w / 2, h / 2
    if a <= 0 or b <= 0:
        raise ValueError("椭圆宽高须正")
    pts = []
    for i in range(97):
        t = 2 * math.pi * i / 96
        pts.append((cx + a * math.cos(t), cy + b * math.sin(t)))
    return pts


def _stroke(pts, color, width):
    return {"t": "stroke", "pts": [[round(px, 2), round(py, 2)]
                                   for px, py in pts],
            "color": _hex(color), "width": float(width)}


def _fat_arrow_poly(x1, y1, x2, y2, width):
    """渐变实心箭头多边形（v0.1.8 重校准）：头长=头宽=3.5×width（1:1 细
    三角）、短箭头长封顶 0.4×全长、杆恒定≈width（尾 0.35×width 幂 0.75
    温和渐变）+ 实心三角头 + 圆尾。与像素版 arrow 同参数语义
    （width=头部粗细基准）。业界参照（2026-10-28 调研，设计文档 §7.7.2）：
    Flameshot 杆恒定+细长三角头+短箭 clamp；matplotlib 头宽≤头长。"""
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1:
        return []
    ux, uy = dx / dist, dy / dist
    head_len = min(max(10.0, width * 3.5), dist * 0.4)   # 短箭封顶
    head_half = max(head_len * 0.5, width * 0.5)   # 头底不窄于杆端（极短箭域防凹肩）
    r_tail = max(1.2, width * 0.35)
    r_head = width * 0.5   # 杆接头=名义宽，零膨胀（旧 2×width 已废）
    shaft_len = max(0.0, dist - head_len)
    right, left = [], []
    steps = max(8, int(shaft_len * 2))
    for i in range(steps + 1):
        s = shaft_len * i / steps
        t = (s / shaft_len) ** 0.75 if shaft_len > 0 else 1.0
        r = r_tail + (r_head - r_tail) * t
        px, py = x1 + ux * s, y1 + uy * s
        right.append((px - uy * r, py + ux * r))   # +n̂ 侧，n̂=(-uy,ux)
        left.append((px + uy * r, py - ux * r))
    bx, by = x2 - ux * head_len, y2 - uy * head_len
    poly = list(right)
    poly.append((bx - uy * head_half, by + ux * head_half))
    poly.append((x2, y2))
    poly.append((bx + uy * head_half, by - ux * head_half))
    poly.extend(left[::-1])
    # 圆尾：从 -n̂r_tail（left[::-1] 末端）绕过 -t̂ 扫回 +n̂r_tail（=poly[0]，
    # a=π→0；闭合边零长。v0.1.8 修正旧正向追加——弧走反方向会在尾帽
    # 留下亚像素月牙缝，审计 P3-4）
    for i in range(11, -1, -1):
        a = math.pi * i / 12
        r = r_tail
        poly.append((x1 + r * (math.cos(a) * -uy + math.sin(a) * -ux),
                     y1 + r * (math.cos(a) * ux + math.sin(a) * -uy)))
    return poly


def compile_ops(ops):
    """JSON ops -> {"shapes": [...], "pixel_ops": [...]}。
    未知 kind 如实抛错（绝不静默跳过，与像素版契约一致）。"""
    shapes, pixel_ops = [], []
    step_n = 0
    for op in ops:
        kind = op.get("kind")
        color = _hex(op.get("color"))
        width = float(op.get("width", DEFAULT_WIDTH))
        if kind in ("mosaic", "blur", "spotlight", "smarterase"):
            pixel_ops.append(op)
            continue
        if kind in ("rect", "ellipse", "line"):
            if kind == "rect":
                x, y, w, h = _nums(op, ("x", "y", "w", "h"))
                pts = _rect_path(x, y, w, h, float(op.get("radius", 0)))
            elif kind == "ellipse":
                x, y, w, h = _nums(op, ("x", "y", "w", "h"))
                pts = _ellipse_path(x, y, w, h)
            else:
                x1, y1, x2, y2 = _nums(op, ("x1", "y1", "x2", "y2"))
                pts = [(x1, y1), (x2, y2)]
            shapes.append(_stroke(pts, color, width))
        elif kind == "arrow":
            x1, y1, x2, y2 = _nums(op, ("x1", "y1", "x2", "y2"))
            if str(op.get("style", "fat")) == "line":
                shapes.append(_stroke([(x1, y1), (x2, y2)], color, width))
                ang = math.atan2(y2 - y1, x2 - x1)
                ln = max(12.0, width * 4)
                for da in (2.6, -2.6):
                    shapes.append(_stroke(
                        [(x2, y2),
                         (x2 + ln * math.cos(ang + da),
                          y2 + ln * math.sin(ang + da))], color, width))
            else:
                poly = _fat_arrow_poly(x1, y1, x2, y2, width)
                if poly:
                    shapes.append({"t": "fill",
                                   "pts": [[round(px, 2), round(py, 2)]
                                           for px, py in poly],
                                   "color": color})
        elif kind in ("step", "number"):
            sz = float(op.get("size", 16))
            cx, cy = float(op.get("x", 0)) + sz, float(op.get("y", 0)) + sz
            if kind == "step":
                step_n += 1
                label = str(step_n)
            else:
                label = str(op.get("value", op.get("n", "1")))
            shapes.append({"t": "dot", "cx": cx, "cy": cy, "r": sz,
                           "color": color, "label": label})
        elif kind == "text":
            shapes.append({"t": "text",
                           "x": float(op.get("x", 0)),
                           "y": float(op.get("y", 0)),
                           "s": str(op.get("text", "")),
                           "size": float(op.get("size", 16)),
                           "color": color,
                           "font": str(op.get("font", DEFAULT_FONT)),
                           "bold": bool(op.get("bold", True))})
        else:
            raise ValueError("未知标注 kind：%r" % kind)
    return {"shapes": shapes, "pixel_ops": pixel_ops}
