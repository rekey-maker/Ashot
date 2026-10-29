# -*- coding: utf-8 -*-
"""Ashot.geometry —— 纯几何：把曲线/弧线采样成点列（零依赖、可单测）。

为什么单独一层：矢量路（vector.py → GDI+ DrawLines）和像素降级路
（annotate.py 的 Canvas.line）都需要同一套采样。抄两遍必然漂移——
这正是 imgtool 两套箭头几何的教训。

采样密度的依据（2026-10-29，官方文档 + 曲线细分惯例）：
  · GDI+ 的 `Graphics.DrawBezier` 内部同样把曲线展平成折线再描边
    （见 Microsoft Learn：DrawBezier(Pen, x1,y1,x2,y2,x3,y3,x4,y4)，
      "drawn from the first point to the fourth point，中间两点是控制点"）；
    我们用 DrawLines 画采样点，等价且让几何留在 Python（渲染端保持 dumb）。
  · 采样步数按**控制多边形长度**自适应（弦长越长越密），夹在 16~128；
    这是曲线细分的常规做法（de Casteljau 递归 / 固定弧长步进的简化版）。
  · 弧线 `Graphics.DrawArc` 的语义：角度制、从 x 轴顺时针、start+sweep
    （Microsoft Learn 原文）。屏幕坐标 y 向下，参数方程 (cos t, sin t)
    随 t 增大同样是顺时针，两者一致。
"""
import math

ARC_MIN_STEPS = 8
ARC_MAX_STEPS = 180
ARC_DEG_PER_STEP = 2.0        # ≈2° 一段：半径 500px 时弦高 < 0.02px

BEZ_MIN_STEPS = 16
BEZ_MAX_STEPS = 128
BEZ_PX_PER_STEP = 4.0         # 控制多边形每 ~4px 取一个采样点


def bezier_points(x0, y0, c1x, c1y, c2x, c2y, x1, y1, steps=None):
    """三次贝塞尔采样 -> [(x, y), ...]（含首尾）。

    自适应步数：按控制多边形长度 / BEZ_PX_PER_STEP，夹在 16~128。
    """
    x0, y0, c1x, c1y, c2x, c2y, x1, y1 = (
        _finite(x0), _finite(y0), _finite(c1x), _finite(c1y),
        _finite(c2x), _finite(c2y), _finite(x1), _finite(y1))
    if steps is None:
        poly = (math.hypot(c1x - x0, c1y - y0)
                + math.hypot(c2x - c1x, c2y - c1y)
                + math.hypot(x1 - c2x, y1 - c2y))
        steps = int(math.ceil(poly / BEZ_PX_PER_STEP))
        steps = max(BEZ_MIN_STEPS, min(BEZ_MAX_STEPS, steps))
    steps = max(1, int(steps))
    pts = []
    for i in range(steps + 1):
        t = i / float(steps)
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((a * x0 + b * c1x + c * c2x + d * x1,
                    a * y0 + b * c1y + c * c2y + d * y1))
    return pts


def arc_points(x, y, w, h, start_deg=0.0, sweep_deg=360.0, steps=None):
    """椭圆弧采样 -> [(x, y), ...]。

    x,y,w,h = 外接矩形（与 GDI+ DrawArc 同义）；start/sweep 单位**度**，
    与 GDI+ 一致（从 x 轴顺时针，屏幕 y 向下）。
    sweep<0 = 逆时针；|sweep|>360 夹到 360（GDI+ 也不画超过一圈）。
    """
    x, y, w, h = _finite(x), _finite(y), _finite(w), _finite(h)
    start_deg = _finite(start_deg, "start")
    sweep = _finite(sweep_deg, "sweep")
    if w <= 0 or h <= 0:
        raise ValueError("arc 宽高须 > 0（got w=%r h=%r）" % (w, h))
    if sweep == 0:
        raise ValueError("arc 的 sweep 不能为 0（没有可画的弧）")
    sweep = max(-360.0, min(360.0, sweep))
    if steps is None:
        steps = int(math.ceil(abs(sweep) / ARC_DEG_PER_STEP))
        steps = max(ARC_MIN_STEPS, min(ARC_MAX_STEPS, steps))
    steps = max(1, int(steps))
    cx, cy, a, b = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
    pts = []
    for i in range(steps + 1):
        deg = float(start_deg) + sweep * i / float(steps)
        t = math.radians(deg)
        pts.append((cx + a * math.cos(t), cy + b * math.sin(t)))
    return pts


def polyline_points(points):
    """折线点列规范化：[(x,y),...]；去掉连续重复点，至少保留 2 个。"""
    pts = []
    for p in points:
        if len(p) != 2:
            raise ValueError("polyline 每个点要 [x, y]：%r" % (p,))
        xy = (_finite(p[0]), _finite(p[1]))
        if not pts or abs(pts[-1][0] - xy[0]) > 1e-9 \
                or abs(pts[-1][1] - xy[1]) > 1e-9:
            pts.append(xy)
    if len(pts) < 2:
        raise ValueError("polyline 至少需要 2 个不同的点（got %d）" % len(pts))
    return pts


def pad_points(pts):
    """描边至少要有两个点（GDI+ DrawLines / 像素线都要求）。"""
    if len(pts) == 1:
        return [pts[0], pts[0]]
    return pts


# ---------- op 解析（矢量路与像素路共用同一套 schema 解析） ----------

COORD_LIMIT = 1e7      # 坐标上限：图像维度远小于此，超限必然派生 inf/溢出


def _finite(v, what="坐标"):
    """转 float，拒绝 NaN/inf 与超范围值。

    只查 isfinite 不够：1e308 级的**有限**坐标在 `cx + a*cos`、控制多边形
    求和时照样溢出成 inf，再一路传到 PS（JSON 出 Infinity、PS 单精度变
    Infinity），最后在像素降级路 `int(round(inf))` 抛 OverflowError——
    不是契约要求的 ValueError。所以在入口就把 |v| 夹到合理范围。
    """
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("%s 必须是有限数：%r" % (what, v))
    if abs(f) > COORD_LIMIT:
        raise ValueError("%s 超出合理范围（|v| ≤ %g）：%r"
                         % (what, COORD_LIMIT, v))
    return f


def _float_list(text, n=None, even=False):
    parts = [_finite(x) for x in str(text).replace(" ", ",").split(",")
             if x.strip()]
    if n is not None and len(parts) != n:
        raise ValueError("期望 %d 个数字，got %d：%r" % (n, len(parts), text))
    if even and (len(parts) < 4 or len(parts) % 2):
        raise ValueError("折线坐标须为偶数个（x,y 成对，≥4）：%r" % (text,))
    return parts


def parse_curve(op):
    """curve -> (x0,y0,c1x,c1y,c2x,c2y,x1,y1)。

    三种写法都认：显式键 / `points=[[x,y]×4]` / `coords="8 个数字"`。
    """
    pts = op.get("points")
    if pts:
        if len(pts) != 4:
            raise ValueError("curve 的 points 要 4 个点（P0,C1,C2,P3）：%r"
                             % (op,))
        flat = []
        for p in pts:
            if len(p) != 2:
                raise ValueError("curve 的 points 每项要 [x, y]：%r" % (p,))
            flat.extend((_finite(p[0]), _finite(p[1])))
        return tuple(flat)
    keys = ("x0", "y0", "c1x", "c1y", "c2x", "c2y", "x1", "y1")
    vals = [op.get(k) for k in keys]
    if any(v is None for v in vals):
        joined = op.get("coords")
        if joined is not None:
            return tuple(_float_list(joined, 8))
        raise ValueError("curve 需要 %s（8 个数字），或 points=[[x,y]×4]，"
                         "或 coords=\"x0,y0,c1x,c1y,c2x,c2y,x1,y1\"：%r"
                         % ("/".join(keys), op))
    return tuple(_finite(v) for v in vals)


def parse_arc(op):
    """arc -> (x, y, w, h, start, sweep)，角度制（与 GDI+ DrawArc 同义）。"""
    vals = [op.get(k) for k in ("x", "y", "w", "h")]
    if any(v is None for v in vals):
        raise ValueError("arc 需要外接矩形 x,y,w,h：%r" % (op,))
    x, y, w, h = (_finite(v) for v in vals)
    start = _finite(op.get("start", op.get("start_angle", 0)) or 0,
                    "start")
    sweep = op.get("sweep", op.get("sweep_angle"))
    if sweep is None:
        end = op.get("end", op.get("end_angle"))
        if end is None:
            raise ValueError("arc 需要 sweep（度）或 end（度）：%r" % (op,))
        sweep = _finite(end, "end") - start
    return x, y, w, h, start, _finite(sweep, "sweep")


def parse_polyline(op):
    """polyline -> [[x,y],...]；`points` 或 `coords="x1,y1,x2,y2,..."`。"""
    pts = op.get("points")
    if pts:
        return pts
    joined = op.get("coords")
    if joined is not None:
        flat = _float_list(joined, even=True)
        return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]
    raise ValueError("polyline 需要 points=[[x,y],...] 或 coords=\"x1,y1,x2,y2,...\"：%r"
                     % (op,))



def clip_segment(x0, y0, x1, y1, w, h):
    """把线段裁到画布 [0,w]×[0,h]；完全在外返回 None。

    像素降级路按 Bresenham 逐像素走，若线段从画布外很远处穿过，会白跑
    几百万步（审查 P2-4）。先裁再画即可。
    """
    left, right, bottom, top = 1, 2, 4, 8

    def code(x, y):
        c = 0
        if x < 0:
            c |= left
        elif x > w:
            c |= right
        if y < 0:
            c |= top
        elif y > h:
            c |= bottom
        return c

    c0, c1 = code(x0, y0), code(x1, y1)
    for _ in range(8):                 # 最多 4 次求交，8 轮足够
        if not (c0 | c1):
            return (x0, y0, x1, y1)
        if c0 & c1:
            return None
        c = c0 or c1
        if c & top:
            x = x0 + (x1 - x0) * (0.0 - y0) / (y1 - y0)
            y = 0.0
        elif c & bottom:
            x = x0 + (x1 - x0) * (h - y0) / (y1 - y0)
            y = float(h)
        elif c & left:
            y = y0 + (y1 - y0) * (0.0 - x0) / (x1 - x0)
            x = 0.0
        else:
            y = y0 + (y1 - y0) * (w - x0) / (x1 - x0)
            x = float(w)
        if c == c0:
            x0, y0 = x, y
            c0 = code(x0, y0)
        else:
            x1, y1 = x, y
            c1 = code(x1, y1)
    return None
