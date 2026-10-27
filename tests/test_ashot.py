# -*- coding: utf-8 -*-
"""Ashot v0.1.0 测试：编码器/标注原语/CLI/MCP 探针。零触网、不依赖桌面。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, output  # noqa: E402

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
    assert "0.1.0" in r.stdout


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
