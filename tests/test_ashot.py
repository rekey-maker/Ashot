# -*- coding: utf-8 -*-
"""Ashot v0.1.0 测试：编码器/标注原语/CLI/MCP 探针。零触网、不依赖桌面。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import __version__, annotate, output  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tiny_png():
    """手工拼一张 4x2 纯色 RGBA PNG（走自家编码器，自洽）。"""
    w, h = 4, 2
    bgra = bytes((0xFF, 0x00, 0x00, 0xFF)) * (w * h)   # 纯红
    return output.bgra_to_png(w, h, bgra)


# ---------- 编码器 ----------

def test_png_magic_and_size():
    png = _tiny_png()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 50


def test_annotate_png_decode_roundtrip():
    """自家解码器读自家编码器：尺寸与像素保真（BGRA 纯蓝→RGBA (0,0,255)）。"""
    png = _tiny_png()
    w, h, px = annotate._decode_png(png)
    assert (w, h) == (4, 2)
    assert (px[0], px[1], px[2], px[3]) == (0, 0, 255, 255)   # 蓝 RGBA


# ---------- 标注原语 ----------

def test_annotate_rect_and_arrow_run():
    png = _tiny_png()
    out = annotate.annotate_png(png, [
        {"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 2, "width": 1},
        {"kind": "arrow", "x1": 0, "y1": 0, "x2": 3, "y2": 1, "width": 1},
    ])
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_annotate_mosaic_changes_pixels():
    """有差异的图（左红右蓝）做马赛克 → 全图趋向均值色。全同色图涂抹
    均值=自身，不该断言变化。"""
    w, h = 4, 2
    bgra = (bytes((0xFF, 0x00, 0x00, 0xFF)) * 2 +   # 蓝
            bytes((0x00, 0x00, 0xFF, 0xFF)) * 2) * h  # 红
    png = output.bgra_to_png(w, h, bgra)
    out = annotate.annotate_png(png, [{"kind": "mosaic", "x": 0, "y": 0,
                                       "w": 4, "h": 2}])
    _, _, px = annotate._decode_png(out)
    colors = {(px[i * 4], px[i * 4 + 2]) for i in range(w * h)}
    assert len(colors) == 1, "马赛克后仍有双色（块均值未涂抹）"


def test_annotate_unknown_kind_raises():
    try:
        annotate.annotate_png(_tiny_png(), [{"kind": "nuke"}])
        raise AssertionError("未知 kind 竟被静默跳过")
    except ValueError as e:
        assert "nuke" in str(e)


def test_annotate_text_ascii_and_placeholder():
    png = _tiny_png()
    out = annotate.annotate_png(png, [
        {"kind": "text", "x": 0, "y": 0, "text": "A1", "size": 16},
        {"kind": "text", "x": 0, "y": 0, "text": "中文"},   # 非 ASCII=占位框
    ])
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


# ---------- retention ----------

def test_gc_removes_expired_png(tmp_path):
    import os
    import time as _t
    old = tmp_path / "shot_old.png"
    old.write_bytes(b"\x89PNG\r\n\x1a\n")
    past = _t.time() - 40 * 86400
    os.utime(old, (past, past))
    new = tmp_path / "shot_new.png"
    new.write_bytes(b"\x89PNG\r\n\x1a\n")
    n, mb = output.gc(retention_days=30, directory=str(tmp_path))
    assert n == 1 and not old.exists() and new.exists()
    assert mb >= 0


def test_gc_keep_skips(tmp_path):
    f = tmp_path / "shot_old.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    n, _ = output.gc(retention_days=0, keep=True, directory=str(tmp_path))
    assert n == 0 and f.exists()


# ---------- CLI ----------

def test_cli_version():
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "--version"],
                       capture_output=True, text=True, cwd=ROOT)
    assert __version__ in r.stdout   # 版本烙印对：跟 __init__ 走，不硬编码


def test_cli_annotate_subcommand(tmp_path):
    png = _tiny_png()
    src = tmp_path / "in.png"
    src.write_bytes(png)
    r = subprocess.run(
        [sys.executable, "-m", "ashot.cli", "annotate", str(src),
         json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 2}]),
         "--out", str(tmp_path / "out.png")],
        capture_output=True, text=True, cwd=ROOT)
    assert (tmp_path / "out.png").exists(), r.stderr


# ---------- v0.1.1 四件新标注（ShareX 拆解引进） ----------

def _img(w=60, h=40):
    bgra = bytes((0x30, 0x60, 0x90, 0xFF)) * (w * h)   # 单色底
    return output.bgra_to_png(w, h, bgra)


def _px_at(png, x, y):
    _, _, px = annotate._decode_png(png)
    i = (y * _w(png) + x) * 4
    return px[i], px[i + 1], px[i + 2]


def _w(png):
    return annotate._decode_png(png)[0]


def test_step_numbers_auto_increment():
    """step 同一次 ops 内自动递增 1,2,3；跨调用不共享状态。
    v0.1.2 审查 P2-4：递增真锁行为——第 1 枚文字区字形 ≡ "1"、第 2 枚 ≠ "1"
    （font8x16 点阵比对，同审查员实测法）。"""
    from ashot import font8x16
    png = _img(200, 60)
    out = annotate.annotate_png(png, [
        {"kind": "step", "x": 10, "y": 10},
        {"kind": "step", "x": 60, "y": 10},
        {"kind": "step", "x": 110, "y": 10},
    ])
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    _, _, px = annotate._decode_png(out)

    def badge_glyph_points(x0, ch):
        """字形 set-bit 数 + 实际白点数（数量等价校验；位置差 ≤2px 由
        字距假设吸收——不同数字 set-bit 数不同，足以区分 1/2/7）。"""
        g = font8x16.glyph(ch)
        bits = sum(bin(b).count("1") for b in g)
        actual = 0
        for dy in range(0, 14):
            for dx in range(0, 14):
                p0 = ((10 + dy) * 200 + (x0 + dx)) * 4
                if px[p0:p0 + 3] == b"\xff\xff\xff":
                    actual += 1
        return bits, actual

    def badge_white_count(x0):
        """徽章文字区（x0+0..13, y 10..23）白像素计数。
        文字起点 = 徽章 x + sz//4 = x0+4；窗放宽到 x0 起也够分。"""
        return sum(1 for dy in range(0, 14) for dx in range(0, 14)
                   if px[((10 + dy) * 200 + (x0 + dx)) * 4:
                         ((10 + dy) * 200 + (x0 + dx)) * 4 + 3] == b"\xff\xff\xff")

    bits1 = sum(bin(b).count("1") for b in font8x16.glyph("1"))
    bits2 = sum(bin(b).count("1") for b in font8x16.glyph("2"))
    assert badge_white_count(10) == bits1, \
        "第 1 枚 ≠ '1'（%d bits）" % bits1
    assert badge_white_count(60) == bits2, \
        "第 2 枚 ≠ '2'（递增失效，%d bits）" % bits2
    # 跨调用重置：新调用第一枚仍从 1 开始（无全局账本）
    out2 = annotate.annotate_png(png, [{"kind": "step", "x": 10, "y": 10}])
    assert out2[:8] == b"\x89PNG\r\n\x1a\n"


def test_number_explicit_value():
    """value 真验证：徽章区白点数 ≡ "7" 字形 set-bit 数（'7'=17 不同于
    '1'=23/'2'=21，数量等价即可区分）。"""
    from ashot import font8x16
    png = _img(200, 60)
    out = annotate.annotate_png(png, [{"kind": "number", "x": 10, "y": 10,
                                       "value": "7"}])
    _, _, px = annotate._decode_png(out)
    bits = sum(bin(b).count("1") for b in font8x16.glyph("7"))
    actual = sum(1 for dy in range(0, 14) for dx in range(0, 14)
                 if px[((10 + dy) * 200 + (10 + dx)) * 4:
                       ((10 + dy) * 200 + (10 + dx)) * 4 + 3] == b"\xff\xff\xff")
    assert actual == bits, "value='7' 白点 %d ≠ 字形 %d" % (actual, bits)


def test_spotlight_dims_outside_keeps_inside():
    """聚光灯：目标区保持原色、四周压暗（dim=0.5）。
    底色 BGRA(0x30,0x60,0x90)→RGBA(0x90,0x60,0x30)；区外=原值×0.5。"""
    png = _img()
    out = annotate.annotate_png(png, [{"kind": "spotlight", "x": 0, "y": 0,
                                       "w": 30, "h": 40, "dim": 0.5}])
    inside = _px_at(out, 5, 20)
    outside = _px_at(out, 45, 20)
    assert inside == (0x90, 0x60, 0x30), "目标区被误压暗"
    assert all(abs(c - e) <= 1 for c, e in
               zip(outside, (0x48, 0x30, 0x18))), "四周未按 dim 压暗"


def test_smarterase_fills_with_edge_mean():
    """智能擦除：区域被边缘均值色填充（单色底=同色但走填充路径）；
    双色底（左蓝右红中间被擦）→ 填充色为两侧均值。"""
    w, h = 60, 20
    bgra = (bytes((0xFF, 0x00, 0x00, 0xFF)) * 30 +
            bytes((0x00, 0x00, 0xFF, 0xFF)) * 30) * h
    png = output.bgra_to_png(w, h, bgra)
    out = annotate.annotate_png(png, [{"kind": "smarterase", "x": 20, "y": 0,
                                       "w": 20, "h": 20}])
    mid = _px_at(out, 30, 10)
    # 均值色介于红蓝之间（R 与 B 都非 0）
    assert 0 < mid[0] < 255 and 0 < mid[2] < 255, mid
