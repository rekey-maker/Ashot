# -*- coding: utf-8 -*-
"""v0.4.0 裁切 / 缩放 / JPEG 交付的测试（transform + CLI + MCP 三面）。

为什么单独成文件（而不是继续堆 test_ashot.py）：新能力是独立一层的
端到端契约，和 v0.2.x 的审查回归混在一起会拖慢定位；asets 的 tmp_path
修补见 tests/conftest.py（与项目代码无关）。
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, output, transform  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 素材 ----------

def _solid(w=40, h=30):
    return output.bgra_to_png(w, h, bytes((0x30, 0x60, 0x90, 0xFF)) * (w * h))


def _two_tone(w=40, h=30):
    """左半红、右半蓝（bgra_to_png 收 BGRA：b=0,g=0,r=255 即红）。
    裁切后能按像素证明裁的是哪一半。"""
    row = bytes((0, 0, 255, 255)) * (w // 2) + bytes((255, 0, 0, 255)) * (w - w // 2)
    return output.bgra_to_png(w, h, row * h)


def _noise(w=400, h=300):
    """确定性随机噪点：PNG 压不动、JPEG 压得动，用来比体积。"""
    import random
    rnd = random.Random(7)
    bgra = bytearray()
    for _ in range(w * h):
        bgra += bytes((rnd.randrange(256), rnd.randrange(256),
                       rnd.randrange(256), 255))
    return output.bgra_to_png(w, h, bytes(bgra))


def _px(png, x, y):
    _, _, px = annotate._decode_png(png)
    w = transform.png_size(png)[0]
    i = (y * w + x) * 4
    return tuple(px[i:i + 4])


# ---------- plan_size（纯函数） ----------

def test_plan_size_rules():
    assert transform.plan_size(100, 50) == (100, 50, 1.0)
    assert transform.plan_size(100, 50, scale=2) == (200, 100, 2.0)
    assert transform.plan_size(100, 50, width=50) == (50, 25, 0.5)
    assert transform.plan_size(400, 300, max_side=100) == (100, 75, 0.25)
    # max_side 只缩不放（与 preview 同语义）
    assert transform.plan_size(40, 30, max_side=1000) == (40, 30, 1.0)
    for bad in ({"scale": 2, "width": 10},
                {"scale": 2, "max_side": 10},
                {"width": 10, "max_side": 10}):
        with pytest.raises(ValueError):
            transform.plan_size(100, 50, **bad)
    with pytest.raises(ValueError):
        transform.plan_size(100, 50, scale=-1)


# ---------- crop ----------

def test_crop_geometry_and_pixels():
    src = _two_tone()                        # 40x30，右半红
    out, info = transform.apply(src, crop=(20, 0, 20, 30))
    assert transform.png_size(out) == (20, 30)
    assert info["crop"] == [20, 0, 20, 30]
    assert info["crop_px"] == [20, 0, 40, 30]
    assert info["engine"] == "gdi+"
    assert "bounds_warn" not in info
    # 右半是蓝：(0,0,255,255)
    assert _px(out, 2, 2) == (0, 0, 255, 255)


def test_crop_full_image_is_pixel_exact():
    """裁整图（1:1）必须像素零差：GDI+ 的 DrawImage 若有半像素偏移，
    棋盘格会立刻糊掉——这条锁住「裁切不降质」。"""
    w, h = 41, 31
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            v = 255 if (x + y) % 2 == 0 else 0
            row += bytes((v, 0, 0, 255))
        rows.append(bytes(row))
    src = output.bgra_to_png(w, h, b"".join(rows))
    out, info = transform.apply(src, crop=(0, 0, w, h))
    a = annotate._decode_png(src)[2]
    b = annotate._decode_png(out)[2]
    assert a == b, "1:1 裁切出现像素差异（GDI+ 重采样偏移？）"


def test_crop_out_of_bounds_warns_and_clamps():
    src = _two_tone()
    out, info = transform.apply(src, crop=(30, 0, 20, 30))
    assert transform.png_size(out) == (10, 30), "应夹到图边，不是静默出黑图"
    assert info["bounds_warn"], "越界必须亮牌（imgtool 的静默裁切不复制）"
    assert "右边界越界 10 px" in info["bounds_warn"][0], info["bounds_warn"]


def test_crop_fully_outside_raises():
    with pytest.raises(ValueError):
        transform.apply(_two_tone(), crop=(100, 100, 10, 10))
    with pytest.raises(ValueError):
        transform.apply(_two_tone(), crop=(0, 0, 0, 10))


def test_crop_dpr_css_coords():
    """dpr=2：box 按 CSS 给的，内部乘 2（避免「CSS 当像素」静默错位）。"""
    src = _solid(100, 80)
    out, info = transform.apply(src, crop=(10, 10, 20, 20), dpr=2)
    assert transform.png_size(out) == (40, 40)
    assert info["crop"] == [20, 20, 40, 40]


def test_crop_then_scale_order():
    """先裁后缩：scale 作用在裁切后的尺寸上（收据可自证）。"""
    src = _solid(100, 80)
    out, info = transform.apply(src, crop=(0, 0, 50, 40), scale=2)
    assert transform.png_size(out) == (100, 80)
    assert info["crop"] == [0, 0, 50, 40] and info["scale"] == 2.0


# ---------- resize ----------

def test_scale_up_and_down():
    src = _solid(40, 30)
    assert transform.png_size(transform.apply(src, scale=2)[0]) == (80, 60)
    assert transform.png_size(transform.apply(src, scale=0.5)[0]) == (20, 15)


def test_max_side_passthrough_no_upscale():
    src = _solid(40, 30)
    out, info = transform.apply(src, max_side=1000)
    assert out == src, "无操作时应原样返回（像素零损失）"
    assert info["engine"] == "passthrough"


def test_size_args_are_mutually_exclusive():
    with pytest.raises(ValueError):
        transform.apply(_solid(), scale=2, width=10)


def test_dpr_without_crop_raises():
    """dpr 只在有 crop 时有意义：没裁切就没有坐标可换算（审查 P2-8）。"""
    with pytest.raises(ValueError):
        transform.apply(_solid(), dpr=2)


def test_max_side_equal_long_side_is_passthrough():
    src = _solid(40, 30)
    out, info = transform.apply(src, max_side=40)
    assert out == src and info["engine"] == "passthrough"


def test_jpeg_source_is_accepted():
    """JPEG 源也能裁：GDI+ 本来就认，旧实现只读 PNG IHDR 会报
    「不是合法的 PNG 字节」（审查 P1-3）。"""
    jpg, _ = transform.apply(_noise(120, 90), fmt="jpeg", quality=90)
    out, info = transform.apply(jpg, crop=(0, 0, 60, 45))
    assert (info["w"], info["h"]) == (60, 45)
    assert transform.png_size(out) == (60, 45)


def test_ps_failure_raises_and_never_returns_empty_bytes(monkeypatch):
    """P0 回归：PS「退出 0 但没写出文件」不能变成 0 字节交付。"""
    import subprocess as _sp

    def fake_run(*a, **k):
        return _sp.CompletedProcess(args=a[0] if a else [], returncode=0,
                                    stdout=b"", stderr=b"")

    monkeypatch.setattr(transform.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        transform.apply(_solid(40, 30), crop=(0, 0, 20, 20))


# ---------- JPEG 编码 ----------

def test_jpeg_magic_size_and_volume():
    src = _noise(400, 300)
    data, info = transform.apply(src, fmt="jpeg", quality=85)
    assert data[:2] == b"\xff\xd8", "JPEG 魔数"
    assert info["format"] == "jpeg" and info["quality"] == 85
    assert output.image_size(data) == (400, 300), "JPEG 尺寸嗅探要能进 preview"
    assert len(data) < len(src) * 0.5, "噪点图上 JPEG 应显著更小"


def test_jpeg_path_extension_implies_jpeg(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(_solid(60, 40))
    out = tmp_path / "b.jpg"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize",
                        str(src), "--scale", "1", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:2] == b"\xff\xd8"


# ---------- 缺省输出命名（Q07 同款坑：父目录带点） ----------

def test_out_path_dedup_rules(tmp_path):
    """输出路径只在一处决定（v0.4.0 收口）：目录 / 无扩展名 / 扩展名与格式不符。"""
    assert transform.out_path(None, "a/b.png", "cropped", "jpeg") == \
        "a/b_cropped.jpg"
    assert transform.out_path("x.png", "a/b.png", "cropped", "jpeg") == "x.jpg"
    assert transform.out_path("x.jpg", "a/b.png", "cropped", "png") == "x.png"
    assert transform.out_path("x.png", "a/b.png", "cropped", "png") == "x.png"
    d = tmp_path / "outdir"
    d.mkdir()
    got = transform.out_path(str(d), "a/b.png", "cropped", "jpeg")
    assert got == os.path.join(str(d), "b_cropped.jpg")


def test_default_out_dotted_dir():
    assert transform.default_out("a.dir/shot.png", "cropped") == \
        "a.dir/shot_cropped.png"
    assert transform.default_out("a.dir/shot", "cropped") == \
        "a.dir/shot_cropped.png"


# ---------- CLI ----------

def test_cli_area_accepts_comma_and_space():
    """`--area 0 0 800 600` 与 `--area 0,0,800,600` 都认（与 MCP 同款，
    别让两张脸记两套引号规则——imgtool 的 --area 文档错位就是这么来的）。"""
    from ashot import cli
    assert cli._area4(["100", "100", "800", "600"]) == (100, 100, 800, 600)
    assert cli._area4(["100,100,800,600"]) == (100, 100, 800, 600)
    assert cli._area4(None) is None
    with pytest.raises(ValueError):
        cli._area4(["1", "2", "3"])


def test_mcp_shot_scales_after_capture(tmp_path):
    """v0.4.0：**截图后直接缩放/转 JPEG**（不必再调一次 ashot_resize）。
    真实截一块 64x48 屏幕区域，再缩一半。"""
    from ashot import mcp as mcp_mod
    out = str(tmp_path / "s.png")
    rec = json.loads(mcp_mod._shot(mode="area", area=[0, 0, 64, 48],
                                   out=out, scale=0.5, preview=False))
    assert (rec["w"], rec["h"]) == (32, 24) and rec["src"] == [64, 48]
    assert transform.png_size(open(out, "rb").read()) == (32, 24)

    out2 = str(tmp_path / "s.jpg")
    rec2 = json.loads(mcp_mod._shot(mode="area", area=[0, 0, 64, 48],
                                    out=out2, max_side=32, jpg=85,
                                    preview=False))
    assert rec2["format"] == "jpeg" and rec2["path"].endswith(".jpg")
    assert (rec2["w"], rec2["h"]) == (32, 24)


def test_cli_shot_scales_and_jpeg(tmp_path):
    """CLI 面同能力：`shot area --area 0 0 64 48 --scale 0.5 --jpg 85`。"""
    out = tmp_path / "s.jpg"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "shot", "area",
                        "--area", "0", "0", "64", "48",
                        "--scale", "0.5", "--jpg", "85", "--out", str(out),
                        "--keep"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:2] == b"\xff\xd8"
    assert output.image_size(out.read_bytes()) == (32, 24)


def test_cli_crop_and_resize(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_two_tone())
    crop_out = tmp_path / "c.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "crop",
                        str(src), "--box", "20,0,20,30",
                        "--out", str(crop_out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert crop_out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "crop: x,y,w,h=20,0,20,30" in r.stderr, "收据要回显 box 语义"
    rs = tmp_path / "r.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize",
                        str(src), "--max-side", "20", "--out", str(rs)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert transform.png_size(rs.read_bytes()) == (20, 15)


def test_cli_resize_needs_a_size(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_solid())
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize", str(src)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 1 and "--scale" in r.stderr


def test_cli_annotate_jpeg_output(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_solid(200, 150))
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps([{"kind": "rect", "x": 10, "y": 10,
                                "w": 50, "h": 40, "width": 4}]), "utf-8")
    out = tmp_path / "a.jpg"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "annotate",
                        str(src), "--ops-file", str(ops), "--jpg", "80",
                        "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.read_bytes()[:2] == b"\xff\xd8"


def test_cli_compose_from_src_to_jpeg(tmp_path):
    src = tmp_path / "s.png"
    src.write_bytes(_solid(200, 150))
    out = tmp_path / "c.jpg"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "compose",
                        "--src", str(src), "--box", "0,0,100,100",
                        "--scale", "2", "--rect", "10,10,50,40",
                        "--text", "20,70:测试", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:2] == b"\xff\xd8"
    assert output.image_size(out.read_bytes()) == (200, 200), \
        "compose 应先裁(100x100)再缩(2x)再标注"


def test_cli_compose_actually_annotates(tmp_path):
    """不只验尺寸：裁+缩之后标注要真的落在像素上（去掉 annotate 这步
    就变红——否则"标注"那半段没人守）。"""
    src = tmp_path / "s.png"
    src.write_bytes(_solid(200, 150))
    out = tmp_path / "c.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "compose",
                        "--src", str(src), "--box", "0,0,100,100",
                        "--scale", "2", "--rect", "10,10,50,40",
                        "--line-width", "6", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    png = out.read_bytes()
    assert transform.png_size(png) == (200, 200)
    assert _px(png, 11, 11) == (0xFF, 0x3B, 0x30, 0xFF), "缺省红色框没画上"


# ---------- MCP ----------

def test_mcp_crop_receipt(tmp_path):
    from ashot import mcp as mcp_mod
    src = tmp_path / "s.png"
    src.write_bytes(_two_tone())
    rec = json.loads(mcp_mod._crop(str(src), "20,0,20,30", preview=False))
    assert rec["ok"] is True
    assert (rec["w"], rec["h"]) == (20, 30)
    assert rec["crop"] == [20, 0, 20, 30] and rec["crop_px"] == [20, 0, 40, 30]
    assert os.path.isfile(rec["path"])


def test_mcp_crop_bounds_warn(tmp_path):
    from ashot import mcp as mcp_mod
    src = tmp_path / "s.png"
    src.write_bytes(_two_tone())
    rec = json.loads(mcp_mod._crop(str(src), "30,0,20,30", preview=False))
    assert rec["bounds_warn"], "越界要在收据里说，不能只裁不说话"


def test_mcp_resize_jpeg_receipt(tmp_path):
    from ashot import mcp as mcp_mod
    src = tmp_path / "s.png"
    src.write_bytes(_solid(200, 150))
    rec = json.loads(mcp_mod._resize(str(src), max_side=100, jpg=80,
                                     preview=False))
    assert rec["format"] == "jpeg" and (rec["w"], rec["h"]) == (100, 75)
    assert rec["path"].endswith(".jpg") and os.path.isfile(rec["path"])


def test_mcp_preview_works_from_jpeg_output(tmp_path):
    """v0.4.0：preview_jpeg 改用 image_size 嗅探，JPEG 输出也能进缩图梯次
    （旧实现只认 PNG IHDR，JPEG 会拿不到尺寸、丢高度上限）。"""
    from ashot import mcp as mcp_mod
    src = tmp_path / "s.png"
    src.write_bytes(_solid(300, 200))
    out = mcp_mod._crop(str(src), "0,0,300,200", jpg=85, preview=True)
    assert isinstance(out, list) and len(out) == 2
    rec = json.loads(out[0]["text"])
    assert rec["format"] == "jpeg" and rec["preview"]["fit"] is True
    import base64
    assert base64.b64decode(out[1]["data"])[:2] == b"\xff\xd8"
