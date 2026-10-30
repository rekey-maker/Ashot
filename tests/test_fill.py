# -*- coding: utf-8 -*-
"""v0.7.4 fill（色块填充）。

锁四件事：
1. 编译：闭合形状带 fill → 先 fill 后 stroke，fill 带 op 下标；
2. 校验：非闭合 kind（line/text）给 fill → apply_pad 报错；
3. 渲染两路：实心色块（GDI+ Winding + 像素扫描线 non-zero）内部出色；
4. 半透明 #RRGGBBAA：GDI+ 与像素路都 source-over 混合（出中间色）。
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, annotate_gdi, output, vector  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bg(w=340, h=240):
    return output.bgra_to_png(w, h, bytes((0x20, 0x20, 0x20, 0xFF)) * (w * h))


def _px_at(png, x, y):
    w, _, px = annotate._decode_png(png)
    i = (y * w + x) * 4
    return (px[i], px[i + 1], px[i + 2])


def _n_of_color(png, rgb):
    _, _, px = annotate._decode_png(png)
    return sum(1 for i in range(0, len(px), 4)
               if (px[i], px[i + 1], px[i + 2]) == rgb)


# ---------- 编译 ----------

def test_fill_emits_fill_before_stroke():
    for op in ({"kind": "rect", "x": 10, "y": 10, "w": 60, "h": 40,
                "fill": "#FF0000", "color": "#00FF00"},
               {"kind": "ellipse", "x": 10, "y": 10, "w": 60, "h": 40,
                "fill": "#FF0000"},
               {"kind": "polyline", "points": [[10, 10], [60, 20], [40, 60]],
                "fill": "#FF0000"},
               {"kind": "arc", "x": 10, "y": 10, "w": 80, "h": 80,
                "start": 0, "sweep": 90, "fill": "#FF0000"},
               {"kind": "curve", "x0": 10, "y0": 10, "c1x": 40, "c1y": 60,
                "c2x": 60, "c2y": 10, "x1": 70, "y1": 50, "fill": "#FF0000"}):
        spec = vector.compile_ops(vector.apply_pad([op]))
        kinds = [s["t"] for s in spec["shapes"]]
        assert "fill" in kinds and "stroke" in kinds, (op["kind"], kinds)
        assert kinds.index("fill") < kinds.index("stroke"), \
            "色块必须先画，描边压在上面"
        assert all(s["i"] == 0 for s in spec["shapes"])
        fill = next(s for s in spec["shapes"] if s["t"] == "fill")
        assert fill["color"] == "#FF0000"
        assert len(fill["pts"]) >= 3


def test_arc_fill_is_pie_centered():
    """弧 fill = 扇形：点列首点是圆心（弧两半径夹出）。"""
    op = {"kind": "arc", "x": 0, "y": 0, "w": 100, "h": 100,
          "start": 0, "sweep": 90, "fill": "#FF0000"}
    spec = vector.compile_ops(vector.apply_pad([op]))
    fill = next(s for s in spec["shapes"] if s["t"] == "fill")
    assert fill["pts"][0] == [50.0, 50.0], "首点必须是椭圆圆心"


def test_line_and_text_reject_fill():
    for op in ({"kind": "line", "x1": 0, "y1": 0, "x2": 40, "y2": 20,
                "fill": "#FF0000"},
               {"kind": "text", "x": 5, "y": 5, "text": "hi",
                "fill": "#FF0000"}):
        with pytest.raises(ValueError):
            vector.apply_pad([op])


def test_fill_hex_length_and_bad_hex():
    assert vector._hex("#FF000080") == "#FF000080"
    with pytest.raises(ValueError):
        vector._hex("#FFF")
    with pytest.raises(ValueError):
        vector._hex("#GG0000")


# ---------- 渲染：实心色块两路 ----------

def test_solid_fill_renders_both_paths():
    ops = [{"kind": "rect", "x": 60, "y": 60, "w": 120, "h": 80,
            "fill": "#FF0000", "width": 4, "color": "#FF0000"}]
    vec, backend, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    assert backend == "gdi+"
    assert _px_at(vec, 120, 100) == (0xFF, 0x00, 0x00), "矢量路内部应是纯填充色"
    px = annotate.annotate_png(_bg(), ops)
    assert _px_at(px, 120, 100) == (0xFF, 0x00, 0x00), "像素路内部应是纯填充色"
    # 色块外仍是背景
    assert _px_at(vec, 10, 10) == (0x20, 0x20, 0x20)


def test_semi_transparent_fill_blends_both_paths():
    """#RRGGBBAA：GDI+ 与像素路都 source-over，出中间色（不是纯红也不是背景）。"""
    ops = [{"kind": "ellipse", "x": 60, "y": 60, "w": 120, "h": 80,
            "fill": "#FF000080"}]
    vec, _, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    px = annotate.annotate_png(_bg(), ops)
    for name, img in (("gdi+", vec), ("pixel", px)):
        r, g, b = _px_at(img, 120, 100)
        assert 0x20 < r < 0xFF, (name, r)      # 红被半透明抬升但未饱和
        assert g < 0x20 and b < 0x20, (name, g, b)   # 绿蓝被拉向 0（红调混入）


def test_fill_stroke_overlap_parity():
    """fill+同色描边：两路内部都应是纯填充色（Winding vs non-zero 不吞内部）。"""
    ops = [{"kind": "polyline", "points": [[80, 60], [200, 70], [150, 180],
                                           [90, 160]],
            "fill": "#00E5FF", "color": "#00E5FF", "width": 6}]
    vec, _, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    px = annotate.annotate_png(_bg(), ops)
    assert _px_at(vec, 140, 110) == (0x00, 0xE5, 0xFF)
    assert _px_at(px, 140, 110) == (0x00, 0xE5, 0xFF)


def test_fill_concave_parity_nonzero_vs_evenodd():
    """凹多边形（自交边界）non-zero 规则：内点两路都出墨。"""
    pts = [[40, 40], [220, 40], [130, 120], [220, 200], [40, 200], [130, 120]]
    ops = [{"kind": "polyline", "points": pts, "fill": "#07C160"}]
    vec, _, _ = annotate_gdi.annotate_png_vector(_bg(), ops)
    px = annotate.annotate_png(_bg(), ops)
    # 上半凹角处内点：两路都绿
    assert _px_at(vec, 130, 90) == (0x07, 0xC1, 0x60)
    assert _px_at(px, 130, 90) == (0x07, 0xC1, 0x60)


def test_fill_bounds_warn_still_works():
    ops = [{"kind": "rect", "x": 10, "y": 10, "w": 400, "h": 40,
            "fill": "#FF0000"}]
    st = {}
    annotate_gdi.annotate_png_vector(_bg(), ops, stats=st)
    assert st.get("bounds_warn"), "填充矩形越右界必须亮牌"


def test_cli_fill_via_ops_file(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_bg())
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps(
        [{"kind": "ellipse", "x": 60, "y": 60, "w": 120, "h": 80,
          "fill": "#FF9500", "color": "#FF9500"}]), "utf-8")
    out = tmp_path / "o.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "annotate",
                        str(src), "--ops-file", str(ops), "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "backend: gdi+" in r.stderr
    assert _px_at(out.read_bytes(), 120, 100) == (0xFF, 0x95, 0x00)


def test_stroke_alpha_rejected_both_paths():
    """v0.7.4 审查修正：像素路描边不做 alpha，8 位 color 在入口拒绝，
    避免 GDI+ 半透明 / 像素路不透明两种结果。"""
    op = {"kind": "line", "x1": 10, "y1": 10, "x2": 60, "y2": 60,
          "color": "#FF000080", "width": 4}
    with pytest.raises(ValueError):
        annotate.annotate_png(_bg(), [op])
    with pytest.raises(ValueError):
        annotate_gdi.annotate_png_vector(_bg(), [op])


def test_transparent_bg_fill_alpha_matches_both_paths():
    """透明底上的半透明 fill：两路都应是 (255,0,0,128)，不是黑底不透明。"""
    bg = output.bgra_to_png(20, 20, bytes((0, 0, 0, 0)) * (20 * 20))
    op = {"kind": "rect", "x": 2, "y": 2, "w": 10, "h": 10,
          "fill": "#FF000080"}
    vec, _, _ = annotate_gdi.annotate_png_vector(bg, [op])
    px = annotate.annotate_png(bg, [op])
    for name, img in (("gdi+", vec), ("pixel", px)):
        w, h, data = annotate._decode_png(img)
        i = (7 * w + 7) * 4
        assert tuple(data[i:i + 4]) == (0xFF, 0x00, 0x00, 0x80), name


def test_fill_alpha_zero_is_noop():
    """alpha=00 的 fill 不应把像素改成不透明。"""
    bg = output.bgra_to_png(20, 20, bytes((0, 0, 0, 0)) * (20 * 20))
    op = {"kind": "rect", "x": 2, "y": 2, "w": 10, "h": 10,
          "fill": "#FF000000"}
    px = annotate.annotate_png(bg, [op])
    w, h, data = annotate._decode_png(px)
    i = (7 * w + 7) * 4
    assert tuple(data[i:i + 4]) == (0, 0, 0, 0)
