# -*- coding: utf-8 -*-
"""v0.7.5 测试：stroke:false（fill-only）+ preview 白底合成。

审计 P1-1（无边柔和色块做不出来：不写 color 带默认红边、width=0 硬
报错、半透明 fill 无法配无边框）与 P1-2（preview/JPEG 把透明底压成
不透明，模型看到的与实际 PNG 不一致）。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, annotate_gdi, output, vector

BG = b"\x90\x60\x30"   # 测试画布底色（RGBA→PNG 后 RGB 序）


def _img(w=200, h=120, alpha=b"\xff"):
    """纯色画布（可指定 alpha——P1-2 透明底用例）。BGRA 每 4 字节一组。"""
    return output.bgra_to_png(w, h, (b"\x30\x60\x90" + alpha) * (w * h))


def _px(png, x, y):
    _, _, px = annotate._decode_png(png)
    i = (y * annotate._decode_png(png)[0] + x) * 4
    return (px[i], px[i + 1], px[i + 2])


# ---------- P1-1 stroke:false ----------

def test_stroke_false_vector_no_stroke_shape():
    """compile_ops：fill+stroke:false 只产 fill 形状（默认红边消失）。"""
    spec = vector.compile_ops([{"kind": "rect", "x": 10, "y": 10, "w": 50,
                                "h": 40, "fill": "#00FF00",
                                "stroke": False}])
    assert [s["t"] for s in spec["shapes"]] == ["fill"]


def test_stroke_false_pixel_no_red_edge():
    """像素路 fill-only：色块内=填充色、紧贴块外的边框带=背景色
    （旧版此处是默认红边）。"""
    png = annotate.annotate_png(
        _img(), [{"kind": "rect", "x": 20, "y": 20, "w": 60, "h": 50,
                  "fill": "#00B140", "stroke": False}])
    _, _, px = annotate._decode_png(png)

    def at(x, y):
        i = (y * 200 + x) * 4
        return (px[i], px[i + 1], px[i + 2])

    bg = (0x90, 0x60, 0x30)
    assert at(50, 45) == (0, 0xB1, 0x40), "块内非填充色：%r" % (at(50, 45),)
    # 描边若存在会以路径为中心向两侧各 ~2px：块外 17,45 / 45,17 都会染红
    assert at(17, 45) == bg and at(45, 17) == bg, \
        "fill-only 仍有默认红边：%r %r" % (at(17, 45), at(45, 17))


def test_stroke_false_gdi_edge_clean():
    """矢量路 fill-only：backend=gdi+ 且边框带无默认红（全图无红）。"""
    out, backend, _ = annotate_gdi.annotate_png_vector(
        _img(), [{"kind": "rect", "x": 20, "y": 20, "w": 60, "h": 50,
                  "fill": "#00B140", "stroke": False}])
    assert backend == "gdi+"
    _, _, px = annotate._decode_png(out)
    red = sum(1 for i in range(0, len(px), 4)
              if px[i] > 0xC0 and px[i + 1] < 0x40 and px[i + 2] < 0x40)
    assert red == 0, "fill-only 出现红色描边像素：%d" % red


def test_stroke_false_gdi_translucent_fill_no_edge():
    """审计 P1-1 的原始痛点：半透明 fill 配 stroke:false = 无边柔和
    色块（旧版做不出来——color 只收 6 位）。"""
    out, backend, _ = annotate_gdi.annotate_png_vector(
        _img(), [{"kind": "rect", "x": 20, "y": 20, "w": 60, "h": 50,
                  "fill": "#FF3B3080", "stroke": False}])
    assert backend == "gdi+"
    _, _, px = annotate._decode_png(out)
    # 中心=半透明红 over 背景 → 红通道介于背景与饱和红之间
    i = (45 * 200 + 50) * 4
    r, g = px[i], px[i + 1]
    assert 0x30 < r < 0xFF and g < 0x60, "中心混合色异常：%r" % ((r, g),)
    # 边框带无描边
    j = (45 * 200 + 17) * 4
    assert (px[j], px[j + 1], px[j + 2]) == (0x90, 0x60, 0x30)


def test_stroke_false_requires_fill():
    """stroke:false 无 fill = 静默 no-op，入口拒绝（如实亮牌）。"""
    import pytest
    for kind_ops in ({"kind": "rect", "x": 1, "y": 1, "w": 4, "h": 4,
                      "stroke": False},
                     {"kind": "line", "x1": 0, "y1": 0, "x2": 4, "y2": 4,
                      "stroke": False}):
        try:
            vector.apply_pad([kind_ops])
            raise AssertionError("未拒绝：%r" % kind_ops)
        except ValueError as e:
            assert "stroke:false" in str(e)
    # line + fill + stroke:false 也拒（line 没有 fill 能力）
    try:
        vector.apply_pad([{"kind": "line", "x1": 0, "y1": 0, "x2": 4,
                           "y2": 4, "fill": "#00FF00", "stroke": False}])
        raise AssertionError("line+fill 未被 fill 白名单拒绝")
    except ValueError:
        pass


def test_stroke_bool_only():
    """stroke 只收布尔（字符串 "false" 是 LLM 手写 JSON 常见坑）。"""
    import pytest
    with pytest.raises(ValueError):
        vector.apply_pad([{"kind": "rect", "x": 1, "y": 1, "w": 4, "h": 4,
                           "fill": "#00FF00", "stroke": "false"}])


def test_stroke_false_width_zero_ok():
    """stroke:false 时 width 无意义：width=0 不再硬报错（审计 P1-1
    原文点名的坑）。"""
    seq = vector.compile_ops([{"kind": "rect", "x": 10, "y": 10, "w": 50,
                               "h": 40, "fill": "#00FF00", "width": 0,
                               "stroke": False}])
    assert [s["t"] for s in seq["shapes"]] == ["fill"]


def test_stroke_true_explicit_unchanged():
    """stroke:true 显式 = 与缺省一致（描边照画）。"""
    from ashot import cdp as _  # noqa: F401  确保模块可导入
    spec = vector.compile_ops([{"kind": "rect", "x": 10, "y": 10, "w": 50,
                                "h": 40, "fill": "#00FF00",
                                "stroke": True}])
    assert sorted(s["t"] for s in spec["shapes"]) == ["fill", "stroke"]


# ---------- P1-2 preview 白底合成 ----------

def test_preview_jpeg_white_composite():
    """透明底 + 半透明 fill 的 PNG：预览 JPEG = source-over 白底合成
    （#FF000080 over white → (255,127,127)）；收据如实声明背景色与
    alpha 通道（结构性检查：IHDR color type 携带 alpha）。"""
    base = output.bgra_to_png(60, 40, b"\x00\x00\x00\x00" * (60 * 40))
    png = annotate.annotate_png(
        base, [{"kind": "rect", "x": 10, "y": 10, "w": 40, "h": 20,
                "fill": "#FF000080", "stroke": False}])
    jpeg, info = output.preview_jpeg(png)
    assert info["preview_alpha_channel"] is True
    assert info["preview_background"] == "white"
    # JPEG 无 alpha；半透明红 over 白 → R=255, G/B≈127（±2 容差）
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_tmp_alpha_check.jpg")
    open(tmp, "wb").write(jpeg)
    try:
        ps = (
            "Add-Type -AssemblyName System.Drawing;"
            "$b=New-Object System.Drawing.Bitmap('%s');"
            "$p=$b.GetPixel(30,20);"
            "Write-Output (\"{0},{1},{2}\" -f $p.R,$p.G,$p.B);"
            "$b.Dispose()" % tmp.replace("'", "''"))
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=30)
        line = r.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
        rr, gg, bb = (int(v) for v in line.split(","))
        assert rr == 255 and 120 <= gg <= 140 and 120 <= bb <= 140, \
            "白底合成色异常：%r" % ((rr, gg, bb),)
    finally:
        os.unlink(tmp)


def test_preview_jpeg_white_invariant():
    """白底合成是恒定规则：不透明源图同样声明（合成对不透明源无损）。"""
    png = output.bgra_to_png(60, 40, b"\x30\x60\x90\xff" * (60 * 40))
    _, info = output.preview_jpeg(png)
    assert info["preview_background"] == "white"
    assert info["preview_alpha_channel"] is True   # Ashot PNG 恒 RGBA
