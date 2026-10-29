# -*- coding: utf-8 -*-
"""v0.4.1 新原语：curve（三次贝塞尔）/ arc（椭圆弧）/ polyline（折线）。

重点锁三件事：
1. 几何（纯函数）：端点、对称性、采样密度、角度方向；
2. 矢量路：采样点 → GDI+ 抗锯齿描边（与箭头同一条原理），边缘必须有中间色；
3. 像素降级路：同一条曲线要能画出来（硬边），且两路用的采样一致。
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, annotate_gdi, geometry, output, vector  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bg(w=340, h=240):
    return output.bgra_to_png(w, h, bytes((0x20, 0x20, 0x20, 0xFF)) * (w * h))


def _colors(png):
    _, _, px = annotate._decode_png(png)
    return {(px[i], px[i + 1], px[i + 2]) for i in range(0, len(px), 4)}


def _px_at(png, x, y):
    w, _, px = annotate._decode_png(png)
    i = (y * w + x) * 4
    return (px[i], px[i + 1], px[i + 2])


# ---------- 几何 ----------

def test_bezier_endpoints_and_steps():
    pts = geometry.bezier_points(0, 0, 10, 40, 40, 40, 50, 0)
    assert pts[0] == (0.0, 0.0), "首点必须是 P0"
    assert abs(pts[-1][0] - 50) < 1e-9 and abs(pts[-1][1]) < 1e-9, "末点必须是 P3"
    assert 16 <= len(pts) - 1 <= 128, "采样步数应夹在 16~128"
    # 控制多边形很长的曲线取样更密
    far = geometry.bezier_points(0, 0, 400, 400, 800, 400, 1200, 0)
    assert len(far) > len(pts)


def test_bezier_midpoint_symmetry():
    """对称控制点 → 中点落在对称轴上（t=0.5 的解析解）。"""
    pts = geometry.bezier_points(0, 100, 50, 0, 150, 0, 200, 100, steps=2)
    mid = pts[1]
    # B(0.5) = (P0 + 3C1 + 3C2 + P3)/8 → x=(0+150+450+200)/8=100, y=(100+0+0+100)/8=25
    assert abs(mid[0] - 100) < 1e-9 and abs(mid[1] - 25) < 1e-9


def test_arc_direction_and_clamp():
    p0 = geometry.arc_points(0, 0, 100, 100, 0, 90, steps=2)
    assert abs(p0[0][0] - 100) < 1e-9 and abs(p0[0][1] - 50) < 1e-9, "0°=最右"
    assert abs(p0[-1][0] - 50) < 1e-9 and abs(p0[-1][1] - 100) < 1e-9, "90°=最下"
    # 逆时针：sweep 负值 → -90° 落在最上（x 回到圆心 50，y 到 0）
    neg = geometry.arc_points(0, 0, 100, 100, 0, -90, steps=2)
    assert abs(neg[-1][0] - 50) < 1e-9 and abs(neg[-1][1]) < 1e-9, "-90° 到最上"
    # 超过一圈夹到 360（**默认步数**才走 clamp 分支：720° 不夹会要 360° 的
    # 两倍步数；夹后 = 180 段 → 181 点，且首尾重合）
    full = geometry.arc_points(0, 0, 100, 100, 0, 720)
    assert len(full) == 181, len(full)
    assert abs(full[0][0] - full[-1][0]) < 1e-6
    assert abs(full[0][1] - full[-1][1]) < 1e-6
    with pytest.raises(ValueError):
        geometry.arc_points(0, 0, 100, 100, 0, 0)
    with pytest.raises(ValueError):
        geometry.arc_points(0, 0, 0, 100, 0, 90)


def test_polyline_dedupe_and_validation():
    pts = geometry.polyline_points([[0, 0], [0, 0], [10, 10]])
    assert pts == [(0.0, 0.0), (10.0, 10.0)], "连续重复点应合并"
    with pytest.raises(ValueError):
        geometry.polyline_points([[0, 0]])
    with pytest.raises(ValueError):
        geometry.polyline_points([[0, 0], [1]])


# ---------- op 解析（三种写法） ----------

def test_parse_curve_forms():
    a = geometry.parse_curve({"x0": 1, "y0": 2, "c1x": 3, "c1y": 4,
                              "c2x": 5, "c2y": 6, "x1": 7, "y1": 8})
    b = geometry.parse_curve({"points": [[1, 2], [3, 4], [5, 6], [7, 8]]})
    c = geometry.parse_curve({"coords": "1,2,3,4,5,6,7,8"})
    assert a == b == c == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    with pytest.raises(ValueError):
        geometry.parse_curve({"x0": 1})


def test_non_finite_rejected():
    """NaN/inf 不能让 PS 静默画不出：解析阶段就报错。"""
    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(ValueError):
            geometry.parse_curve({"coords": "0,0,%s,0,0,0,1,1" % bad})
    with pytest.raises(ValueError):
        geometry.parse_arc({"x": 0, "y": 0, "w": 10, "h": 10,
                            "sweep": float("nan")})
    with pytest.raises(ValueError):
        geometry.polyline_points([[0, 0], [float("inf"), 1]])


def test_coord_range_guard_and_clip_segment():
    """有限但超范围的坐标必须入口报错：否则 PS 单精度变 Infinity、
    像素降级路 int(round(inf)) 抛 OverflowError（审查 P1-2/P1-3/P2-4）。"""
    with pytest.raises(ValueError):
        geometry.bezier_points(0, 0, 1e308, 0, 0, 0, 1, 1)
    with pytest.raises(ValueError):
        geometry.arc_points(1e308, 0, 1e308, 1e308, 0, 90)
    with pytest.raises(ValueError):
        geometry.polyline_points([[0, 0], [1e9, 1]])
    # 线段裁剪：整段在外 -> None；跨边界 -> 夹到画布；完全在内 -> 原样
    assert geometry.clip_segment(200, 200, 300, 300, 100, 100) is None
    assert geometry.clip_segment(-10, -10, 20, 20, 100, 100) == (0.0, 0.0, 20, 20)
    assert geometry.clip_segment(-100, 50, 200, 50, 100, 100) == \
        (0.0, 50.0, 100.0, 50.0)


def test_parse_arc_and_polyline_forms():
    assert geometry.parse_arc({"x": 0, "y": 0, "w": 10, "h": 10,
                               "start": 30, "sweep": 120}) == \
        (0.0, 0.0, 10.0, 10.0, 30.0, 120.0)
    # end 别名：sweep = end - start
    assert geometry.parse_arc({"x": 0, "y": 0, "w": 10, "h": 10,
                               "start": 30, "end": 150})[5] == 120.0
    with pytest.raises(ValueError):
        geometry.parse_arc({"x": 0, "y": 0, "w": 10, "h": 10})
    assert geometry.parse_polyline({"coords": "0,0,10,10,20,0"}) == \
        [[0.0, 0.0], [10.0, 10.0], [20.0, 0.0]]
    with pytest.raises(ValueError):
        geometry.parse_polyline({"coords": "0,0,10"})


# ---------- 编译 ----------

def test_compile_shapes_and_index():
    ops = [{"kind": "curve", "x0": 0, "y0": 0, "c1x": 10, "c1y": 20,
            "c2x": 30, "c2y": 20, "x1": 40, "y1": 0},
           {"kind": "arc", "x": 0, "y": 0, "w": 20, "h": 20, "start": 0,
            "sweep": 90},
           {"kind": "polyline", "points": [[0, 0], [5, 5], [9, 0]]}]
    spec = vector.compile_ops(ops)
    assert [s["t"] for s in spec["shapes"]] == ["stroke"] * 3
    assert [s["i"] for s in spec["shapes"]] == [0, 1, 2]
    assert len(spec["shapes"][2]["pts"]) == 3
    # 坐标统一 round(2) 序列化（渲染端零形状数学）
    assert all(isinstance(v, (int, float)) for s in spec["shapes"]
               for p in s["pts"] for v in p)


def test_compile_rejects_bad_geometry():
    with pytest.raises(ValueError):
        vector.compile_ops([{"kind": "curve", "x0": 0}])
    with pytest.raises(ValueError):
        vector.compile_ops([{"kind": "polyline", "points": [[0, 0]]}])
    with pytest.raises(ValueError):
        vector.compile_ops([{"kind": "arc", "x": 0, "y": 0, "w": 0, "h": 10,
                             "start": 0, "sweep": 90}])


# ---------- 渲染：矢量 vs 像素 ----------

def _ink(png):
    _, _, px = annotate._decode_png(png)
    bg = (0x20, 0x20, 0x20)
    return sum(1 for i in range(0, len(px), 4)
               if (px[i], px[i + 1], px[i + 2]) != bg)


def test_pixel_and_vector_cover_the_same_curve():
    """两路必须画同一条曲线：墨量差 ≤5%（证明像素路没漏末段/步长一致）。"""
    ops = [{"kind": "curve", "x0": 20, "y0": 160, "c1x": 80, "c1y": 20,
            "c2x": 180, "c2y": 220, "x1": 280, "y1": 80, "width": 5,
            "color": "#00E5FF"}]
    vec, backend, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    px = annotate.annotate_png(_bg(), ops)
    iv, ip = _ink(vec), _ink(px)
    assert backend == "gdi+"
    assert abs(iv - ip) <= max(10, int(iv * 0.05)), (iv, ip)


_SHAPES = [
    {"kind": "curve", "x0": 20, "y0": 160, "c1x": 80, "c1y": 20,
     "c2x": 180, "c2y": 220, "x1": 280, "y1": 80, "width": 5,
     "color": "#00E5FF"},
    {"kind": "arc", "x": 40, "y": 40, "w": 200, "h": 120, "start": 0,
     "sweep": 270, "width": 4, "color": "#FF9500"},
    {"kind": "polyline", "points": [[240, 40], [300, 80], [260, 140],
                                    [320, 180]], "width": 3,
     "color": "#07C160"},
]


def test_vector_render_is_antialiased():
    """与箭头同一条原理：GDI+ 抗锯齿描边 → 边缘有中间色（不是纯色硬边）。"""
    out, backend, pixel_n = annotate_gdi.annotate_png_vector(_bg(), _SHAPES)
    assert backend == "gdi+" and pixel_n == 0
    cols = _colors(out)
    assert len(cols) > 40, "抗锯齿应产生大量过渡色（got %d）" % len(cols)
    assert (0x00, 0xE5, 0xFF) in cols and (0xFF, 0x95, 0x00) in cols


def test_curve_is_curved_not_a_chord():
    """证伪「用弦糊弄」：弧顶必须出墨、弦中点必须是背景。

    弯成 U 形的曲线：B(0.5)=(135,55)，弦中点=(150,160)，相距 100+px——
    只画直线/弦的实现会在弦中点出墨、弧顶空着。
    """
    ops = [{"kind": "curve", "x0": 20, "y0": 160, "c1x": 80, "c1y": 20,
            "c2x": 180, "c2y": 20, "x1": 280, "y1": 160, "width": 5,
            "color": "#00E5FF"}]
    out, _, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    assert _px_at(out, 135, 55) != (0x20, 0x20, 0x20), "弧顶没出墨"
    assert _px_at(out, 150, 160) == (0x20, 0x20, 0x20), "弦中点出墨=画成了直线"


def test_pixel_fallback_draws_same_shapes():
    out = annotate.annotate_png(_bg(), _SHAPES)
    cols = _colors(out)
    assert (0x00, 0xE5, 0xFF) in cols, "像素路也要有曲线颜色"
    assert (0xFF, 0x95, 0x00) in cols, "像素路也要有弧线颜色"
    assert (0x07, 0xC1, 0x60) in cols, "像素路也要有折线颜色"


def test_both_paths_share_sampling(monkeypatch):
    """契约 1 的真锁：两路必须调用**同一个** geometry.bezier_points。

    （旧写法「像素路颜色数更少」是恒真式——硬边画布画什么都少。）
    """
    calls = []
    orig = geometry.bezier_points

    def counted(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(geometry, "bezier_points", counted)
    ops = [{"kind": "curve", "x0": 20, "y0": 160, "c1x": 80, "c1y": 20,
            "c2x": 180, "c2y": 220, "x1": 280, "y1": 80, "width": 5}]
    annotate_gdi.annotate_png_vector(_bg(), ops)
    annotate.annotate_png(_bg(), ops)
    assert len(calls) == 2, "两路没有共用同一套采样（calls=%d）" % len(calls)


def test_curve_out_of_canvas_warns():
    """曲线也进 bounds_warn（bbox 由采样点算，不靠估算）。"""
    ops = [{"kind": "curve", "x0": 10, "y0": 10, "c1x": 400, "c1y": 10,
            "c2x": 400, "c2y": 10, "x1": 410, "y1": 10, "width": 4}]
    st = {}
    annotate_gdi.annotate_png_vector(_bg(), ops, stats=st)
    assert st.get("bounds_warn"), "越过右边界必须亮牌"
    assert "op[0]" in st["bounds_warn"][0]


def test_cli_renders_new_shapes(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_bg())
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps(_SHAPES), "utf-8")
    out = tmp_path / "o.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "annotate",
                        str(src), "--ops-file", str(ops), "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "backend: gdi+" in r.stderr
    assert len(_colors(out.read_bytes())) > 40
