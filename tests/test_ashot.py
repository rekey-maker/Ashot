# -*- coding: utf-8 -*-
"""Ashot v0.1.0 测试：编码器/标注原语/CLI/MCP 探针。零触网、不依赖桌面。"""
import base64
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import __version__, annotate, output, vector  # noqa: E402

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
                       capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=ROOT)
    assert __version__ in r.stdout   # 版本烙印对：跟 __init__ 走，不硬编码


def test_cli_annotate_subcommand(tmp_path):
    png = _tiny_png()
    src = tmp_path / "in.png"
    src.write_bytes(png)
    r = subprocess.run(
        [sys.executable, "-m", "ashot.cli", "annotate", str(src),
         json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 2}]),
         "--out", str(tmp_path / "out.png")],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=ROOT)
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


# ---------- v0.1.3 二轮审查 P1 回归 ----------

def test_line_primitive_alive():
    """P1-A 回归：line 曾被 dispatch 重构漏出 xyxy 组=原语全灭。
    底色判定用 RGBA 序 b'\\x90\\x60\\x30'（BGRA 串曾判错→全图恒计数）。"""
    bg = b"\x90\x60\x30"
    png = _img(200, 100)
    out = annotate.annotate_png(png, [{"kind": "line", "x1": 5, "y1": 5,
                                       "x2": 100, "y2": 50, "width": 1}])
    _, _, px = annotate._decode_png(out)
    drawn = sum(1 for i in range(0, len(px), 4)
                if px[i:i + 3] != bg)
    assert 50 < drawn < 1000, "line 笔画异常（%d 像素）" % drawn


def test_text_has_no_disc_background():
    """P1-B 回归：text 不得带实心圆底（v0.1.2 重构残留——797 个红像素）。"""
    red = b"\xff\x3b\x30"
    png = _img(200, 100)   # 底色同前
    out = annotate.annotate_png(png, [{"kind": "text", "x": 50, "y": 30,
                                       "text": "A", "color": "#FFFFFF",
                                       "size": 16}])
    _, _, px = annotate._decode_png(out)
    reds = sum(1 for i in range(0, len(px), 4)
               if px[i:i + 3] == red)
    assert reds <= 40, "text 带实心圆盘（%d 红像素——字形本身只需 ~40）" % reds


def test_step_number_disc_drawn_once():
    """P1-B 伴随：step/number 圆底只画一次（两遍幂等但浪费）。"""
    from ashot import font8x16
    red = b"\xff\x3b\x30"
    png = _img(200, 100)
    out = annotate.annotate_png(png, [{"kind": "step", "x": 10, "y": 10,
                                       "size": 16}])
    _, _, px = annotate._decode_png(out)
    reds = sum(1 for i in range(0, len(px), 4)
               if px[i:i + 3] == red)
    assert 0 < reds < 900, "圆底缺失或异常放大（%d）" % reds


def test_unknown_kind_still_raises_cleanly():
    """未知 kind 报错文案仍含 kind 名（_NUM_KEYS 守卫接住后不许丢信息）。"""
    try:
        annotate.annotate_png(_img(), [{"kind": "nuke"}])
        raise AssertionError("未知 kind 未报错")
    except ValueError as e:
        assert "nuke" in str(e)


# ---------- v0.1.4 EnumDisplayMonitors 实装回归 ----------

def test_list_screens_returns_real_monitors():
    """v0.1.3 漏调 EnumDisplayMonitors（自调用回调=None→0×0 空屏）。
    修复后至少 1 块屏、主屏非零尺寸。"""
    from ashot import capture
    screens = capture.list_screens()
    assert len(screens) >= 1, "枚举不到显示器"
    assert all(s["w"] > 0 and s["h"] > 0 for s in screens), "存在 0×0 空屏"
    assert any(s["primary"] for s in screens), "无主屏标记"


def test_list_screens_indices_sequential():
    from ashot import capture
    screens = capture.list_screens()
    assert [s["index"] for s in screens] == list(range(len(screens)))


# ---------- v0.1.5 审查收口回归 ----------

def test_gdi_handles_no_leak():
    """P1 回归：CreateCompatibleBitmap 句柄曾每截一张漏 1 个——长驻 MCP
    进程约万张触 GDI 配额后主路永久报废。GetGuiResources 前后计数守恒。
    伴随回归：GDI 族函数曾挂 user32（无导出）→ 主路从未跑通、每次静默
    降级 PS 兜底；此测试跑真主路即锁死该回归。"""
    import ctypes
    from ashot import capture
    proc = ctypes.windll.kernel32.GetCurrentProcess()
    u32 = ctypes.windll.user32   # GetGuiResources 在 user32（非 kernel32）
    before = u32.GetGuiResources(proc, 0)   # 0 = GR_GDIOBJECTS
    for _ in range(5):
        w, h, bgra = capture._shot_gdi((0, 0, 32, 32))
        assert (w, h) == (32, 32) and len(bgra) == w * h * 4
        assert all(bgra[3::4]), "alpha 未强制不透明（BI_RGB alpha 未定义透传）"
    after = u32.GetGuiResources(proc, 0)
    assert after == before, "GDI 句柄泄漏：%d -> %d" % (before, after)


def test_decode_rejects_interlaced_png():
    """P2 回归：interlace=1 曾被按逐行扫描线硬解 Adam7 数据 → 静默花图。
    契约是「其他形态如实报错」。"""
    import struct as _s
    import zlib as _z

    def chunk(tag, data):
        c = tag + data
        return _s.pack(">I", len(data)) + c + _s.pack(">I", _z.crc32(c))

    ihdr = _s.pack(">IIBBBBB", 4, 2, 8, 6, 0, 0, 1)   # 末位 interlace=1
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", _z.compress(b"\x00" * 40)) + chunk(b"IEND", b""))
    try:
        annotate._decode_png(png)
        raise AssertionError("interlaced PNG 竟被接受")
    except ValueError as e:
        assert "隔行" in str(e) or "interlac" in str(e).lower()


def test_smarterase_outside_image_raises_clean():
    """P3 回归：区域完全在图外曾 IndexError（clamp 出负宽高后环采样越界）
    或静默错采——现在干净报错。"""
    try:
        annotate.annotate_png(_img(10, 10), [{"kind": "smarterase",
                                              "x": 15, "y": 9, "w": 4, "h": 4}])
        raise AssertionError("图外 smarterase 竟被接受")
    except ValueError as e:
        assert "图外" in str(e)


def test_spotlight_outside_image_raises_clean():
    try:
        annotate.annotate_png(_img(10, 10), [{"kind": "spotlight",
                                              "x": 20, "y": 0, "w": 4, "h": 4}])
        raise AssertionError("图外 spotlight 竟被接受")
    except ValueError as e:
        assert "图外" in str(e)


def test_save_into_directory(tmp_path):
    """P2 回归：out=目录时文件必须落在该目录内（旧实现无视传入目录、
    悄悄落到缺省目录）。"""
    p = output.save(_tiny_png(), out=str(tmp_path))
    assert os.path.dirname(p) == str(tmp_path) and os.path.isfile(p)


def test_save_extless_path_treated_as_dir(tmp_path):
    d = tmp_path / "shots"
    p = output.save(_tiny_png(), out=str(d))
    assert os.path.dirname(p) == str(d) and os.path.isfile(p)


def test_default_name_nanosecond_suffix():
    """P2 回归：缺省名纯秒级时间戳，同秒连截两张同名静默覆盖——纳秒尾数防撞。"""
    a, b = output._default_name(), output._default_name()
    assert a != b, "同秒两次缺省命名撞名（尾数失效）"


def test_gc_fresh_files_exempt_even_zero_days(tmp_path):
    """P3 回归：retention_days=0 时 cutoff=now，mtime 同秒的刚存图曾被时钟
    粒度误删——120 秒内新图一律豁免。"""
    f = tmp_path / "shot_fresh.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    n, _ = output.gc(retention_days=0, directory=str(tmp_path))
    assert n == 0 and f.exists()


def test_mcp_survives_non_object_frame():
    """P2 回归：合法 JSON 非对象帧（如数组）曾 AttributeError 杀死服务
    进程——现在回 -32600 且进程继续服务后续请求。"""
    payload = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {}}),
        "[1, 2, 3]",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "ashot_screens", "arguments": {}}}),
    ]) + "\n"
    r = subprocess.run([sys.executable, "ashot_mcp.py"], input=payload,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.strip().splitlines()]
    assert lines[1]["error"]["code"] == -32600, lines[1]
    assert lines[2]["id"] == 2
    assert "screens" in lines[2]["result"]["content"][0]["text"]


def test_mcp_annotate_does_not_overwrite_source(tmp_path):
    """P1 回归：MCP annotate 缺省曾静默覆盖原图——现写 *_annotated.png。"""
    from ashot import mcp as mcp_mod
    src = tmp_path / "in.png"
    original = _tiny_png()
    src.write_bytes(original)
    res = json.loads(mcp_mod._annotate(
        str(src), json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 2, "h": 2}]),
        preview=False))
    assert res["ok"] and res["path"] != str(src)
    assert src.read_bytes() == original, "原件被覆盖"
    assert os.path.basename(res["path"]).endswith("_annotated.png")
    assert os.path.isfile(res["path"])


def test_mcp_tool_schemas():
    """P3 死代码清理后 schema 生成仍自洽：required 推导 + 属性集合。"""
    from ashot import mcp as mcp_mod
    assert set(mcp_mod.TOOLS) == {"ashot_shot", "ashot_screens",
                                  "ashot_annotate", "ashot_fonts",
                                  "ashot_show", "ashot_hash", "ashot_diff",
                                  "ashot_element", "ashot_frames",
                                  "ashot_frame_element", "ashot_snapshot",
                                  "ashot_cdp_tabs",
                                  "ashot_cdp_shot", "ashot_cdp_key",
                                  "ashot_cdp_wheel", "ashot_cdp_click",
                                  "ashot_cdp_drag", "ashot_cdp_dblclick",
                                  "ashot_cdp_type", "ashot_cdp_view",
                                  "ashot_cdp_eval", "ashot_crop",
                                  "ashot_resize"}
    for nm, props in (
            ("ashot_cdp_click", {"x", "y", "button", "human", "seed", "activate",
                         "url_sub",
                                 "port", "index", "ws", "timing",
                                 "verify", "from_x", "from_y"}),
            ("ashot_cdp_drag", {"x1", "y1", "x2", "y2", "steps", "button",
                                "human", "seed", "port", "index", "ws",
                                "pace", "total_ms", "constrained",
                                "max_perp", "timing", "verify", "activate",
                                "url_sub"}),
            ("ashot_cdp_dblclick", {"x", "y", "button", "count", "human",
                                    "seed", "port", "index", "ws",
                                    "from_x", "from_y", "activate",
                                    "url_sub"})):
        assert set(mcp_mod.TOOLS[nm]["inputSchema"]["properties"]) == props, nm
    sc = mcp_mod.TOOLS["ashot_annotate"]["inputSchema"]
    assert sc["required"] == ["image", "ops"]
    assert set(sc["properties"]) == {"image", "ops", "out", "preview",
                                     "jpg", "quality", "max_side", "dpr",
                                     "port", "index", "ws", "space", "url_sub"}
    assert sc["properties"]["dpr"]["type"] == "number", \
        "v0.5.1：dpr 典型值 1.25/1.566，声明 integer 会让宿主拒参"
    assert "dpr" in mcp_mod.TOOLS["ashot_annotate"]["description"], \
        "工具描述必须提到 dpr，否则模型只能猜"
    assert sc["properties"]["preview"]["type"] == "boolean", \
        "v0.2.6 Q13：有 bool 缺省的参数应声明为 boolean"
    # v0.4.0：裁切/缩放两工具（与 CLI 同能力），dpr 必须是 number 不是 integer
    cr = mcp_mod.TOOLS["ashot_crop"]["inputSchema"]
    assert cr["required"] == ["image", "box"], cr["required"]
    assert set(cr["properties"]) == {"image", "box", "out", "scale", "width",
                                     "max_side", "jpg", "quality", "dpr",
                                     "preview"}
    assert cr["properties"]["dpr"]["type"] == "number"
    assert cr["properties"]["scale"]["type"] == "number", \
        "scale 是倍率（1.2/0.5），声明成 integer 会让宿主校验把小数挡掉"
    assert cr["properties"]["box"]["type"] == "string"
    rz = mcp_mod.TOOLS["ashot_resize"]["inputSchema"]
    assert rz["required"] == ["image"]
    assert set(rz["properties"]) == {"image", "out", "scale", "width",
                                     "max_side", "jpg", "quality", "preview"}
    ss = mcp_mod.TOOLS["ashot_shot"]["inputSchema"]
    assert set(ss["properties"]) == {"mode", "screen", "out", "clip",
                                     "keep", "area", "retention_days",
                                     "preview", "scale", "max_side",
                                     "jpg", "quality"}
    assert ss["properties"]["scale"]["type"] == "number"
    assert ss["properties"]["preview"]["type"] == "boolean"
    assert ss["properties"]["clip"]["type"] == "boolean"
    # 无缺省值的参数仍按 string 声明（工具内自转型）
    assert ss["properties"]["mode"]["type"] == "string"
    fc = mcp_mod.TOOLS["ashot_fonts"]["inputSchema"]
    assert fc["required"] == []
    assert set(fc["properties"]) == {"filter", "refresh"}
    wc = mcp_mod.TOOLS["ashot_show"]["inputSchema"]
    assert wc["required"] == ["image", "title", "out_dir"]
    assert set(wc["properties"]) == {"image", "title", "out_dir",
                                     "caption", "width"}
    ct = mcp_mod.TOOLS["ashot_cdp_tabs"]["inputSchema"]
    assert ct["required"] == []
    assert set(ct["properties"]) == {"port", "url_sub"}
    cs = mcp_mod.TOOLS["ashot_cdp_shot"]["inputSchema"]
    assert cs["required"] == []
    assert set(cs["properties"]) == {"port", "index", "fullpage", "out",
                                     "stitch", "preview", "activate",
                                     "url_sub"}
    db = mcp_mod.TOOLS["ashot_cdp_dblclick"]["inputSchema"]
    assert db["required"] == ["x", "y"]
    assert set(db["properties"]) == {"x", "y", "button", "count", "human",
                                     "seed", "port", "index", "ws",
                                     "from_x", "from_y", "activate",
                                     "url_sub"}
    assert db["properties"]["from_x"]["type"] == "integer", \
        "坐标参数默认 None 也应按语义声明 integer（v0.2.6 审计）"
    assert mcp_mod.TOOLS["ashot_cdp_click"]["inputSchema"]["properties"][
        "x"]["type"] == "integer"
    tp = mcp_mod.TOOLS["ashot_cdp_type"]["inputSchema"]
    assert tp["required"] == ["text"]
    assert set(tp["properties"]) == {"text", "x", "y", "port", "index",
                                     "ws", "verify", "activate", "url_sub"}
    hh = mcp_mod.TOOLS["ashot_hash"]["inputSchema"]
    assert hh["required"] == ["image"]
    assert set(hh["properties"]) == {"image", "algo"}
    dd = mcp_mod.TOOLS["ashot_diff"]["inputSchema"]
    assert dd["required"] == ["a", "b"]
    assert set(dd["properties"]) == {"a", "b", "threshold", "out"}
    assert dd["properties"]["threshold"]["type"] == "number"
    el = mcp_mod.TOOLS["ashot_element"]["inputSchema"]
    assert el["required"] == ["selector"]
    assert set(el["properties"]) == {"selector", "port", "index", "ws",
                                     "scroll", "url_sub"}
    assert el["properties"]["scroll"]["type"] == "boolean"
    fe2 = mcp_mod.TOOLS["ashot_frame_element"]["inputSchema"]
    assert fe2["required"] == ["iframe", "selector"]
    assert set(fe2["properties"]) == {"iframe", "selector", "port", "index",
                                     "ws", "url_sub"}
    fr2 = mcp_mod.TOOLS["ashot_frames"]["inputSchema"]
    assert set(fr2["properties"]) == {"port", "index", "ws", "url_sub"}
    for nm, req, props in (
            ("ashot_cdp_key", ["key"],
             {"key", "text", "modifiers", "port", "index", "ws", "url_sub"}),
            ("ashot_cdp_wheel", [],
             {"dx", "dy", "x", "y", "port", "index", "ws", "url_sub"}),
            ("ashot_cdp_click", ["x", "y"],
             {"x", "y", "button", "human", "seed", "port", "index", "ws",
              "timing", "verify", "from_x", "from_y", "activate", "url_sub"}),
            ("ashot_cdp_drag", ["x1", "y1", "x2", "y2"],
             {"x1", "y1", "x2", "y2", "steps", "button", "human", "seed",
              "port", "index", "ws", "pace", "total_ms", "constrained",
              "max_perp", "timing", "verify", "activate", "url_sub"})):
        ic = mcp_mod.TOOLS[nm]["inputSchema"]
        assert ic["required"] == req, (nm, ic["required"])
        assert set(ic["properties"]) == props, nm


# ---------- v0.1.6 渐变实心箭头 + 圆角矩形 ----------
# （v0.1.8 注：_ink 墨量比较随几何重校准退役——杆恒定后墨量不再是
#   fat/line 的判别特征，改用头底边柱状连通段，见 _col_run）


def test_fat_arrow_head_vs_line_shaft():
    """v0.1.8 重校准后缺省箭头不再靠墨量区分（杆已恒定=width）：
    判别特征=实心三角头——头底边柱状连通墨远高于 style=line 同列
    （line 该处只有细杆+两翼断段）。"""
    png = _img(300, 120)
    fat = annotate.annotate_png(png, [{"kind": "arrow", "x1": 20, "y1": 60,
                                       "x2": 260, "y2": 60, "width": 6,
                                       "color": "#FF0000"}])
    thin = annotate.annotate_png(png, [{"kind": "arrow", "x1": 20, "y1": 60,
                                        "x2": 260, "y2": 60, "width": 6,
                                        "style": "line",
                                        "color": "#FF0000"}])
    # 头底边在 x = 260 - 3.5*6 = 239；取 x=241（距 tip 19，三角全宽 19）
    assert _col_run(fat, 241) >= 15, _col_run(fat, 241)
    assert _col_run(thin, 241) <= 11, _col_run(thin, 241)


def _col_run(png, x):
    """x 列上同色（红）像素的最大竖向连通段长度。"""
    _, _, px = annotate._decode_png(png)
    best = run = 0
    for y in range(120):
        i = (y * 300 + x) * 4
        if px[i] > 0xC0 and px[i + 1] < 0x40:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def test_fat_arrow_solid_head_tip():
    """三角头尖端 (x2,y2) 附近必须实心（渐变箭头的头是实心三角）。
    窗口按 v0.1.8 几何算：距 tip d 处三角全宽 = d（1:1 头）。"""
    png = _img(300, 120)
    out = annotate.annotate_png(png, [{"kind": "arrow", "x1": 20, "y1": 60,
                                       "x2": 260, "y2": 60, "width": 6,
                                       "color": "#FF0000"}])
    _, _, px = annotate._decode_png(out)
    red = 0
    for dy in range(-5, 6):
        for dx in range(-6, 1):
            i = ((60 + dy) * 300 + (260 + dx)) * 4
            if px[i] > 0xC0 and px[i + 1] < 0x40:
                red += 1
    assert red >= 20, "头尖端不实心（%d 红像素）" % red


def test_fat_arrow_geometry_ratios():
    """v0.1.8 几何锁：头宽==头长（1:1）；杆峰值半径≤0.5×width（零膨胀）；
    短箭头长封顶 0.4×全长。"""
    from ashot import vector
    w = 8
    poly = vector._fat_arrow_poly(0, 0, 200, 0, w)
    assert max(p[0] for p in poly) == 200, "tip 缺失"
    base = [p for p in poly if abs(p[0] - (200 - 3.5 * w)) < 0.01]
    half_w = max(abs(p[1]) for p in base)
    assert abs(half_w - 3.5 * w / 2) < 0.05, "头宽≠头长（半宽 %r）" % half_w
    shaft_ys = [abs(p[1]) for p in poly if p[0] < 200 - 3.5 * w - 0.01]
    assert max(shaft_ys) <= w * 0.5 + 0.01, \
        "杆膨胀超名义宽：%r" % max(shaft_ys)
    # 短箭：基准头长 28 > 0.4×60=24 → 头长取 24，头底半宽=12
    poly2 = vector._fat_arrow_poly(0, 0, 60, 0, w)
    base2 = [p for p in poly2 if abs(p[0] - (60 - 24)) < 0.51]
    half_w2 = max(abs(p[1]) for p in base2)
    assert abs(half_w2 - 12) < 0.6, "短箭封顶未生效（半宽 %r）" % half_w2
    # 极短箭域：dist=30 < 2.5×18 → 封顶头长 12，头底半宽钳到 ≥0.5×width=9
    poly3 = vector._fat_arrow_poly(0, 0, 30, 0, 18)
    base3 = [p for p in poly3 if abs(p[0] - (30 - 12)) < 0.51]
    half_w3 = max(abs(p[1]) for p in base3)
    assert half_w3 >= 9 - 0.01, "头底窄于杆端（凹肩回归）：%r" % half_w3


def test_fat_arrow_poly_simple_and_closed():
    """多边形简单性锁（§7.7.6）：长箭/封顶短箭/斜箭三形态无自交
    （相邻段共享端点除外）、有向面积恒正（闭合且非退化）。"""
    from ashot import vector

    def segments(poly):
        return [(poly[i], poly[(i + 1) % len(poly)])
                for i in range(len(poly))]

    def proper_crossing_count(poly):
        segs = segments(poly)
        EPS = 1e-9

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - \
                   (a[1] - o[1]) * (b[0] - o[0])

        def sgn(v):
            return 1 if v > EPS else (-1 if v < -EPS else 0)
        n = 0
        for i in range(len(segs)):
            for j in range(i + 2, len(segs)):
                if i == 0 and j == len(segs) - 1:
                    continue   # 首尾段共享 poly[0] 端点，非真自交
                (p1, p2), (p3, p4) = segs[i], segs[j]
                s1 = sgn(cross(p3, p4, p1)) * sgn(cross(p3, p4, p2))
                s2 = sgn(cross(p1, p2, p3)) * sgn(cross(p1, p2, p4))
                if s1 < 0 and s2 < 0:
                    n += 1
            return n

    def area2(poly):
        s = 0.0
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            s += x1 * y2 - x2 * y1
        return s

    for x2, y2, w in ((60, 0, 8), (30, 0, 18), (50, 80, 10)):
        poly = vector._fat_arrow_poly(0, 0, x2, y2, w)
        assert proper_crossing_count(poly) == 0, \
            "多边形自交 (%d,%d,w=%d)：%d 处" % (x2, y2, w,
                                              proper_crossing_count(poly))
        assert abs(area2(poly)) > 1.0, "多边形退化 (%d,%d,w=%d)" % (x2, y2, w)


def test_pixel_only_ops_backend_pixel():
    """收据契约另一半（§7.7.6）：纯像素 ops 无矢量形状 → backend=pixel
    （A 方案后这是 pixel 的唯一「非降级」合法场景），pixel_ops 计数正确。"""
    from ashot import annotate_gdi
    out, backend, pixel_n = annotate_gdi.annotate_png_vector(
        _img(120, 120),
        [{"kind": "mosaic", "x": 20, "y": 20, "w": 40, "h": 40,
          "block": 8}])
    assert backend == "pixel", backend
    assert pixel_n == 1, pixel_n


def test_fat_arrow_pixel_geometry():
    """像素版几何探针锁（防与矢量版漂移，审计 P3-5）：width=8 长箭
    杆区最大半宽==4（零膨胀）；头底边柱宽≈头长 28。"""
    png = _img(300, 120)
    out = annotate.annotate_png(png, [{"kind": "arrow", "x1": 20, "y1": 60,
                                       "x2": 260, "y2": 60, "width": 8,
                                       "color": "#FF0000"}])
    _, _, px = annotate._decode_png(out)

    def col_extent(x):
        ys = [y for y in range(120)
              if px[(y * 300 + x) * 4] > 0xC0
              and px[(y * 300 + x) * 4 + 1] < 0x40]
        return (max(ys) - min(ys) + 1) if ys else 0

    shaft_peak = max(col_extent(x) for x in range(40, 200))
    assert shaft_peak <= 2 * (8 * 0.5) + 2, \
        "像素版杆膨胀（%d）——与矢量版漂移" % shaft_peak
    head_base = col_extent(233)   # 距 tip 27，1:1 头全宽≈27+盘缘
    assert 22 <= head_base <= 32, \
        "像素版头宽漂移（%d，期望≈28）" % head_base


def test_rounded_rect_corners_open():
    """radius>0：四角留空（无笔画）、边中段有笔画。"""
    png = _img(200, 120)
    out = annotate.annotate_png(png, [{"kind": "rect", "x": 20, "y": 20,
                                       "w": 160, "h": 80, "width": 3,
                                       "radius": 14}])
    _, _, px = annotate._decode_png(out)
    bg = (0x90, 0x60, 0x30)

    def at(x, y):
        i = (y * 200 + x) * 4
        return (px[i], px[i + 1], px[i + 2])

    corners = [(20, 20), (179, 20), (20, 99), (179, 99)]
    assert all(at(*c) == bg for c in corners), "圆角矩形角点未留空"
    assert at(100, 20) != bg and at(20, 60) != bg, "边中段笔画缺失"


def test_rounded_rect_zero_radius_is_plain():
    """radius 缺省 0 = 原直角行为不变（向后兼容）。"""
    png = _img(200, 120)
    out = annotate.annotate_png(png, [{"kind": "rect", "x": 20, "y": 20,
                                       "w": 160, "h": 80, "width": 3}])
    _, _, px = annotate._decode_png(out)
    i = (20 * 200 + 20) * 4
    assert (px[i], px[i + 1], px[i + 2]) != (0x90, 0x60, 0x30), \
        "radius=0 直角矩形角点竟无笔画"


# ---------- v0.1.7 矢量标注（GDI+ 抗锯齿） ----------

def test_vector_compile_fat_arrow_poly_closed():
    """几何编译：fat arrow 多边形闭合且点数充足；未知 kind/坏 hex 抛错。"""
    from ashot import vector
    poly = vector._fat_arrow_poly(20, 60, 260, 60, 6)
    assert len(poly) > 60, "多边形点数过少：%d" % len(poly)
    # v0.1.8 圆尾弧向修正后弧末点（a=0）恰为 poly[0]——显式零长闭合
    assert poly[-1] == poly[0]
    try:
        vector.compile_ops([{"kind": "nuke"}])
        raise AssertionError("未知 kind 未抛错")
    except ValueError:
        pass
    try:
        vector.compile_ops([{"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 4,
                             "color": "#ZZZZZZ"}])
        raise AssertionError("坏 hex 未抛错")
    except ValueError:
        pass


def test_vector_compile_pixel_ops_separated():
    """像素操作与矢量形状分流：mosaic/blur/spotlight/smarterase 不进 shapes。"""
    from ashot import vector
    spec = vector.compile_ops([
        {"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 4},
        {"kind": "mosaic", "x": 0, "y": 0, "w": 4, "h": 4},
        {"kind": "smarterase", "x": 0, "y": 0, "w": 4, "h": 4},
    ])
    assert len(spec["shapes"]) == 1 and len(spec["pixel_ops"]) == 2


def test_gdi_vector_backend_and_antialiasing():
    """端到端：GDI+ 矢量路 backend=gdi+，笔画边缘存在抗锯齿中间色
    （纯像素画布是硬边——中间色像素数为 0，这是两种后端的分水岭）。"""
    from ashot import annotate_gdi
    out, backend, pixel_n = annotate_gdi.annotate_png_vector(
        _img(300, 120),
        [{"kind": "rect", "x": 50, "y": 30, "w": 200, "h": 60,
          "width": 6, "color": "#FF0000"}])
    assert backend == "gdi+", backend
    assert pixel_n == 0, pixel_n
    _, _, px = annotate._decode_png(out)
    mid = sum(1 for i in range(0, len(px), 4)
              if 0 < abs(px[i] - 0x90) < 0xC0
              and px[i + 1] < 0x90)   # 红与底色(0x90,0x60,0x30)的混合过渡
    assert mid > 20, "描边边缘无抗锯齿中间色（%d）——像硬边像素版" % mid


def test_gdi_vector_mixed_ops_backend_gdiplus():
    """混合 ops（v0.1.8 A 方案）：GDI+ 形状渲染成功时 backend=gdi+（不再
    谎报 pixel），收据 pixel_ops=像素操作数；像素操作仍真实生效
    （spotlight：区内保持原色、区外压暗——像素 ops 恒最后叠加）。"""
    from ashot import annotate_gdi
    out, backend, pixel_n = annotate_gdi.annotate_png_vector(
        _img(300, 120),
        [{"kind": "rect", "x": 10, "y": 10, "w": 50, "h": 50, "width": 3},
         {"kind": "spotlight", "x": 100, "y": 20, "w": 60, "h": 60,
          "dim": 0.5}])
    assert backend == "gdi+", backend
    assert pixel_n == 1, pixel_n
    inside = _px_at(out, 130, 50)
    outside = _px_at(out, 250, 50)
    assert inside == (0x90, 0x60, 0x30), "区内被误压暗：%r" % (inside,)
    assert all(c < e for c, e in zip(outside, (0x90, 0x60, 0x30))), \
        "区外未压暗：%r" % (outside,)


def test_gdi_vector_chinese_text():
    """GDI+ DrawString 系统字体：中文 text 不再降级占位框——输出可解
    且文字区出现非底色笔画。"""
    from ashot import annotate_gdi
    out, backend, pixel_n = annotate_gdi.annotate_png_vector(
        _img(400, 120),
        [{"kind": "text", "x": 20, "y": 40, "text": "中文标注测试",
          "size": 28, "color": "#FFFFFF"}])
    assert backend == "gdi+", backend
    assert pixel_n == 0, pixel_n
    _, _, px = annotate._decode_png(out)
    white = sum(1 for i in range(0, len(px), 4)
                if px[i] > 0xD0 and px[i + 1] > 0xD0 and px[i + 2] > 0xD0)
    assert white > 100, "中文文字未渲染出笔画（%d 白像素）" % white


# ---------- v0.1.9 文字字体设置 ----------

def test_text_font_and_bold_compile():
    """compile：font/bold 透传进 text shape；缺省=微软雅黑 + 粗体。"""
    from ashot import vector
    dflt = vector.compile_ops([{"kind": "text", "x": 0, "y": 0,
                                "text": "hi"}])["shapes"][0]
    assert dflt["font"] == "Microsoft YaHei UI", dflt["font"]
    assert dflt["bold"] is True
    custom = vector.compile_ops([{"kind": "text", "x": 0, "y": 0,
                                  "text": "hi", "font": "Consolas",
                                  "bold": False}])["shapes"][0]
    assert custom["font"] == "Consolas" and custom["bold"] is False


def test_text_font_render_smoke():
    """渲染冒烟：指定字体正常出墨；未安装字体名静默回退不崩（§7.8.2）。"""
    from ashot import annotate_gdi
    for font in ("Times New Roman", "NoSuchFontXYZ"):
        out, backend, pixel_n = annotate_gdi.annotate_png_vector(
            _img(400, 120),
            [{"kind": "text", "x": 20, "y": 30, "text": "Font Test 测试",
              "size": 36, "color": "#FFFFFF", "font": font}])
        assert backend == "gdi+", (font, backend)
        assert pixel_n == 0
        _, _, px = annotate._decode_png(out)
        white = sum(1 for i in range(0, len(px), 4)
                    if px[i] > 0xD0 and px[i + 1] > 0xD0
                    and px[i + 2] > 0xD0)
        assert white > 50, "font=%s 文字未出墨（%d 白像素）" % (font, white)


def test_text_font_pixel_path_ignores():
    """像素降级路向后兼容：text op 携带 font/bold 字段不炸（被忽略），
    ASCII 仍走 8×16 点阵。"""
    out = annotate.annotate_png(_img(200, 80),
                                [{"kind": "text", "x": 20, "y": 20,
                                  "text": "pixel", "size": 16,
                                  "color": "#FFFFFF",
                                  "font": "Times New Roman",
                                  "bold": False}])
    _, _, px = annotate._decode_png(out)
    white = sum(1 for i in range(0, len(px), 4)
                if px[i] > 0xD0 and px[i + 1] > 0xD0 and px[i + 2] > 0xD0)
    assert white > 10, "像素路 ASCII 文字未出墨（%d）" % white


# ---------- v0.1.10 字库查询 ----------

def test_fonts_list_and_filter():
    """字库查询：列表非空且含渲染器缺省族、已排序；过滤不区分大小写
    （数据源与渲染器同源，§7.9.2）。

    v0.2.6（Q19）：本地名命中是**条件承诺**——实测部分机器（含本机）
    .NET 的 FontFamily.Name 也只回英文名（KaiTi 的本地名就是 "KaiTi"），
    此时"楷体"过滤必然为空，属 OS 数据边界而非过滤器缺陷。测试按
    实际数据判：只要存在本地名与英文名不同的族，就必须双命中。"""
    from ashot import fonts
    names = fonts.list_families(refresh=True)
    assert len(names) > 10, len(names)
    assert names == sorted(names), "未排序"
    assert len(set(names)) == len(names), "存在重复族名"
    assert not names[0].startswith("\ufeff"), "首元素带 BOM"
    assert "Microsoft YaHei UI" in names, "渲染器缺省族不在字库"
    hits = fonts.list_families("kai")
    assert "KaiTi" in hits, hits
    assert all("kai" in n.lower() for n in hits)
    assert fonts.list_families("NoSuchFontZZZ") == []
    aliased = [(en, loc) for en, loc in fonts._CACHE if en.lower() != loc.lower()]
    if aliased:
        en, loc = aliased[0]
        assert en in fonts.list_families(loc), \
            "OS 提供了本地名 %r，但本地名过滤没命中 %r" % (loc, en)
    else:
        # 数据边界：本机没有本地化别名，"楷体"查不到是预期行为
        assert fonts.list_families("楷体") == []


def test_fonts_cache_invalidation(monkeypatch):
    """v0.2.6 Q11：字库缓存可失效——常驻进程装了新字体不必重启。"""
    from ashot import fonts
    calls = {"n": 0}
    real = fonts.subprocess.run

    def fake_run(*a, **k):
        calls["n"] += 1
        class R:
            returncode = 0
            stdout = b"FakeFam\tFakeFam\n"
            stderr = b""
        return R()

    monkeypatch.setattr(fonts.subprocess, "run", fake_run)
    try:
        fonts.clear_cache()
        assert fonts.list_families() == ["FakeFam"]
        assert calls["n"] == 1
        fonts.list_families()          # 缓存命中：不再枚举
        assert calls["n"] == 1
        fonts.list_families(refresh=True)   # 强制刷新：再枚举
        assert calls["n"] == 2
        fonts.clear_cache()
        fonts.list_families()
        assert calls["n"] == 3
    finally:
        monkeypatch.setattr(fonts.subprocess, "run", real)
        fonts.clear_cache()


def test_fonts_cli_subcommand():
    """CLI fonts 子命令子进程实跑：过滤命中 + 计数走 stderr。"""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "fonts", "kai"],
                       capture_output=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = r.stdout.decode("utf-8", "replace")
    assert "KaiTi" in out, out
    assert "total: " in r.stderr.decode("utf-8", "replace")


# ---------- v0.1.11 preview 图片收据（MCP ImageContent 实验） ----------

def _jpeg_magic(data):
    return data[:2] == b"\xff\xd8"


def test_shot_preview_compat_and_blocks(tmp_path):
    """preview 缺省=true（v0.2.6 Q16）→ 两内容块；=false 退回单字符串
    （兼容旧调用方，省上下文/省一次缩图进程）。"""
    from ashot import mcp as mcp_mod
    out_png = str(tmp_path / "s.png")
    blocks = mcp_mod._shot(mode="area", area=[0, 0, 64, 48], out=out_png)
    assert isinstance(blocks, list) and len(blocks) == 2, "缺省应带缩图"
    receipt = json.loads(blocks[0]["text"])
    assert receipt["ok"] and receipt["preview"]["fit"] is True
    assert receipt["box_source"] == "area"

    old = mcp_mod._shot(mode="area", area=[0, 0, 64, 48],
                        out=str(tmp_path / "s0.png"), preview=False)
    assert isinstance(old, str) and json.loads(old)["ok"]

    blocks = mcp_mod._shot(mode="area", area=[0, 0, 64, 48],
                           out=str(tmp_path / "s2.png"), preview=True)
    assert isinstance(blocks, list) and len(blocks) == 2
    receipt = json.loads(blocks[0]["text"])
    assert receipt["ok"] and receipt["preview"]["fit"] is True
    assert blocks[1]["type"] == "image"
    assert blocks[1]["mimeType"] == "image/jpeg"
    assert blocks[1]["annotations"]["audience"] == ["user"]
    assert blocks[1]["annotations"]["priority"] == 0.9
    jpeg = base64.b64decode(blocks[1]["data"])
    assert _jpeg_magic(jpeg), "缩图不是 JPEG"


def test_annotate_preview_blocks(tmp_path):
    """annotate preview=true：同样升级两内容块，缩图来自标注成品。
    v0.2.6 起缺省即 true。"""
    from ashot import mcp as mcp_mod
    src = tmp_path / "in.png"
    src.write_bytes(_tiny_png())
    blocks = mcp_mod._annotate(
        str(src), json.dumps([{"kind": "rect", "x": 0, "y": 0,
                               "w": 2, "h": 2}]), preview=True)
    assert isinstance(blocks, list) and len(blocks) == 2
    receipt = json.loads(blocks[0]["text"])
    assert receipt["ok"] and receipt["backend"] == "gdi+"
    assert blocks[1]["type"] == "image"
    assert _jpeg_magic(base64.b64decode(blocks[1]["data"]))
    # 防 mutant：缩图必须来自标注成品而非源图（魔数区分不了，字节比较）
    src_jpeg, _ = output.preview_jpeg(_tiny_png())
    assert blocks[1]["data"] != base64.b64encode(src_jpeg).decode(), \
        "缩图竟是源图而非标注成品"
    # 缺省（不传 preview）同样带图
    assert isinstance(mcp_mod._annotate(
        str(src), json.dumps([{"kind": "rect", "x": 0, "y": 0,
                               "w": 2, "h": 2}])), list)


def test_preview_jpeg_no_upscale_and_ladder():
    """缩图规格：不放大（4×2 源宽保持 4）；正常图落 1200px 档且 fit；
    上限压到极小时梯次到底、如实报 fit=False 不假装。"""
    from ashot import output
    jpeg, info = output.preview_jpeg(_tiny_png())
    assert _jpeg_magic(jpeg) and info["width"] == 4, info
    big = output.bgra_to_png(2000, 1500, b"\x30\x60\x90\xff" * (2000 * 1500))
    jpeg, info = output.preview_jpeg(big)
    assert info["width"] == 1200 and info["fit"] is True, info
    jpeg, info = output.preview_jpeg(big, max_bytes=500)
    assert info["width"] == 600 and info["fit"] is False, info
    assert len(jpeg) == info["bytes"]


# ---------- v0.1.12 show 用户可见展示 ----------

def test_show_build_html(tmp_path):
    """show：数据 URL 内嵌落盘、标题规范化、不放大、caption 缺省。"""
    from ashot import show as show_mod
    img = tmp_path / "cam Case!.png"
    img.write_bytes(_tiny_png())
    res = show_mod.build_html(str(img), "My Title! 42", str(tmp_path))
    assert res["ok"] and res["title"] == "my-title-42"
    assert os.path.isfile(res["html"])
    html_text = open(res["html"], encoding="utf-8").read()
    assert "data:image/jpeg;base64," in html_text
    assert "cam Case!.png" in html_text   # caption 缺省=文件名（escaped）
    assert res["preview"]["width"] == 4   # 不放大
    assert html_text.index("data:image/jpeg") > 0


def test_show_build_html_empty_title_raises(tmp_path):
    """title 全非法字符 → 规范化为空，如实报错不静默。"""
    from ashot import show as show_mod
    import pytest
    img = tmp_path / "t.png"
    img.write_bytes(_tiny_png())
    with pytest.raises(ValueError):
        show_mod.build_html(str(img), "!!!", str(tmp_path))


def test_show_caption_escaped_and_makedirs(tmp_path):
    """恶意 caption 必须 html.escape（::visualize 渲染路径的注入防线，
    审计 P2-2 mutant 实测存活后补锁）；out_dir 不存在自动创建（含
    嵌套，审计 P3-7）。"""
    from ashot import show as show_mod
    img = tmp_path / "t.png"
    img.write_bytes(_tiny_png())
    res = show_mod.build_html(str(img), "cap test",
                              str(tmp_path / "deep" / "nested"),
                              caption='<img src=x onerror=alert(1)>&"')
    html_text = open(res["html"], encoding="utf-8").read()
    assert "<img src=x" not in html_text, "caption 注入未转义"
    assert "&lt;img src=x onerror=alert(1)&gt;&amp;&quot;" in html_text


def test_show_title_too_long_raises(tmp_path):
    """title 超长（规范化后 >80 字符）如实报错（防 MAX_PATH 边缘，
    审计 P3-4）。"""
    from ashot import show as show_mod
    import pytest
    img = tmp_path / "t.png"
    img.write_bytes(_tiny_png())
    with pytest.raises(ValueError):
        show_mod.build_html(str(img), "x" * 100, str(tmp_path))


def test_show_cli_subcommand(tmp_path):
    """CLI show 子命令子进程实跑：html 路径 stdout、preview 信息 stderr。"""
    import subprocess
    import sys
    img = tmp_path / "in.png"
    img.write_bytes(_tiny_png())
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "show",
                        str(img), "--title", "cli show test",
                        "--out-dir", str(tmp_path)],
                       capture_output=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = r.stdout.decode("utf-8", "replace")
    assert os.path.isfile(out.strip().splitlines()[0])
    assert "preview: " in r.stderr.decode("utf-8", "replace")


# ---------- v0.2.0 批1 CDP（纯 stdlib WebSocket + CDP 客户端） ----------

class _FakeWsServer:
    """最小 WS 服务端桩：握手应答 + 收一帧回 N 帧响应（可分片/ping）。
    纯 stdlib socket，单测用（审计：批1 无浏览器环境全单测不触网）。"""
    import hashlib as _hashlib
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, responses):
        import socket as _socket
        self._srv = _socket.socket()
        self._srv.setsockopt(_socket.SOL_SOCKET,
                             _socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._responses = list(responses)   # [(opcode, payload, fin)]

    def handshake_key(self, key):
        import hashlib
        import base64
        return base64.b64encode(
            hashlib.sha1((key + self.GUID).encode()).digest()).decode()

    def serve_once(self):
        import threading
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()
        return t

    def _serve(self):
        import struct
        conn, _ = self._srv.accept()
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(4096)
            head, _, rest = buf.partition(b"\r\n\r\n")
            key = ""
            for ln in head.split(b"\r\n"):
                if ln.lower().startswith(b"sec-websocket-key:"):
                    key = ln.split(b":", 1)[1].strip().decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                          "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\n\r\n"
                          % self.handshake_key(key)).encode())
            # 读客户端一帧（带掩码；客户端消息短，单帧必达）
            data = rest
            while len(data) < 2:
                data += conn.recv(4096)
            h, data = data[:2], data[2:]
            ln = h[1] & 0x7F
            if ln == 126:
                while len(data) < 2:
                    data += conn.recv(4096)
                ln = struct.unpack(">H", data[:2])[0]
                data = data[2:]
            elif ln == 127:
                while len(data) < 8:
                    data += conn.recv(4096)
                ln = struct.unpack(">Q", data[:8])[0]
                data = data[8:]
            need = 4 + ln
            while len(data) < need:
                data += conn.recv(4096)
            # 客户端命令帧已完整收到，逐条回响应
            for opcode, body, fin in self._responses:
                out = bytes([(0x80 if fin else 0x00) | opcode, len(body)])
                conn.sendall(out + body)
            import time
            time.sleep(0.1)   # 给客户端留收帧窗口，避免 RST 掐连接
        finally:
            conn.close()
            self._srv.close()


def test_ws_frame_roundtrip_and_fragmentation():
    """WS 客户端核心（审计 P2-11）：握手、masked 发送、**分片重组**
    （text 三片 + 中途 ping 回 pong）、消息级 call 往返。"""
    from ashot import cdp as cdp_mod
    reply = json.dumps({"id": 1, "result": {"ok": True}}).encode()
    # 片1（无FIN）+ 片2（无FIN）+ ping（FIN）+ 片3（FIN=continuation 语义
    # 由 opcode 0 表达）
    half1, half2, half3 = reply[:5], reply[5:9], reply[9:]
    srv = _FakeWsServer([(0x1, half1, False), (0x0, half2, False),
                         (0x9, b"hb", True), (0x0, half3, True)])
    thread = srv.serve_once()
    res = cdp_mod.call("ws://127.0.0.1:%d/devtools/page/x" % srv.port,
                       "Page.captureScreenshot")
    thread.join(timeout=5)
    assert res == {"ok": True}


def test_ws_coalesced_and_single_frame():
    """合包共存（审计 P1-1 实锤场景）：握手 rest 携带事件帧+应答帧同段
    ——buf 线穿修复前必丢应答；另补「单帧 FIN=1 应答」纯路径单测
    （最常见实弹路，审计 P3-12a）。"""
    from ashot import cdp as cdp_mod

    class _Stub:
        """伪服务端：握手后把「事件帧+应答帧」一次性塞进 101 响应体
        （合法合包），之后 socket 不再发任何数据。"""
        import hashlib as _h
        GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

        def __init__(self, early_frames):
            import socket
            self._srv = socket.socket()
            self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._srv.bind(("127.0.0.1", 0))
            self._srv.listen(1)
            self.port = self._srv.getsockname()[1]
            self._early = early_frames   # [(opcode, payload, fin)]

        def _serve(self):
            import struct
            conn, _ = self._srv.accept()
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    buf += conn.recv(4096)
                head, _, rest = buf.partition(b"\r\n\r\n")
                key = ""
                for ln in head.split(b"\r\n"):
                    if ln.lower().startswith(b"sec-websocket-key:"):
                        key = ln.split(b":", 1)[1].strip().decode()
                accept = base64.b64encode(
                    __import__("hashlib").sha1(
                        (key + self.GUID).encode()).digest()).decode()
                early = b""
                for opcode, body, fin in self._early:
                    early += bytes([(0x80 if fin else 0x00) | opcode,
                                    len(body)]) + body
                conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                              "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                              "Sec-WebSocket-Accept: %s\r\n\r\n"
                              % accept).encode() + early)
                import time
                time.sleep(0.1)
            finally:
                conn.close()
                self._srv.close()

        def serve(self):
            import threading
            threading.Thread(target=self._serve, daemon=True).start()

    reply = json.dumps({"id": 1, "result": {"v": 42}}).encode()
    event = json.dumps({"method": "Page.loadEventFired"}).encode()
    # 合包：101 响应体里直接带 事件帧(首片无FIN + continuation片FIN) +
    # 应答帧(FIN 单帧)
    stub = _Stub([(0x1, event[:3], False), (0x0, event[3:], True),
                  (0x1, reply, True)])
    stub.serve()
    res = cdp_mod.call("ws://127.0.0.1:%d/devtools/page/y" % stub.port,
                       "Page.captureScreenshot")
    assert res == {"v": 42}


def test_ws_frame_encoding_units():
    """_send_frame 长度三态：三档 payload 过 _send_frame 编码头 + 掩码
    后的总长 == 2+len(header_ext)+4+n（发侧规格反向验证）。"""
    from ashot import cdp as cdp_mod
    import struct

    class _Sink:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data
    for n in (125, 126, 70000):
        sink = _Sink()
        cdp_mod._send_frame(sink, 0x1, b"a" * n)
        first, second = sink.sent[0], sink.sent[1]
        assert first == 0x81  # FIN + text
        ln7 = second & 0x7F
        masked = bool(second & 0x80)
        assert masked  # 客户端帧必须 mask（审计 P2-11）
        if n == 125:
            assert ln7 == 125 and len(sink.sent) == 2 + 4 + n
        elif n == 126:
            assert ln7 == 126
            assert struct.unpack(">H", sink.sent[2:4])[0] == 126
            assert len(sink.sent) == 4 + 4 + n
        else:
            assert ln7 == 127
            assert struct.unpack(">Q", sink.sent[2:10])[0] == 70000
            assert len(sink.sent) == 10 + 4 + n


def test_cdp_discover_no_browser():
    """无浏览器环境 discover 如实报（返回空 ports + hint，不抛）——
    审计 P2-13d：无浏览器 CI 环境全单测不触网。"""
    from ashot import cdp as cdp_mod
    res = cdp_mod.discover()
    # 本机可能真有调试浏览器——不假设空，但结构必须正确
    assert isinstance(res, dict) and "ports" in res and "hint" in res
    assert isinstance(res["ports"], list)


def test_cdp_find_port_from_profile(tmp_path):
    """DevToolsActivePort 解析：正常/缺失/坏内容三态。"""
    from ashot import cdp as cdp_mod
    (tmp_path / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
    assert cdp_mod.find_port_from_profile(str(tmp_path)) == 9333
    try:
        cdp_mod.find_port_from_profile(str(tmp_path / "nope"))
        raise AssertionError("缺失未报错")
    except RuntimeError:
        pass
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "DevToolsActivePort").write_text("junk\n")
    try:
        cdp_mod.find_port_from_profile(str(tmp_path / "bad"))
        raise AssertionError("坏内容未报错")
    except RuntimeError:
        pass


# ---------- v0.2.0 §4.2.2 输入事件注入 ----------

def test_key_events_sequences():
    """键序列构造（审计规格 §4.2.2）：可见字符 rawKeyDown+char+keyUp
    三连；控制键 keyDown+keyUp 且 key 名=UI Events 规范（审计 P1-1：
    小写别名传入、规范 key 名出——页面 e.key 可识别）；组合键
    modifiers 位+按住/回弹序。"""
    from ashot import cdp as cdp_mod
    # 可见字符三连，char 带 text
    seq = cdp_mod.key_events("a")
    assert [e["type"] for e in seq] == ["rawKeyDown", "char", "keyUp"]
    assert seq[1]["text"] == "a"
    assert seq[0]["windowsVirtualKeyCode"] == 65
    # 控制键双发：key 名必须是规范名（实机 e.key 可识别）
    seq = cdp_mod.key_events("enter")
    assert [e["type"] for e in seq] == ["keyDown", "keyUp"]
    assert seq[0]["key"] == "Enter"
    assert seq[0]["windowsVirtualKeyCode"] == 13
    seq = cdp_mod.key_events("f5")
    assert seq[0]["key"] == "F5" and seq[0]["code"] == "F5"
    # 组合键：ctrl+s = ctrl 按下 + s(rawDown/char/keyUp, modifiers=2)
    #          + ctrl 回弹
    seq = cdp_mod.key_events("s", "ctrl")
    types = [e["type"] for e in seq]
    assert types == ["keyDown", "rawKeyDown", "char", "keyUp", "keyUp"]
    assert seq[0]["key"] == "Control" and seq[0]["modifiers"] == 2
    assert seq[-1]["key"] == "Control"
    assert seq[1]["modifiers"] == 2
    # modifiers 位掩码
    assert cdp_mod._parse_modifiers("ctrl+shift") == 10
    assert cdp_mod._parse_modifiers(["alt"]) == 1
    try:
        cdp_mod._parse_modifiers("bogus")
        raise AssertionError("未知修饰键未报错")
    except ValueError:
        pass


def test_key_events_full_coverage():
    """v0.2.2 键表补全锁：F 功能键/符号别名（非移位+移位级）/未知键
    unresolved 标记 + dispatch 真实剥除汇总（审计 P1-3 死代码假锁
    换真测试：monkeypatch call 零网络验证 pop 契约）。"""
    from ashot import cdp as cdp_mod
    # F 键查表（VK 112-123，非 ord）+ 规范 key 名
    seq = cdp_mod.key_events("f5")
    assert seq[0]["windowsVirtualKeyCode"] == 116
    assert seq[0]["code"] == "F5" and seq[0]["key"] == "F5"
    # 符号字符别名：";" → semicolon（VK 186 ≠ ord(';')=59——ord 错表修正）
    seq = cdp_mod.key_events(";")
    assert seq[0]["windowsVirtualKeyCode"] == 186
    assert seq[0]["code"] == "Semicolon"
    assert seq[0]["key"] == ";"   # 审计 P1-2：key=符号本身非 code 名
    assert any(e.get("type") == "char" and e["text"] == ";"
               for e in seq)
    # 具名符号键也可直接传（key 名=符号）
    seq = cdp_mod.key_events("minus")
    assert seq[0]["windowsVirtualKeyCode"] == 189
    assert seq[0]["key"] == "-"
    # 移位级符号（审计 P2-1）：":" → VK 186（Shift 位产生，本表直出）
    seq = cdp_mod.key_events(":")
    assert seq[0]["windowsVirtualKeyCode"] == 186
    assert seq[0]["key"] == ":" and seq[0]["code"] == "Semicolon"
    assert seq[0]["windowsVirtualKeyCode"] != ord(":")
    # 未知键名：透传但带 unresolved 标记（收据亮牌契约）
    seq = cdp_mod.key_events("MediaPlay")
    assert all(e.get("unresolved") for e in seq)


def test_dispatch_strips_unresolved(monkeypatch):
    """dispatch 真实剥除 unresolved 并汇总（审计 P1-3：原测试 if False
    死代码假锁——mutant 实测删 pop 全绿存活）。零网络桩。

    v0.2.5 桩要挂两处：`_ws_connect`（Session 构造时的真实握手）与
    `Session.command`（派发出口）。只挂 command 会在构造时 ConnectionRefused
    ——连接发生在 __init__ 里，不在 command 里。"""
    from ashot import cdp as cdp_mod
    captured = []

    class _DummySock:
        def close(self):
            pass

        def settimeout(self, t):
            pass

    monkeypatch.setattr(cdp_mod, "_ws_connect",
                        lambda host, port, path, timeout=15:
                        (_DummySock(), b""))
    monkeypatch.setattr(cdp_mod.Session, "command",
                        lambda self, m, p=None: captured.append(p)
                        or {})
    seq = cdp_mod.key_events("MediaPlay")
    assert all(e.get("unresolved") for e in seq)
    n, unresolved = cdp_mod.dispatch("ws://127.0.0.1:1/x", seq)
    assert n == 2 and unresolved == ["MediaPlay"]
    # 发到线上的事件不得携带非法字段 unresolved
    assert all("unresolved" not in e for e in captured), captured


def test_drag_events_sequence():
    """拖拽序列（v0.2.5）：moved(起始) → pressed → 轨迹 moved（buttons=
    press 掩码）→ 末端过冲 → 回退到终点 → released。

    两档契约分别锁：
      · constrained=True（**缺省**）= 受轨道约束：垂直偏移 ≤ max_perp，
        不随距离放大（旧版会漂 50px → 拖滑块必脱轨）；
      · constrained=False = 自由拖拽：保留贝塞尔弧度。
    """
    from ashot import cdp as cdp_mod

    def off_line(e):
        # 直线 y = 10 + (x-10)*0.5
        return abs(e["y"] - (10 + (e["x"] - 10) * 0.5))

    # ① 缺省 = 受约束（拖滑块/进度条要的就是这个）
    seq = cdp_mod.drag_events(10, 10, 110, 60, steps=4, seed=7)
    types = [e["type"] for e in seq]
    assert types.count("mousePressed") == 1
    assert types[-1] == "mouseReleased"
    moved = [e for e in seq if e["type"] == "mouseMoved"]
    assert len(moved) >= 5   # 起始 + 轨迹
    # 纵向漂移必须被夹住，且与距离无关
    assert max(off_line(e) for e in moved) <= 3.0, "受约束模式仍在纵向漂"
    # 末端过冲 + 回到精确终点
    assert moved[-1]["x"] == 110 and moved[-1]["y"] == 60, "终点未精确落点"

    # ② 长距离：漂移不放大（旧版 520px 会漂 50px）
    seq = cdp_mod.drag_events(80, 200, 600, 200, seed=11)
    mv = [e for e in seq if e["type"] == "mouseMoved"]
    assert max(abs(e["y"] - 200) for e in mv) <= 3.0, "长距离漂移放大了"
    assert mv[-1]["x"] == 600 and mv[-1]["y"] == 200

    # ③ 自由拖拽：弧度契约保留
    seq = cdp_mod.drag_events(10, 10, 110, 60, steps=4, seed=7,
                              constrained=False)
    moved = [e for e in seq if e["type"] == "mouseMoved"]
    assert any(off_line(e) > 1.0 for e in moved[1:-1]), "自由轨迹毫无弧度"
    assert moved[-1]["x"] == 110 and moved[-1]["y"] == 60, "自由模式终点错"

    # ④ 节奏档位：captcha 比 normal 慢，normal 比 fast 慢
    st = {"fast": {}, "normal": {}, "captcha": {}}
    for pc in st:
        s = cdp_mod.drag_events(0, 0, 300, 0, seed=3, pace=pc)
        st[pc]["steps"] = sum(1 for e in s if e["type"] == "mouseMoved")
        st[pc]["ms"] = round(sum(float(e.get("_delay_ms", 0)) for e in s), 1)
    assert st["captcha"]["ms"] > st["normal"]["ms"] > st["fast"]["ms"], st
    # total_ms 显式优先于 pace
    s = cdp_mod.drag_events(0, 0, 300, 0, seed=3, pace="captcha", total_ms=0)
    assert sum(float(e.get("_delay_ms", 0)) for e in s) == 0, "total_ms=0 应全速"

    pressed = [e for e in seq if e["type"] == "mousePressed"][0]
    assert pressed["buttons"] == 1
    # 中键拖拽 buttons 位（审计 P2-1：press 掩码按 button 查表，middle=4）
    seq = cdp_mod.drag_events(0, 0, 10, 10, steps=1, button="middle")
    pressed = [e for e in seq if e["type"] == "mousePressed"][0]
    assert pressed["buttons"] == 4 and pressed["button"] == "middle"
    # teleport 逃生门：直线插值旧行为
    seq = cdp_mod.drag_events(0, 0, 40, 30, steps=2, human=False)
    moved = [e for e in seq if e["type"] == "mouseMoved"]
    assert [(e["x"], e["y"]) for e in moved[1:]] == [(20, 15), (40, 30)]


def test_human_move_events_determinism():
    """人类化轨迹纯函数锁：seed 确定性、首尾精确、步数自适应边界、
    抖动 fade（首尾无抖动）。"""
    from ashot import cdp as cdp_mod
    a = cdp_mod.human_move_events(0, 0, 500, 400, seed=42)
    b = cdp_mod.human_move_events(0, 0, 500, 400, seed=42)
    assert a == b, "同 seed 轨迹不同"
    c = cdp_mod.human_move_events(0, 0, 500, 400, seed=43)
    assert a != c, "不同 seed 轨迹相同"
    # 首点仍贴近起点（缓动起步、抖动 fade=0）、终点精确
    assert abs(a[0][0]) < 30 and abs(a[0][1]) < 30, a[0]
    assert a[-1] == (500.0, 400.0), "终点带抖动"
    # 步数自适应：距离 640 → ~25 步（min(28, 640/25=25)）
    assert 20 <= len(a) <= 30, len(a)
    # 短距离：dist<25 → 8 步下限
    short = cdp_mod.human_move_events(0, 0, 20, 0, seed=1)
    assert len(short) == 8
    # 抖动=0：轨迹应是纯贝塞尔（仍非直线，但可复现）
    j0 = cdp_mod.human_move_events(0, 0, 500, 400, jitter=0, seed=9)
    assert j0[-1] == (500.0, 400.0)


def test_dispatch_insert_text_route(monkeypatch):
    """insertText 路由锁（审计 P2-3——本批头条修复的回归锁）：
    insertText 事件必须走**独立命令 Input.insertText**（参数仅 text），
    不得再进 dispatchKeyEvent（实弹曾报 Unexpected event type）。"""
    from ashot import cdp as cdp_mod
    calls = []

    class _DummySock:
        def close(self):
            pass

        def settimeout(self, t):
            pass

    monkeypatch.setattr(cdp_mod, "_ws_connect",
                        lambda host, port, path, timeout=15:
                        (_DummySock(), b""))
    monkeypatch.setattr(cdp_mod.Session, "command",
                        lambda self, m, p=None:
                        calls.append((m, p)) or {})
    n, unresolved = cdp_mod.dispatch(
        "ws://127.0.0.1:1/x", cdp_mod.insert_text_events("表文"))
    assert n == 1 and unresolved == []
    assert calls == [("Input.insertText", {"text": "表文"})]
    # 双击序列路由到 dispatchMouseEvent 且 clickCount 递增（human=False
    # 固定事件数=5，便于断言；human 轨迹事件数随距离自适应）
    calls.clear()
    seq = cdp_mod.dblclick_events(5, 6, count=2, human=False)
    n, _ = cdp_mod.dispatch("ws://127.0.0.1:1/x", seq)
    assert n == 5
    assert all(m == "Input.dispatchMouseEvent" for m, _ in calls)
    ccs = [p["clickCount"] for _, p in calls if p["type"] == "mousePressed"]
    assert ccs == [1, 2]


def test_dblclick_and_insert_text():
    """v0.2.3/0.2.4：双击=human 轨迹到位 + clickCount 递增序列（浏览器
    据此合成 dblclick）；insertText=粘贴式填表（不逐键击）。"""
    from ashot import cdp as cdp_mod
    seq = cdp_mod.dblclick_events(50, 60, human=False)
    types = [e["type"] for e in seq]
    assert types == ["mouseMoved", "mousePressed", "mouseReleased",
                     "mousePressed", "mouseReleased"]
    assert seq[1]["clickCount"] == 1 and seq[2]["clickCount"] == 1
    assert seq[3]["clickCount"] == 2 and seq[4]["clickCount"] == 2
    # human=True：前面多出人类化 moved 序列，clickCount 语义不变
    seq = cdp_mod.dblclick_events(50, 60, human=True, seed=5)
    presses = [e for e in seq if e["type"] == "mousePressed"]
    assert [e["clickCount"] for e in presses] == [1, 2]
    assert seq[0]["type"] == "mouseMoved" and len(seq) > 5
    seq = cdp_mod.dblclick_events(0, 0, count=3, human=False)
    assert sum(1 for e in seq if e["type"] == "mousePressed") == 3
    # insertText：粘贴式单事件，text 整段携带
    seq = cdp_mod.insert_text_events("多行文本\n第二行")
    assert len(seq) == 1
    assert seq[0]["type"] == "insertText"
    assert seq[0]["text"] == "多行文本\n第二行"


def test_cdp_dispatch_with_stub():
    """dispatch 走 WS 桩真实派发：**一次握手、整批事件全部送达**。

    v0.2.5 把 dispatch 从"每事件一次独立连接"改成会话化（省掉每事件
    一次握手）。桩因此必须：① 在**同一条连接**上循环收发；② **回显请求
    id**——桩若固定回 id=1，Session 的 id 递增匹配会一直等第二条的应答
    直到超时（这就是"卡住"的根源，不是网络慢）。
    """
    from ashot import cdp as cdp_mod
    sent = []

    class _Multi(_FakeWsServer):
        def _serve(self):
            import struct
            import time
            conn, _ = self._srv.accept()
            try:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    c = conn.recv(4096)
                    if not c:
                        return
                    buf += c
                head, _, rest = buf.partition(b"\r\n\r\n")
                key = ""
                for ln in head.split(b"\r\n"):
                    if ln.lower().startswith(b"sec-websocket-key:"):
                        key = ln.split(b":", 1)[1].strip().decode()
                conn.sendall(("HTTP/1.1 101 Switching Protocols\r\n"
                              "Upgrade: websocket\r\n"
                              "Connection: Upgrade\r\n"
                              "Sec-WebSocket-Accept: %s\r\n\r\n"
                              % self.handshake_key(key)).encode())
                data = rest
                while True:
                    while len(data) < 2:
                        c = conn.recv(4096)
                        if not c:
                            return
                        data += c
                    h, data = data[:2], data[2:]
                    ln = h[1] & 0x7F
                    if ln == 126:
                        while len(data) < 2:
                            data += conn.recv(4096)
                        ln = struct.unpack(">H", data[:2])[0]
                        data = data[2:]
                    elif ln == 127:
                        while len(data) < 8:
                            data += conn.recv(4096)
                        ln = struct.unpack(">Q", data[:8])[0]
                        data = data[8:]
                    need = 4 + ln
                    while len(data) < need:
                        c = conn.recv(4096)
                        if not c:
                            return
                        data += c
                    # 客户端帧：4 字节掩码 + masked payload——解析前必须
                    # 去掩码（原桩只 collect 不解析所以没踩这坑）
                    mask, mp = data[:4], data[4:4 + ln]
                    payload = bytes(mp[i] ^ mask[i % 4]
                                    for i in range(ln))
                    data = data[4 + ln:]
                    sent.append(payload)
                    # 回显 id：会话化之后每条命令的 id 都不同
                    try:
                        rid = json.loads(payload.decode("utf-8")).get("id")
                    except Exception:
                        rid = 1
                    body = json.dumps({"id": rid, "result": {}}).encode()
                    conn.sendall(bytes([0x81, len(body)]) + body)
                    time.sleep(0.05)
            finally:
                conn.close()
                self._srv.close()

    srv = _Multi([])      # 响应由 _serve 按请求 id 动态生成

    import threading
    threads = [srv.serve_once() for _ in range(1)]
    n, unresolved = cdp_mod.dispatch(
        "ws://127.0.0.1:%d/devtools/page/z" % srv.port,
        cdp_mod.drag_events(0, 0, 40, 30, steps=1, total_ms=0))
    for t in threads:
        t.join(timeout=5)
    # 起始 moved + pressed + 轨迹 moved×steps（total_ms=0 时无过冲）+
    # released
    assert n == 4, n
    assert unresolved == []
    assert len(sent) == 4
    # 派发出去的事件里不得残留内部元信息字段
    for raw in sent:
        ev = json.loads(raw.decode("utf-8"))
        assert "_delay_ms" not in ev, ev
        assert "unresolved" not in ev, ev
# ---------- v0.2.6 修复锁（审查清单 Q03-Q22） ----------
import copy

import pytest


def _stub_ws(monkeypatch, cdp_mod):
    """把 dispatch 的握手与命令出口换成内存桩，返回已发送命令列表。"""
    calls = []

    class _Sock:
        def close(self):
            pass

        def settimeout(self, t):
            pass

    monkeypatch.setattr(cdp_mod, "_ws_connect",
                        lambda *a, **k: (_Sock(), b""))
    monkeypatch.setattr(cdp_mod.Session, "command",
                        lambda self, m, p=None: calls.append((m, p)) or {})
    return calls


def test_dispatch_does_not_mutate_input_q03(monkeypatch):
    """Q03 修复锁：dispatch 不得就地 pop 调用方的 _delay_ms/unresolved。

    旧实现直接改输入事件，同一 seq 第二次派发时节奏延时全丢；现有实现
    先 dict() 拷贝。锁住"入参不变 + 可重试"两件事（原测试只查发送侧）。"""
    from ashot import cdp as cdp_mod
    _stub_ws(monkeypatch, cdp_mod)
    seq = cdp_mod.drag_events(10, 10, 200, 40, seed=3)
    before = copy.deepcopy(seq)
    assert any("_delay_ms" in e for e in before)
    n1, _ = cdp_mod.dispatch("ws://127.0.0.1:1/x", seq, realtime=False)
    assert seq == before, "dispatch 改动了调用方的事件序列"
    n2, _ = cdp_mod.dispatch("ws://127.0.0.1:1/x", seq, realtime=False)
    assert n2 == n1, "重试时事件数变了（元信息被吃掉了）"


def test_discover_reports_enum_failure_q20(monkeypatch):
    """Q20：进程枚举失败必须亮牌（旧实现只看 stdout，stderr 被吞）。"""
    from ashot import cdp as cdp_mod
    monkeypatch.setattr(cdp_mod, "_enum_browser_processes",
                        lambda: ([], "进程枚举失败（rc=1）：Access denied"))
    monkeypatch.setattr(cdp_mod, "_probe_ports",
                        lambda ports, timeout=0.6, workers=8:
                        {p: p == 9222 for p in ports})
    res = cdp_mod.discover()
    assert res["ports"] == [9222]
    assert res["confidence"] == "scan"
    assert res["warnings"] and "Access denied" in res["warnings"][0]
    assert "别的工具" in res["hint"]
    assert res["details"][0]["source"] == "scan"


def test_discover_marks_process_identity_q04(monkeypatch):
    """Q04/Q20：进程枚举成功时给出进程名，confidence=process。"""
    from ashot import cdp as cdp_mod
    cmd = ('C:\\Program Files\\Edge\\msedge.exe --remote-debugging-port=9333 '
           '--user-data-dir=C:\\ud')
    monkeypatch.setattr(cdp_mod, "_enum_browser_processes",
                        lambda: ([(9333, cmd)], None))
    monkeypatch.setattr(cdp_mod, "_probe_ports",
                        lambda ports, timeout=0.6, workers=8:
                        {p: p == 9333 for p in ports})
    res = cdp_mod.discover()
    assert res["ports"] == [9333]
    assert res["confidence"] == "process"
    assert res["details"][0]["process"] == "msedge.exe"
    assert res["warnings"] == []


def test_pick_port_single_and_multi_q04(monkeypatch):
    """Q04：单实例返回身份信息；多实例输入类动作必须拒绝猜。"""
    from ashot import cdp as cdp_mod
    one = {"ports": [9301], "details": [{"port": 9301, "source": "scan",
                                         "process": "chrome.exe",
                                         "user_data_dir": ""}],
           "warnings": ["枚举失败"], "hint": "x"}
    monkeypatch.setattr(cdp_mod, "discover", lambda: one)
    p, info = cdp_mod.pick_port(None)
    assert p == 9301
    assert info["process"] == "chrome.exe"
    assert info["warnings"] == ["枚举失败"]      # 单实例也要带痕

    two = dict(one, ports=[9301, 9302],
               details=one["details"] + [{"port": 9302, "source": "scan",
                                          "process": "", "user_data_dir": ""}])
    monkeypatch.setattr(cdp_mod, "discover", lambda: two)
    monkeypatch.setattr(cdp_mod, "tabs", lambda port: [])
    with pytest.raises(RuntimeError) as ei:
        cdp_mod.pick_port(None)
    assert "--port" in str(ei.value)
    assert cdp_mod.pick_port(None, allow_multi=True)[0] == 9301


def test_cdp_shot_coord_space_q06(monkeypatch):
    """Q06：全页截图的坐标是文档坐标——收据必须带 coord_space 与
    scroll_y，hint 不得再说"就是点击坐标"。"""
    from ashot import cdp as cdp_mod
    tall = output.bgra_to_png(100, 900, b"\x10\x20\x30\xff" * (100 * 900))
    data = base64.b64encode(tall).decode()

    def fake_call(ws, method, params=None, timeout=30):
        return {"data": data}

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 400, "vh": 300, "content_w": 100, "content_h": 900,
         "scroll_y": 123, "scroll_x": 0}, 2))
    png, info = cdp_mod.shot(9222, ws="ws://x/devtools/page/1", stitch=False)
    assert info["coord_space"] == "document"
    assert info["scroll_y"] == 123
    assert "文档坐标" in info["hint"]

    short = output.bgra_to_png(100, 300, b"\x10\x20\x30\xff" * (100 * 300))
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"data": base64.b64encode(short).decode()})
    # 内容高==视口高：全页截图与视口截图等价
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 400, "vh": 300, "content_w": 100, "content_h": 300,
         "scroll_y": 0, "scroll_x": 0}, 2))
    _, info2 = cdp_mod.shot(9222, ws="ws://x/devtools/page/1", stitch=False)
    assert info2["coord_space"] == "viewport"

    # 审计 S1：dpr 求值失败是真实路径（evaluate 单独 try，vw/vh 仍在）。
    # 旧实现 `dpr or 1` 会把 400×600 的视口截图标成 document、to_css 错一倍。
    big = output.bgra_to_png(400, 600, b"\x10\x20\x30\xff" * (400 * 600))
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"data": base64.b64encode(big).decode()})
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 400, "vh": 300, "content_w": 400, "content_h": 300,
         "scroll_y": 0, "scroll_x": 0}, None))
    _, info3 = cdp_mod.shot(9222, ws="ws://x/devtools/page/1", fullpage=False)
    assert info3["coord_space"] == "viewport", info3
    assert info3["to_css_estimated"] is True
    assert "退化估算" in info3["hint"]

    # 二轮审查（实测抖音页）：content_h 比视口高，但 Chrome 把
    # captureBeyondViewport 夹到了视口高——图像 CSS 高 == vh，不能因为
    # content_h 大就谎报"文档坐标"。
    clamped = output.bgra_to_png(400, 600, b"\x10\x20\x30\xff" * (400 * 600))
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"data": base64.b64encode(clamped).decode()})
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 400, "vh": 300, "content_w": 400, "content_h": 1632,
         "scroll_y": 0, "scroll_x": 0}, 2))
    _, info4 = cdp_mod.shot(9222, ws="ws://x/devtools/page/1", stitch=False)
    assert info4["coord_space"] == "viewport", info4
    assert "只截到视口" in info4["hint"]


def test_annotate_default_out_q07():
    """Q07：父目录带点、basename 无点时不得把路径截到上一级。"""
    assert annotate.default_out(r"C:\a\my.dir\shot") == \
        r"C:\a\my.dir\shot_annotated.png"
    assert annotate.default_out(r"C:\a\b\shot.png") == \
        r"C:\a\b\shot_annotated.png"
    assert annotate.default_out(r"C:\a\b\shot") == \
        r"C:\a\b\shot_annotated.png"


def test_cli_annotate_dotted_dir_q07(tmp_path):
    """Q07 端到端：父目录带点、basename 无点时，产物落回同目录。"""
    d = tmp_path / "my.dir"
    d.mkdir()
    src = d / "shot"
    src.write_bytes(_img(40, 30))
    r = subprocess.run(
        [sys.executable, "-m", "ashot.cli", "annotate", str(src),
         json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 4, "h": 4}])],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert (d / "shot_annotated.png").exists(), r.stdout
    assert not (tmp_path / "my_annotated.png").exists(), "仍写到上一级"


def test_degrade_reason_surfaced_q08(monkeypatch, tmp_path):
    """Q08：矢量路失败要留原因——"设计内降级"与"环境坏了"不再同形。"""
    from ashot import annotate_gdi, mcp as mcp_mod
    monkeypatch.setattr(annotate_gdi, "_RENDER_PS",
                        str(tmp_path / "no_such_renderer.ps1"))
    src = str(tmp_path / "in.png")
    open(src, "wb").write(_tiny_png())
    stats = {}
    out, backend, n = annotate_gdi.annotate_png_vector(
        _tiny_png(), [{"kind": "rect", "x": 0, "y": 0, "w": 2, "h": 2}],
        stats=stats)
    assert backend == "pixel"
    assert stats["degrade_reason"] and "ps_rc" in stats["degrade_reason"]
    rec = json.loads(mcp_mod._annotate(
        src, json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 2, "h": 2}]),
        out=str(tmp_path / "o.png"), preview=False))
    assert rec["backend_fallback"] is True
    assert rec["degrade_reason"]


def test_capture_keeps_gdi_error_q09(monkeypatch):
    """Q09：GDI 主路失败原因必须带出（兜底成功也留在收据里）。"""
    from ashot import capture
    monkeypatch.setattr(capture, "_shot_gdi",
                        lambda box: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(capture, "_shot_ps", lambda box: ("png", b"PNGDATA"))
    r = capture.shot("area", area=[0, 0, 10, 10])
    assert r["kind"] == "png" and r["png"] == b"PNGDATA"
    assert r["gdi_error"].startswith("OSError") and "boom" in r["gdi_error"]
    assert r["box_source"] == "area"

    def dead(box):
        raise RuntimeError("ps dead")

    monkeypatch.setattr(capture, "_shot_ps", dead)
    with pytest.raises(RuntimeError) as ei:
        capture.shot("area", area=[0, 0, 10, 10])
    assert "GDI 主路" in str(ei.value) and "ps dead" in str(ei.value)


def test_win_box_requires_foreground_q17(monkeypatch):
    """Q17：没有前台窗口时给可读错误，不是用 hwnd=0 去 GetWindowRect。"""
    from ashot import capture

    class _Fake:
        @staticmethod
        def GetForegroundWindow():
            return 0

        @staticmethod
        def SetProcessDPIAware():
            pass

    monkeypatch.setattr(capture, "U32", _Fake)
    with pytest.raises(RuntimeError) as ei:
        capture._win_box()
    assert "前台窗口" in str(ei.value)


def test_click_start_point_q12():
    """Q12：接近轨迹起点不再恒为 (0,0)；seed 决定方位、start 可覆盖。"""
    from ashot import cdp as cdp_mod
    import math
    p1 = cdp_mod._start_point(500, 500, seed=1)
    p2 = cdp_mod._start_point(500, 500, seed=2)
    r1 = math.hypot(p1[0] - 500, p1[1] - 500)
    assert 140 <= r1 <= 420, r1          # 起步半径契约
    a1 = math.atan2(p1[1] - 500, p1[0] - 500)
    a2 = math.atan2(p2[1] - 500, p2[0] - 500)
    assert abs(a1 - a2) > 0.05, "不同 seed 的起步方位相同（随机方位没锁住）"

    a = cdp_mod.click_events(400, 300, seed=1)
    b = cdp_mod.click_events(400, 300, seed=2)
    assert (a[0]["x"], a[0]["y"]) != (b[0]["x"], b[0]["y"])
    assert not (a[0]["x"] < 5 and a[0]["y"] < 5), "仍从左上角出发"
    c = cdp_mod.click_events(400, 300, seed=1, start=(40, 60))
    assert math.hypot(c[0]["x"] - 40, c[0]["y"] - 60) < \
        math.hypot(c[0]["x"] - 400, c[0]["y"] - 300)
    moved = [e for e in c if e["type"] == "mouseMoved"]
    assert (moved[-1]["x"], moved[-1]["y"]) == (400.0, 300.0)


def test_text_wrap_and_bounds_warn_q15(monkeypatch):
    """Q15：text 带 w 走 GDI+ 原生换行（实测 bbox 宽度受 w 约束），
    出界进 bounds_warn；像素降级路同样认 w。"""
    from ashot import annotate_gdi, vector
    shape = vector.compile_ops([{"kind": "text", "x": 0, "y": 0,
                                 "text": "a", "w": 50}])["shapes"][0]
    assert shape["w"] == 50.0

    stats = {}
    out, backend, _ = annotate_gdi.annotate_png_vector(
        _img(300, 120),
        [{"kind": "text", "x": 10, "y": 10, "size": 16, "w": 100,
          "text": "word " * 20}], stats=stats)
    box = stats["boxes"][0]
    assert backend == "gdi+"
    assert box["w"] <= 102, box        # 换行后宽度被 w 约束
    assert box["h"] > 20, box          # 多行

    stats2 = {}
    annotate_gdi.annotate_png_vector(
        _img(300, 120),
        [{"kind": "text", "x": 290, "y": 10, "size": 20,
          "text": "overflowing"}], stats=stats2)
    assert stats2["bounds_warn"], "越界没告警"
    assert "超出" in stats2["bounds_warn"][0]

    # 像素路：w 生效 -> 墨迹不越过 x+w 太多
    px_png = annotate.annotate_png(
        _img(200, 200),
        [{"kind": "text", "x": 10, "y": 10, "size": 16, "w": 60,
          "text": "A" * 40}])
    _, _, px = annotate._decode_png(px_png)
    max_x = 0
    for y in range(200):
        for x in range(200):
            i = (y * 200 + x) * 4
            # 底色 (0x30,0x60,0x90) 不算墨；只认红色字形
            if px[i] > 150 and px[i + 1] < 120:
                max_x = max(max_x, x)
    assert max_x <= 10 + 60 + 20, max_x


def test_decode_rgb_and_palette_q21():
    """Q21：像素路不再只吃 RGBA——RGB/调色板 PNG 也能解。"""
    import struct
    import zlib

    def _chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    def rgb_png(w, h):
        raw = b"".join(b"\x00" + bytes([10, 20, 30]) * w for _ in range(h))
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + _chunk(b"IDAT", zlib.compress(raw))
                + _chunk(b"IEND", b""))

    def pal_png(w, h):
        raw = b"".join(b"\x00" + bytes([0, 1]) * (w // 2) for _ in range(h))
        plte = bytes([255, 0, 0, 0, 255, 0])
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
                + _chunk(b"PLTE", plte)
                + _chunk(b"IDAT", zlib.compress(raw))
                + _chunk(b"IEND", b""))

    w, h, px = annotate._decode_png(rgb_png(4, 3))
    assert (w, h, tuple(px[:4])) == (4, 3, (10, 20, 30, 255))
    w, h, px = annotate._decode_png(pal_png(4, 3))
    assert tuple(px[0:4]) == (255, 0, 0, 255)
    assert tuple(px[4:8]) == (0, 255, 0, 255)

    # 审计：每行 filter=0 锁不住 bpp（把步长改回 4 的 mutant 能存活）——
    # 补一条 Sub(filter=1) 的 RGB 与调色板图。
    def sub_rgb_png(w, h, color=(10, 20, 30)):
        raw = bytearray()
        for _ in range(h):
            row = bytes(color) * w
            enc = bytearray(row)
            for i in range(len(row) - 1, 2, -1):   # 倒序：左侧仍是原值
                enc[i] = (row[i] - row[i - 3]) & 0xFF
            raw.append(1)
            raw += enc
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + _chunk(b"IDAT", zlib.compress(bytes(raw)))
                + _chunk(b"IEND", b""))

    def sub_pal_png(w, h):
        raw = bytearray()
        for _ in range(h):
            row = bytes([0, 1, 0, 1][:w])
            enc = bytearray(row)
            for i in range(len(row) - 1, 0, -1):   # bpp=1
                enc[i] = (row[i] - row[i - 1]) & 0xFF
            raw.append(1)
            raw += enc
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
                + _chunk(b"PLTE", bytes([255, 0, 0, 0, 255, 0]))
                + _chunk(b"IDAT", zlib.compress(bytes(raw)))
                + _chunk(b"IEND", b""))

    w, h, px = annotate._decode_png(sub_rgb_png(4, 2))
    assert (w, h, tuple(px[:4])) == (4, 2, (10, 20, 30, 255))
    w, h, px = annotate._decode_png(sub_pal_png(4, 2))
    assert tuple(px[0:4]) == (255, 0, 0, 255)
    assert tuple(px[4:8]) == (0, 255, 0, 255)


def test_eval_value_type_q14(monkeypatch):
    """Q14：收据带 value_type，undefined 与不可序列化对象可区分。"""
    from ashot import cdp as cdp_mod
    from ashot import mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_resolve_ws", lambda *a, **k: "ws://x")
    monkeypatch.setattr(cdp_mod, "evaluate",
                        lambda *a, **k: {"result": {"type": "undefined"}})
    rec = json.loads(mcp_mod._cdp_eval("1"))
    assert rec["value_type"] == "undefined" and "note" in rec
    monkeypatch.setattr(cdp_mod, "evaluate",
                        lambda *a, **k: {"result": {"type": "object"}})
    rec = json.loads(mcp_mod._cdp_eval("document"))
    assert rec["value_type"] == "object" and "不可序列化" in rec["note"]


def test_receipt_stamped_with_ver_and_target_q18():
    """Q18/Q04：收据单一出口盖 ver（识破旧进程）与 target（目标身份）。"""
    import ashot
    from ashot import mcp as mcp_mod
    mcp_mod._LAST_TARGET.clear()
    rec = json.loads(mcp_mod._stamp('{"ok": true}'))
    assert rec["ver"] == ashot.__version__
    mcp_mod._LAST_TARGET.update({"port": 9222, "title": "T", "url": "u"})
    try:
        rec = json.loads(mcp_mod._stamp('{"ok": true}'))
        assert rec["target"]["port"] == 9222
        # 非 JSON 文本原样返回（不炸）
        assert mcp_mod._stamp("plain text") == "plain text"
    finally:
        mcp_mod._LAST_TARGET.clear()


def test_mcp_error_receipt_stamped_q18():
    """Q18 审计：错误收据也必须带 ver——最需要识破旧进程的时候不能没有。"""
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "ashot_annotate",
                    "arguments": {"image": r"Z:\no-such-dir\nope.png",
                                  "ops": "[]", "preview": False}}},
    ]
    inp = "\n".join(json.dumps(x) for x in lines) + "\n"
    r = subprocess.run([sys.executable, "ashot_mcp.py"], input=inp.encode(),
                       capture_output=True, cwd=ROOT, timeout=120)
    outs = [json.loads(x) for x in r.stdout.decode("utf-8", "replace").splitlines()]
    err = [o for o in outs if o.get("id") == 2][0]
    assert err["result"]["isError"] is True
    rec = json.loads(err["result"]["content"][0]["text"])
    assert rec["ok"] is False and rec["ver"] == __version__


def test_preview_budget_and_default_q16():
    """Q16：preview 缺省开、预算压到 200KB、小图不放大。"""
    from ashot import cli, mcp as mcp_mod
    assert output.PREVIEW_MAX_BYTES_DEFAULT == 200 * 1024
    assert mcp_mod.TOOLS["ashot_shot"]["inputSchema"]["properties"][
        "preview"]["type"] == "boolean"
    jpeg, info = output.preview_jpeg(_img(800, 600))
    assert info["width"] == 800 and info["fit"] is True
    # v0.2.6 Q22：--ops 不得再被 --ops-file 前缀匹配吞掉（应报用法错误）
    with pytest.raises(SystemExit) as ei:
        cli.main(["annotate", "x.png", "--ops", "[]"])
    assert ei.value.code == 2


def test_show_keeps_500k_budget_q16(monkeypatch, tmp_path):
    """Q16 边界：show 是给人看的展示件，预算保持 500KB；
    200KB 只用于 MCP preview（模型自检），两个口径别混。"""
    from ashot import show
    seen = {}

    def fake(png, width=1200, max_bytes=None):
        seen["max_bytes"] = max_bytes
        seen["width"] = width
        return b"\xff\xd8jpeg", {"width": 10, "quality": 85,
                                 "bytes": 4, "fit": True}

    monkeypatch.setattr(show.output, "preview_jpeg", fake)
    src = tmp_path / "i.png"
    src.write_bytes(_tiny_png())
    show.build_html(str(src), "t", str(tmp_path / "o"))
    assert seen["max_bytes"] == 500 * 1024
    assert seen["width"] == 1200


def test_cli_cdp_shot_prints_coords(monkeypatch, tmp_path, capsys):
    """Q22：CLI cdp-shot 必须输出 to_css/coord_space（旧版只打 fullpage）。"""
    from ashot import cdp as cdp_mod
    from ashot import cli
    png = output.bgra_to_png(10, 10, b"\x00\x00\x00\xff" * 100)
    monkeypatch.setattr(cdp_mod, "pick_port",
                        lambda port, **k: (9222, {"port": 9222,
                                                  "source": "explicit",
                                                  "warnings": []}))
    monkeypatch.setattr(cdp_mod, "shot", lambda *a, **k: (png, {
        "fullpage": True, "w": 10, "h": 10, "vw": 5, "vh": 5, "dpr": 2,
        "to_css": 0.5, "coord_space": "viewport", "hint": "h"}))
    rc = cli.main(["cdp-shot", "--port", "9222",
                   "--out", str(tmp_path / "c.png")])
    assert rc == 0
    err = capsys.readouterr().err
    assert "to_css: 0.5" in err and "coord_space: viewport" in err

def test_pixel_fallback_bounds_warn_q15(monkeypatch, tmp_path):
    """Q15 另一半：矢量路降级到像素画布时，出界也要告警（估算 bbox）。"""
    from ashot import annotate_gdi
    monkeypatch.setattr(annotate_gdi, "_RENDER_PS",
                        str(tmp_path / "gone.ps1"))
    stats = {}
    out, backend, _ = annotate_gdi.annotate_png_vector(
        _img(200, 120),
        [{"kind": "text", "x": 180, "y": 10, "size": 20,
          "text": "overflow right"}], stats=stats)
    assert backend == "pixel"
    assert stats["bounds_warn"], "像素降级路仍静默出界"
    assert "超出" in stats["bounds_warn"][0]
    assert stats["boxes"] and stats["boxes"][0]["x"] == 180


def test_pick_port_tolerates_minimal_discover_q04(monkeypatch):
    """Q04 健壮性：discover 只回 ports 时 pick_port 不 KeyError。"""
    from ashot import cdp as cdp_mod
    monkeypatch.setattr(cdp_mod, "discover",
                        lambda: {"ports": [9301], "hint": "x"})
    p, info = cdp_mod.pick_port(None)
    assert p == 9301 and info["source"] == "scan" and info["warnings"] == []

def test_layout_prefers_css_content_size_q06(monkeypatch):
    """Q06 单位锁：getLayoutMetrics 的 contentSize 是设备像素（已废弃），
    cssContentSize 才是 CSS——旧实现取前者会把整页高报成 dpr 倍。"""
    from ashot import cdp as cdp_mod
    metrics = {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600},
               "layoutViewport": {"clientWidth": 1600, "clientHeight": 1200},
               "contentSize": {"width": 1882, "height": 6000},
               "cssContentSize": {"width": 941, "height": 3000},
               "cssVisualViewport": {}}

    def fake_call(ws, method, params=None, timeout=15):
        if method == "Page.getLayoutMetrics":
            return metrics
        return {"result": {"value": {"dpr": 2, "scrollY": 0, "scrollX": 0}}}

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    lay, dpr = cdp_mod.layout("ws://x")
    assert (lay["content_w"], lay["content_h"]) == (941, 3000), lay
    assert lay["content_source"] == "css"
    assert (lay["vw"], lay["vh"]) == (800, 600)

    # 老协议只有设备像素字段 -> 按 dpr 折算
    metrics2 = {"layoutViewport": {"clientWidth": 1600, "clientHeight": 1200},
                "contentSize": {"width": 1882, "height": 6000}}
    monkeypatch.setattr(cdp_mod, "call",
                        lambda ws, m, p=None, timeout=15:
                        metrics2 if m == "Page.getLayoutMetrics"
                        else {"result": {"value": {"dpr": 2}}})
    lay2, _ = cdp_mod.layout("ws://x")
    assert (lay2["content_w"], lay2["content_h"]) == (941, 3000), lay2
    assert lay2["content_source"] == "device/dpr"


def test_shot_marks_truncated_fullpage_q06(monkeypatch):
    """页太高 / 只截到视口时，收据必须亮 fullpage_truncated，不假装整页。"""
    from ashot import cdp as cdp_mod
    layout = lambda ws, timeout=15: (
        {"vw": 400, "vh": 300, "content_w": 400, "content_h": 3000,
         "scroll_y": 0, "scroll_x": 0}, 2)
    monkeypatch.setattr(cdp_mod, "layout", layout)

    # 只截到视口（图像 300 CSS == vh）：坐标是视口坐标，但整页没拍全
    viewport_png = output.bgra_to_png(400, 600, b"\x10\x20\x30\xff" * (400 * 600))
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"data": base64.b64encode(viewport_png).decode()})
    _, info = cdp_mod.shot(9222, ws="ws://x", stitch=False)
    assert info["coord_space"] == "viewport"
    assert info["fullpage_truncated"] is True
    assert "只截到视口" in info["hint"]

    # 拍到一部分（图像 1000 CSS > vh，但 < 整页 3000）：文档坐标 + 截断标记
    partial = output.bgra_to_png(400, 2000, b"\x10\x20\x30\xff" * (400 * 2000))
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"data": base64.b64encode(partial).decode()})
    _, info2 = cdp_mod.shot(9222, ws="ws://x", stitch=False)
    assert info2["coord_space"] == "document"
    assert info2["fullpage_truncated"] is True
    assert "只截到 1000 CSS" in info2["hint"] or "只截到" in info2["hint"]

def _band_png(w, h, band):
    return output.bgra_to_png(w, h, bytes([0, 0, band * 40, 255]) * (w * h))


def _stitch_stub(monkeypatch, cdp_mod, state):
    def fake_call(ws, method, params=None, timeout=30):
        if method == "Page.captureScreenshot":
            assert params.get("captureBeyondViewport") is False
            return {"data": base64.b64encode(
                _band_png(50, 50, state["scroll"] // 50)).decode()}
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if "scrollTop=" in expr:
                y = int(expr.split("scrollTop=")[1].split(";")[0])
                state["scroll"] = y
                return {"result": {"value": y}}
            return {"result": {"value": state["scroll"]}}
        raise AssertionError("unexpected method %r" % method)
    monkeypatch.setattr(cdp_mod, "call", fake_call)


def test_stitch_fullpage_scroll_and_compose_q22(monkeypatch):
    """超长页：按视口滚动逐屏拍、按实际 scrollY 拼、拍完还原滚动位置。"""
    from ashot import cdp as cdp_mod
    state = {"scroll": 0}
    _stitch_stub(monkeypatch, cdp_mod, state)
    lay = {"vw": 50, "vh": 50, "content_w": 50, "content_h": 200,
           "scroll_y": 0}
    png, info = cdp_mod._stitch_fullpage("ws://x", lay, 1)
    assert info["stitched"] is True and info["shots"] == 4
    assert (info["w"], info["h"]) == (50, 200)
    _, _, px = annotate._decode_png(png)
    assert px[0] == 0            # y=0  -> band 0
    assert px[(60 * 50) * 4] == 40    # y=60 -> band 1
    assert px[(110 * 50) * 4] == 80   # y=110 -> band 2
    assert px[(160 * 50) * 4] == 120  # y=160 -> band 3
    assert state["scroll"] == 0, "拼接后没还原滚动位置"


def test_shot_auto_stitches_truncated_fullpage_q22(monkeypatch):
    """单张只截到视口且页更高时，shot 自动改走拼接并如实标 stitched。"""
    from ashot import cdp as cdp_mod
    state = {"scroll": 0, "full": 0}

    def fake_call(ws, method, params=None, timeout=30):
        if method == "Page.captureScreenshot":
            if params.get("captureBeyondViewport"):
                state["full"] += 1
                return {"data": base64.b64encode(
                    _band_png(50, 50, 0)).decode()}
            return {"data": base64.b64encode(
                _band_png(50, 50, state["scroll"] // 50)).decode()}
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if "scrollTop=" in expr:
                y = int(expr.split("scrollTop=")[1].split(";")[0])
                state["scroll"] = y
                return {"result": {"value": y}}
            return {"result": {"value": state["scroll"]}}
        raise AssertionError(method)

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 50, "vh": 50, "content_w": 50, "content_h": 200,
         "scroll_y": 0}, 1))
    png, info = cdp_mod.shot(9222, ws="ws://x")
    assert state["full"] == 1, "先走了单张全页路径"
    assert info["stitched"] is True and info["h"] == 200
    assert info["coord_space"] == "document"
    assert info["shots"] == 4

    # stitch=False：不拼接，如实保留截断标记
    state.update(scroll=0, full=0)
    _, info2 = cdp_mod.shot(9222, ws="ws://x", stitch=False)
    assert "stitched" not in info2
    assert info2.get("fullpage_truncated") is True

def test_shot_stitches_when_single_capture_fails_q22(monkeypatch):
    """单张 captureBeyondViewport 被拒（"Unable to capture screenshot"）
    时，自动改走滚动拼接。"""
    from ashot import cdp as cdp_mod
    state = {"scroll": 0}

    def fake_call(ws, method, params=None, timeout=30):
        if method == "Page.captureScreenshot":
            if params.get("captureBeyondViewport"):
                raise RuntimeError("Unable to capture screenshot")
            return {"data": base64.b64encode(
                _band_png(50, 50, state["scroll"] // 50)).decode()}
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if "scrollTop=" in expr:
                y = int(expr.split("scrollTop=")[1].split(";")[0])
                state["scroll"] = y
                return {"result": {"value": y}}
            return {"result": {"value": state["scroll"]}}
        raise AssertionError(method)

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    monkeypatch.setattr(cdp_mod, "layout", lambda ws, timeout=15: (
        {"vw": 50, "vh": 50, "content_w": 50, "content_h": 200,
         "scroll_y": 0}, 1))
    png, info = cdp_mod.shot(9222, ws="ws://x")
    assert info["stitched"] is True and info["h"] == 200 and info["shots"] == 4
    # stitch=False 时如实抛出，不静默吞
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        cdp_mod.shot(9222, ws="ws://x", stitch=False)

def test_preview_caps_height_for_long_pages_q16():
    """超长页预览：只按宽度缩仍会出 2.8MB 的"缩图"（实弹），必须同时限高。"""
    tall = output.bgra_to_png(746, 20000, b"\x20\x40\x60\xff" * (746 * 20000))
    jpeg, info = output.preview_jpeg(tall)
    assert info["height"] <= 4000, info
    assert info["width"] <= 746
    assert info["bytes"] <= output.PREVIEW_MAX_BYTES_DEFAULT and info["fit"] is True, info

# ---------- v0.2.7 通用视觉 / DOM 原语 ----------

def _solid(w, h, rgb=(40, 80, 120)):
    return output.bgra_to_png(w, h, bytes([rgb[2], rgb[1], rgb[0], 255]) * (w * h))


def _with_block(w, h, x, y, bw, bh, rgb2=(255, 0, 0)):
    base = bytes([120, 80, 40, 255]) * (w * h)
    px = bytearray(base)
    for yy in range(y, min(y + bh, h)):
        for xx in range(x, min(x + bw, w)):
            i = (yy * w + xx) * 4
            px[i:i + 4] = bytes([rgb2[2], rgb2[1], rgb2[0], 255])
    return output.bgra_to_png(w, h, bytes(px))


def test_vision_digest_and_stability():
    """指纹：sha 精确、dhash 对整体亮度平移稳定、改内容 dhash 变。"""
    from ashot import vision
    a = _solid(120, 80, (40, 80, 120))
    b = _solid(120, 80, (80, 120, 160))          # 整体变亮
    c = _with_block(120, 80, 50, 30, 30, 20)        # 内容变化（块够大）
    da, db, dc = vision.digest(a), vision.digest(b), vision.digest(c)
    assert da["sha256"] != db["sha256"]
    assert da["dhash"] == db["dhash"], "整体亮度平移不该改变 dHash"
    assert da["dhash"] != dc["dhash"], "内容变化 dHash 必须变"
    assert vision.hamming(da["dhash"], da["dhash"]) == 0
    assert 0 < vision.hamming(da["dhash"], dc["dhash"]) <= 64


def test_vision_diff_identical_and_bbox():
    """diff：同图 same/ratio=0；单点变化 ratio 精确、bbox 精确。"""
    from ashot import vision
    a = _solid(100, 50)
    b = _with_block(100, 50, 30, 20, 2, 2)
    r0 = vision.diff(a, a)
    assert r0["same"] is True and r0["ratio"] == 0 and r0["bbox"] is None
    r = vision.diff(a, b)
    assert r["same"] is False and r["changed_px"] == 4
    assert r["ratio"] == round(4 / 5000.0, 6)
    assert r["bbox"] == [30, 20, 2, 2]
    jpeg_like = vision.diff(a, b, make_image=True)
    _, _, px = annotate._decode_png(jpeg_like["image"])
    i = (20 * 100 + 30) * 4
    assert (px[i], px[i + 1], px[i + 2]) == (255, 0, 0), "差异图像素不是红色"


def test_vision_diff_size_mismatch():
    """尺寸不同：只比重叠区，same 恒 False，并如实标 size_mismatch。"""
    from ashot import vision
    a = _solid(100, 50)
    b = _solid(80, 40)
    r = vision.diff(a, b)
    assert r["size_mismatch"] is True and r["same"] is False
    assert r["dims"] == [[100, 50], [80, 40]]
    assert "尺寸不同" in r["note"]


def test_dom_element_rect_stub(monkeypatch):
    """element_rect：字段归一（local→x/y）、中心点、选择器 JSON 转义。"""
    from ashot import cdp as cdp_mod
    from ashot import dom
    seen = {}
    payload = {"found": True, "tag": "button", "text": "ok",
               "local_x": 100, "local_y": 50, "w": 80, "h": 40,
               "visible": True, "visibility_source": "checkVisibility",
               "in_viewport": True, "visible_ratio": 1.0, "occluded": False,
               "pointer_events": "auto", "dpr": 2, "scroll_x": 0,
               "scroll_y": 10, "doc_scroll_h": 900}

    def fake_call(ws, method, params=None, timeout=15):
        seen["expr"] = params.get("expression", "")
        seen["await"] = params.get("awaitPromise")
        return {"result": {"value": payload}}

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    rec = dom.element_rect("ws://x", 'a[href="q"]')
    assert rec["x"] == 100 and rec["y"] == 50 and rec["cx"] == 140
    assert rec["cy"] == 70 and rec["dpr"] == 2
    assert '"a[href=\\"q\\"]"' in seen["expr"], seen["expr"][:120]
    assert "checkVisibility" in seen["expr"] and "elementFromPoint" in seen["expr"]
    assert "in_viewport" in seen["expr"]


def test_dom_element_rect_not_found(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import dom
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": {"found": False,
                                                             "error": "nope"}}})
    import pytest as _pytest
    with _pytest.raises(RuntimeError) as ei:
        dom.element_rect("ws://x", "#missing")
    assert "未找到" in str(ei.value)


def test_dom_element_rect_scroll(monkeypatch):
    """scroll=True：先 awaitPromise 的 scrollIntoView，再量一次。"""
    from ashot import cdp as cdp_mod
    from ashot import dom
    calls = []

    def fake_call(ws, method, params=None, timeout=15):
        calls.append(params.get("awaitPromise"))
        if len(calls) == 1:
            return {"result": {"value": {"found": True}}}
        return {"result": {"value": {"found": True, "local_x": 0, "local_y": 0,
                                     "w": 10, "h": 10, "visible": True}}}

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    dom.element_rect("ws://x", "#a", scroll=True)
    assert calls == [True, False]


def test_dom_cross_origin_frame_map(monkeypatch):
    """跨域同进程：一个 Session 内 isolated world 求值 + 内容原点相加。"""
    from ashot import cdp as cdp_mod
    from ashot import dom
    inner = {"found": True, "local_x": 20, "local_y": 10, "w": 100, "h": 40,
             "visible": True, "in_viewport": True}

    class FakeSession:
        def __init__(self, ws, timeout=30):
            self.ws = ws

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, method, params=None, session_id=None):
            if method == "Runtime.evaluate":
                if params.get("contextId") == 5:
                    return {"result": {"value": inner}}
                return {"result": {"value": {"found": False,
                                             "cross_origin": True}}}
            return {
                "DOM.enable": {},
                "DOM.getDocument": {"root": {"nodeId": 1}},
                "DOM.querySelector": {"nodeId": 7},
                "DOM.describeNode": {"node": {"frameId": "F1"}},
                "DOM.getBoxModel": {"model": {"content": [105, 505, 405, 505,
                                                          405, 705, 105, 705]}},
                "Page.createIsolatedWorld": {"executionContextId": 5},
            }[method]

    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": {"found": False,
                                                             "cross_origin": True,
                                                             "chain": [{"selector": "#f"}]}}})
    monkeypatch.setattr(cdp_mod, "Session", FakeSession)
    rec = dom.frame_element_rect("ws://x", "#f", "#inner")
    assert rec["cross_origin"] is True
    assert rec["x"] == 125 and rec["y"] == 515
    assert rec["cx"] == 175 and rec["cy"] == 535
    assert rec["frame_chain"][0]["cross_origin"] is True


def test_dom_oopif_reports_unsupported(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import dom
    import pytest as _pytest

    class FakeSession:
        def __init__(self, ws, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, method, params=None, session_id=None):
            if method == "Page.createIsolatedWorld":
                raise RuntimeError("target detached / OOPIF")
            if method == "Target.getTargets":
                return {"targetInfos": []}
            return {
                "DOM.enable": {},
                "DOM.getDocument": {"root": {"nodeId": 1}},
                "DOM.querySelector": {"nodeId": 7},
                "DOM.describeNode": {"node": {"frameId": "F2"}},
                "DOM.getBoxModel": {"model": {"content": [10, 20, 30, 20, 30, 40,
                                                          10, 40]}},
            }[method]

    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": {"found": False,
                                                             "cross_origin": True}}})
    monkeypatch.setattr(cdp_mod, "Session", FakeSession)
    with _pytest.raises(RuntimeError) as ei:
        dom.frame_element_rect("ws://x", "#f", "#inner")
    assert "oopif_unsupported" in str(ei.value)


def test_dom_oopif_attach_maps(monkeypatch):
    """跨站 OOPIF：createIsolatedWorld 失败 → Target.attachToTarget（flatten）
    → 带 sessionId 求值 → 与 iframe 内容原点相加。"""
    from ashot import cdp as cdp_mod
    from ashot import dom

    class FakeSession:
        def __init__(self, ws, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, method, params=None, session_id=None):
            if method == "Page.createIsolatedWorld":
                raise RuntimeError("No frame for given id found")
            if method == "Target.getTargets":
                return {"targetInfos": [{"type": "iframe", "targetId": "F2",
                                         "url": "https://example.com/"}]}
            if method == "Target.attachToTarget":
                return {"sessionId": "S1"}
            if method == "Runtime.evaluate" and session_id == "S1":
                return {"result": {"value": {"found": True, "local_x": 5,
                                             "local_y": 6, "w": 10, "h": 10}}}
            if method == "Runtime.evaluate":
                return {"result": {"value": {"found": False,
                                             "cross_origin": True}}}
            return {
                "DOM.enable": {},
                "DOM.getDocument": {"root": {"nodeId": 1}},
                "DOM.querySelector": {"nodeId": 7},
                "DOM.describeNode": {"node": {"frameId": "F2"}},
                "DOM.getBoxModel": {"model": {"content": [100, 200, 300, 200,
                                                          300, 300, 100, 300]}},
                "Target.detachFromTarget": {},
            }[method]

    monkeypatch.setattr(cdp_mod, "Session", FakeSession)
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": {"found": False,
                                                             "cross_origin": True}}})
    rec = dom.frame_element_rect("ws://x", "#f", "#inner")
    assert rec["oopif"] is True
    assert rec["x"] == 105 and rec["y"] == 206
    assert rec["cx"] == 110 and rec["cy"] == 211


def test_dom_frames_flat(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import dom
    tree = {"frameTree": {"frame": {"id": "root", "url": "https://a/"},
                          "childFrames": [
                              {"frame": {"id": "c1", "url": "https://b/",
                                         "name": "f1"}}]}}

    class FakeSession:
        def __init__(self, ws, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, method, params=None):
            return {
                "DOM.enable": {},
                "Page.getFrameTree": tree,
                "DOM.getFrameOwner": {"backendNodeId": 9},
                "DOM.getBoxModel": {"model": {"content": [100, 200, 300, 200,
                                                          300, 400, 100, 400]}},
            }[method]

    monkeypatch.setattr(cdp_mod, "Session", FakeSession)
    fs = dom.frames("ws://x")
    assert [f["id"] for f in fs] == ["root", "c1"]
    assert fs[1]["parent_id"] == "root" and fs[1]["depth"] == 1
    assert fs[1]["rect"] == {"x": 100, "y": 200, "w": 200, "h": 200}


def test_cli_hash_and_diff(tmp_path):
    import subprocess
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(_solid(60, 40))
    b.write_bytes(_with_block(60, 40, 10, 10, 3, 3))
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "hash", str(a)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert len(rec["sha256"]) == 64 and rec["dhash"].startswith("0x")
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "diff", str(a), str(b)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert rec["same"] is False and rec["changed_px"] == 9

def test_clip_to_visible_v028(monkeypatch):
    """frame 内元素：与主视口/iframe 内容框求交，别把 iframe 外算成可见。"""
    from ashot import dom
    monkeypatch.setattr(dom, "_eval_raw",
                        lambda *a, **k: {"vw": 1000, "vh": 700})
    rec = {"x": 900, "y": 100, "w": 200, "h": 50}
    out = dom._clip_to_visible("ws", dict(rec), [], 5)
    assert out["visible_ratio"] == 0.5 and out["clipped_by_frame"] is True
    assert out["in_viewport"] is True

    rec2 = {"x": 0, "y": 0, "w": 100, "h": 100}
    chain = [{"content_x": 0, "content_y": 0, "content_w": 50, "content_h": 50}]
    out2 = dom._clip_to_visible("ws", dict(rec2), chain, 5)
    assert out2["visible_ratio"] == 0.25
    assert out2["clipped_by_frame"] is True


def test_hide_fixed_elements_v028(monkeypatch):
    """拼接前隐藏 fixed/sticky，拍完还原（v0.2.8）。"""
    from ashot import cdp as cdp_mod
    seen = []

    def fake_call(ws, method, params=None, timeout=10):
        expr = params.get("expression", "")
        seen.append(expr)
        if "position" in expr:
            return {"result": {"value": 3}}
        return {"result": {"value": 3}}

    monkeypatch.setattr(cdp_mod, "call", fake_call)
    n = cdp_mod._hide_fixed("ws://x")
    assert n == 3
    assert "fixed" in seen[0] and "sticky" in seen[0] and "data-ashot-vis" in seen[0]
    cdp_mod._restore_fixed("ws://x")
    assert "data-ashot-vis" in seen[1] and "removeAttribute" in seen[1]


# ---------- v0.5.0：JPEG 输入 / dpr / info / 批量 ----------

def _jpeg_of(png, quality=85):
    from ashot import transform
    data, _info = transform.apply(png, fmt="jpeg", quality=quality)
    return data


def test_imageio_jpeg_to_png():
    """JPEG 输入归一化成 PNG（GDI+ 转码），尺寸不变。"""
    from ashot import imageio
    png = _solid(120, 80)
    jpg = _jpeg_of(png)
    assert jpg[:2] == b"\xff\xd8"
    out = imageio.to_png(jpg)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert output.image_size(out) == (120, 80)
    assert imageio.format_of(jpg) == "jpeg"
    assert imageio.format_of(png) == "png"


def test_transform_passthrough_requires_png():
    """JPEG 不能走 PNG 的零拷贝快路径（旧实现会交 JPEG 冒充 PNG）。"""
    from ashot import transform
    png = _solid(60, 40)
    jpg = _jpeg_of(png)
    out, info = transform.apply(jpg, fmt="png")
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert info["engine"] != "passthrough"


def test_annotate_scale_ops_dpr():
    """dpr 只缩放坐标，不缩放字号/线宽；points/coords 一并缩放。"""
    from ashot import annotate
    ops = [{"kind": "rect", "x": 10, "y": 20, "w": 30, "h": 40, "width": 6},
           {"kind": "text", "x": 5, "y": 6, "text": "t", "size": 28},
           {"kind": "polyline", "coords": "1,2,3,4"},
           {"kind": "rect", "area": "10,20,30,40"},
           {"kind": "rect", "x": "10", "y": "20", "w": "30", "h": "40"}]
    out = annotate.scale_ops(ops, 1.5)
    assert out[0]["x"] == 15 and out[0]["w"] == 45 and out[0]["width"] == 6
    assert out[1]["size"] == 28
    assert out[2]["coords"] == "1.5,3,4.5,6"
    assert out[3]["area"] == "15,30,45,60"
    assert out[4]["x"] == 15 and out[4]["h"] == 60
    import pytest as _pytest
    with _pytest.raises(ValueError):
        annotate.scale_ops(ops, 0)


def test_cli_annotate_jpeg_with_dpr(tmp_path):
    """annotate 直接吃 JPEG，且 --dpr 生效（输出仍是 PNG）。"""
    src = tmp_path / "a.jpg"
    src.write_bytes(_jpeg_of(_solid(100, 50)))
    out = tmp_path / "o.png"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "annotate",
                        str(src), '[{"kind":"rect","x":5,"y":5,"w":10,'
                        '"h":10,"width":2,"color":"#FF0000"}]',
                        "--dpr", "2", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cli_hash_jpeg(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(_jpeg_of(_solid(80, 60)))
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "hash", str(src)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert (rec["w"], rec["h"]) == (80, 60)


def test_cli_info_png_jpeg(tmp_path):
    png = tmp_path / "a.png"; png.write_bytes(_solid(30, 20))
    jpg = tmp_path / "a.jpg"; jpg.write_bytes(_jpeg_of(_solid(40, 10)))
    for path, want in ((png, (30, 20)), (jpg, (40, 10))):
        r = subprocess.run([sys.executable, "-m", "ashot.cli", "info", str(path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT)
        assert r.returncode == 0, r.stderr
        rec = json.loads(r.stdout)
        assert (rec["w"], rec["h"]) == want
    assert rec["format"] == "jpeg"
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not an image")
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "info", str(bad)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 1, "info 对非图片必须非零退出"
    assert "不是可识别" in r.stderr


def test_cli_resize_dir_batch(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    (src / "a.png").write_bytes(_solid(200, 100))
    (src / "a.jpg").write_bytes(_jpeg_of(_solid(120, 40)))   # 同名且不同宽高比
    (src / "b.jpg").write_bytes(_jpeg_of(_solid(100, 80)))
    dst = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize",
                        "--dir", str(src), "--out-dir", str(dst),
                        "--max-side", "50"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert (dst / "a.png").is_file() and (dst / "b.png").is_file()
    assert (dst / "a-2.png").is_file(), "同名不同扩展不能互相覆盖"
    sizes = {p.name: output.image_size(p.read_bytes())
             for p in dst.iterdir() if p.is_file()}
    # 排序后 a.jpg 先进，占 a.png（50x17）；a.png 落到 a-2.png（50x25）
    assert sizes["a.png"] == (50, 17)
    assert sizes["a-2.png"] == (50, 25)

    # 重跑：应覆盖旧产物，而不是继续 -2/-3 堆陈图
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize",
                        "--dir", str(src), "--out-dir", str(dst),
                        "--max-side", "40"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert not (dst / "a-3.png").exists(), "重跑不该堆新后缀"
    assert output.image_size((dst / "a.png").read_bytes()) == (40, 13)
    assert output.image_size((dst / "a-2.png").read_bytes()) == (40, 20)


def test_cli_resize_dir_failure_keeps_going(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    (src / "good.png").write_bytes(_solid(60, 30))
    (src / "bad.jpg").write_bytes(b"\xff\xd8broken")
    dst = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "ashot.cli", "resize",
                        "--dir", str(src), "--out-dir", str(dst),
                        "--max-side", "30"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    assert r.returncode == 1, "有失败必须非零退出"
    assert (dst / "good.png").is_file(), "单张失败不拖垮其余"
    assert "1 成功 / 1 失败" in r.stderr


# ---------- v0.6.0：结构化快照 / selector / 预览坐标映射 ----------

def test_dom_snapshot_stub(monkeypatch):
    """snapshot：树格式化 + refs 映射（不靠像素猜坐标）。"""
    from ashot import cdp as cdp_mod
    from ashot import dom
    payload = {
        "tree": {"role": "body", "name": "", "ref": None, "box": None,
                 "kids": [{"role": "button", "name": "提交", "ref": "e1",
                           "box": [10, 20, 80, 32], "kids": []}]},
        "refs": {"e1": {"selector": "#submit", "tag": "button",
                        "text": "提交", "rect": [10, 20, 80, 32]}},
        "count": 1, "url": "https://x/", "title": "t", "dpr": 1.5,
        "scroll": [0, 0]}
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": payload}})
    rec = dom.snapshot("ws://x")
    assert 'button "提交" [ref=e1] [box=10,20,80,32]' in rec["tree"]
    assert rec["refs"]["e1"]["selector"] == "#submit"
    assert rec["count"] == 1 and rec["dpr"] == 1.5


def test_apply_selectors_stub(monkeypatch):
    """selector/ref → 物理像素；pad 外扩；箭头拒绝（语义未定）。"""
    from ashot import dom
    rect = {"x": 10, "y": 20, "w": 100, "h": 40, "dpr": 1.5}
    monkeypatch.setattr(dom, "element_rect",
                        lambda ws, sel, timeout=15: dict(rect))
    ops = [{"kind": "rect", "selector": "#a", "width": 3},
           {"kind": "text", "selector": "#a", "text": "t", "size": 12},
           {"kind": "rect", "ref": "e1", "pad": 2}]
    out = dom.apply_selectors("ws://x", ops, refs={"e1": {"selector": "#b"}})
    assert (out[0]["x"], out[0]["y"], out[0]["w"], out[0]["h"]) == (
        15, 30, 150, 60)
    assert (out[1]["x"], out[1]["y"]) == (15, 30)
    assert (out[2]["x"], out[2]["w"]) == (15, 150)   # pad 交给 apply_pad
    padded = vector.apply_pad(out)
    assert (padded[2]["x"], padded[2]["w"]) == (13, 154)
    import pytest as _pytest
    with _pytest.raises(ValueError):
        dom.apply_selectors("ws://x", [{"kind": "arrow", "selector": "#a",
                                        "x1": 1, "y1": 2, "x2": 3, "y2": 4}])


def test_preview_to_source_mapping():
    """预览收据带源图尺寸与换算系数（模型看图坐标可回到源图）。"""
    big = output.bgra_to_png(800, 600, bytes([0, 0, 255, 255]) * 480000)
    jpeg, info = output.preview_jpeg(big)
    assert info["src"][0] == 800
    assert info["to_source"] == round(800 / float(info["width"]), 4)


def test_apply_selectors_dpr_no_double():
    """selector 已乘页面 dpr；全局 dpr 不得再乘（审查 P1-3）。"""
    from ashot import dom
    import pytest as _pytest
    monkeypatch_rect = {"x": 10, "y": 20, "w": 100, "h": 40, "dpr": 1.5,
                        "scroll_x": 0, "scroll_y": 0}
    old = dom.element_rect
    dom.element_rect = lambda ws, sel, timeout=15: dict(monkeypatch_rect)
    try:
        out = dom.apply_selectors("ws", [{"kind": "rect",
                                          "selector": "#a", "dpr": 1.5}])
        assert out[0]["x"] == 15 and out[0]["w"] == 150
        scaled = annotate.scale_ops(out, 1.5)
        assert scaled[0]["x"] == 15 and scaled[0]["w"] == 150, \
            "已 resolved 的 op 不能再乘 dpr"
    finally:
        dom.element_rect = old


def test_apply_selectors_document_space():
    """space=document 时加 scroll×dpr（整页截图用）。"""
    from ashot import dom
    rect = {"x": 10, "y": 20, "w": 100, "h": 40, "dpr": 2,
            "scroll_x": 10, "scroll_y": 30}
    old = dom.element_rect
    dom.element_rect = lambda ws, sel, timeout=15: dict(rect)
    try:
        out = dom.apply_selectors("ws", [{"kind": "rect", "selector": "#a"}],
                                  space="document")
        assert (out[0]["x"], out[0]["y"]) == (40, 100)
        out2 = dom.apply_selectors("ws", [{"kind": "rect", "selector": "#a"}])
        assert (out2[0]["x"], out2[0]["y"]) == (20, 40)
    finally:
        dom.element_rect = old


def test_apply_selectors_ref_without_cache():
    """CLI 无 refs 缓存时必须明确拒绝（别误导成"先 snapshot"）。"""
    from ashot import dom
    import pytest as _pytest
    with _pytest.raises(ValueError) as ei:
        dom.apply_selectors("ws", [{"kind": "rect", "ref": "e1"}])
    assert "没有快照缓存" in str(ei.value) or "CLI 不支持 ref" in str(ei.value)


def test_snapshot_truncated_flag(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import dom
    payload = {"tree": {"role": "body", "name": "", "kids": [],
                        "ref": None, "box": None},
               "refs": {}, "count": 0, "truncated": True,
               "url": "https://x/", "title": "t", "dpr": 1, "scroll": [0, 0]}
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": payload}})
    rec = dom.snapshot("ws://x", max_nodes=10000)
    assert rec["truncated"] is True


def test_preview_to_source_tall():
    """超高图触发 max_height 分支，to_source 仍正确。"""
    tall = output.bgra_to_png(400, 8000, bytes([0, 0, 255, 255]) * (400 * 8000))
    jpeg, info = output.preview_jpeg(tall)
    assert info["height"] <= 4000
    assert info["to_source"] == round(400 / float(info["width"]), 4)
    assert info["src"] == [400, 8000]


def test_drag_moves_carry_left_button():
    """拖拽移动事件必须带 button=left（原生 range 只认这个；v0.6.2）。"""
    from ashot import cdp as cdp_mod
    for human in (False, True):
        seq = cdp_mod.drag_events(10, 10, 210, 10, steps=4, human=human, seed=1)
        moves = [e for e in seq if e["type"] == "mouseMoved"][1:]
        assert moves and all(e.get("button") == "left" for e in moves), human
        assert all(e.get("buttons") == 1 for e in moves), human


def _red_bbox_v062(png_bytes):
    w, h, px = annotate._decode_png(png_bytes)
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if px[i] > 200 and px[i + 1] < 80 and px[i + 2] < 80:
                xs.append(x); ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def test_pad_without_selector_v062():
    """pad 对坐标型矩形族也生效（旧实现只对 selector 生效，静默吞掉）。"""
    png = _solid(200, 100)
    out = annotate.annotate_png(png, [{"kind": "rect", "x": 50, "y": 30,
                                       "w": 40, "h": 20, "width": 2,
                                       "pad": 5, "color": "#FF0000"}])
    bbox = _red_bbox_v062(out)
    # 像素路线宽 2 会向两侧各溢 1px；中心几何必须是 45,25..95,55
    assert 43 <= bbox[0] <= 46 and 23 <= bbox[1] <= 26, bbox
    assert 94 <= bbox[2] <= 97 and 54 <= bbox[3] <= 57, bbox
    assert bbox[2] - bbox[0] >= 49 and bbox[3] - bbox[1] >= 30, bbox


def test_unknown_op_field_rejected():
    """拼错字段不再静默吞（未知字段直接报错）。"""
    import pytest as _pytest
    png = _solid(40, 20)
    with _pytest.raises(ValueError) as ei:
        annotate.annotate_png(png, [{"kind": "rect", "x": 1, "y": 1, "w": 5,
                                     "h": 5, "colour": "#FF0000"}])
    assert "未知 op 字段" in str(ei.value)
    with _pytest.raises(ValueError):
        annotate.annotate_png(png, [{"kind": "arrow", "x1": 0, "y1": 0,
                                     "x2": 5, "y2": 5, "pad": 3}])


def test_scrollables_stub(monkeypatch):
    from ashot import cdp as cdp_mod
    payload = [{"tag": "div", "id": "sc", "scroll_h": 1000,
                "client_h": 100, "scroll_top": 0}]
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": payload}})
    rec = cdp_mod.scrollables("ws://x")
    assert rec[0]["scroll_h"] == 1000


def test_arc_end_alias_passes_whitelist():
    """文档化写法 arc.end（及 *_angle 别名）不能被白名单误杀。"""
    png = _solid(120, 120)
    for op in ({"kind": "arc", "x": 10, "y": 10, "w": 80, "h": 80,
                "start": 0, "end": 90, "width": 2, "color": "#FF0000"},
               {"kind": "arc", "x": 10, "y": 10, "w": 80, "h": 80,
                "start_angle": 0, "end_angle": 90, "width": 2,
                "color": "#FF0000"}):
        out = annotate.annotate_png(png, [op])
        assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_negative_pad_rejected():
    import pytest as _pytest
    png = _solid(50, 30)
    with _pytest.raises(ValueError) as ei:
        annotate.annotate_png(png, [{"kind": "rect", "x": 5, "y": 5,
                                     "w": 10, "h": 10, "pad": -2}])
    assert "pad 必须" in str(ei.value)


def test_string_op_pad_and_validation():
    """字符串 op 也要过 pad/字段校验（旧实现直接绕过）。"""
    png = _solid(100, 60)
    out = annotate.annotate_png(
        png, ['{"kind":"rect","x":20,"y":10,"w":20,"h":10,"pad":5,'
              '"width":2,"color":"#FF0000"}'])
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    import pytest as _pytest
    with _pytest.raises(ValueError):
        annotate.annotate_png(
            png, ['{"kind":"rect","x":1,"y":1,"w":5,"h":5,"colour":"#f00"}'])


def test_scrollables_raises_on_eval_error(monkeypatch):
    from ashot import cdp as cdp_mod
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"exceptionDetails":
                                         {"text": "boom"}})
    import pytest as _pytest
    with _pytest.raises(RuntimeError) as ei:
        cdp_mod.scrollables("ws://x")
    assert "scrollables" in str(ei.value)


def test_tool_descriptions_v063():
    from ashot import mcp as mcp_mod
    view = mcp_mod.TOOLS["ashot_cdp_view"]["description"]
    assert "scrollables" in view
    ann = mcp_mod.TOOLS["ashot_annotate"]["description"]
    assert "pad" in ann and "白名单" in ann
    drag = mcp_mod.TOOLS["ashot_cdp_drag"]["description"]
    assert "range" in drag
    shot_d = mcp_mod.TOOLS["ashot_cdp_shot"]["description"]
    assert "activate" in shot_d and "url_sub" in shot_d
    click_d = mcp_mod.TOOLS["ashot_cdp_click"]["description"]
    assert "slow_ack" in click_d and "per_event_ms" in click_d


def test_ws_for_url_sub(monkeypatch):
    """url_sub 按 URL 选页，比 index 稳（v0.7.0）。"""
    from ashot import cdp as cdp_mod
    monkeypatch.setattr(cdp_mod, "tabs", lambda port: [
        {"url": "https://a/", "ws": "wa"},
        {"url": "https://b/search?q=x", "ws": "wb"}])
    assert cdp_mod.ws_for(1, index=0, url_sub="b/search") == "wb"
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        cdp_mod.ws_for(1, url_sub="nope")


def test_dispatch_stats(monkeypatch):
    """dispatch 必须回报 events/dispatch_ms/max_event_ms（定位 40s 问题）。"""
    from ashot import cdp as cdp_mod

    class FakeSession:
        def __init__(self, ws, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, method, params=None):
            return {}

    monkeypatch.setattr(cdp_mod, "Session", FakeSession)
    stats = {}
    n, _ = cdp_mod.dispatch("ws", [{"type": "mouseMoved", "x": 1, "y": 2},
                                   {"type": "mousePressed", "x": 1, "y": 2}],
                            realtime=False, stats=stats)
    assert n == 2
    assert stats["events"] == 2
    assert "dispatch_ms" in stats and "max_event_ms" in stats


def test_snapshot_truncated_at(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import dom
    payload = {"tree": {"role": "body", "name": "", "kids": [],
                        "ref": None, "box": None},
               "refs": {}, "count": 0, "truncated": True,
               "truncated_at": {"refs": 0, "nodes": 12, "depth": 12,
                                "last_selector": "body > div"},
               "url": "https://x/", "title": "t", "dpr": 1, "scroll": [0, 0]}
    monkeypatch.setattr(cdp_mod, "call",
                        lambda *a, **k: {"result": {"value": payload}})
    rec = dom.snapshot("ws://x")
    assert rec["truncated_at"]["nodes"] == 12
    assert rec["truncated_at"]["last_selector"] == "body > div"


def test_cdp_dblclick_handler_v071(monkeypatch):
    """P0 回归：dblclick 签名缺 activate/url_sub 会 NameError。"""
    from ashot import cdp as cdp_mod
    from ashot import mcp as mcp_mod
    import json as _json
    monkeypatch.setattr(mcp_mod, "_resolve_ws", lambda *a, **k: "ws")
    monkeypatch.setattr(cdp_mod, "page_visibility", lambda ws: "visible")
    monkeypatch.setattr(cdp_mod, "dispatch", lambda *a, **k: (3, []))
    rec = _json.loads(mcp_mod._cdp_dblclick(1, 1))
    assert rec["ok"] and rec["dispatched"] == 3


def test_drag_hint_only_when_clipped(monkeypatch):
    """drag 收据：clipped_ms=0 不得有「被夹断」hint；真夹断才给。"""
    from ashot import cdp as cdp_mod
    from ashot import mcp as mcp_mod
    import json as _json
    monkeypatch.setattr(mcp_mod, "_resolve_ws", lambda *a, **k: "ws")
    monkeypatch.setattr(cdp_mod, "page_visibility", lambda ws: "visible")
    monkeypatch.setattr(cdp_mod, "drag_events",
                        lambda *a, **k: [{"type": "mouseMoved"}])

    def fake_dispatch(ws, seq, realtime=True, stats=None):
        stats["clipped_ms"] = 0.0
        stats["dispatch_ms"] = 10.0
        stats["max_event_ms"] = 5.0
        return 1, []

    monkeypatch.setattr(cdp_mod, "dispatch", fake_dispatch)
    rec = _json.loads(mcp_mod._cdp_drag(0, 0, 10, 0))
    assert "hint" not in rec and rec["clipped_ms"] == 0.0

    def slow_dispatch(ws, seq, realtime=True, stats=None):
        stats["clipped_ms"] = 500.0
        stats["dispatch_ms"] = 5000.0
        stats["max_event_ms"] = 4500.0
        return 1, []

    monkeypatch.setattr(cdp_mod, "dispatch", slow_dispatch)
    rec = _json.loads(mcp_mod._cdp_drag(0, 0, 10, 0))
    assert "hint" in rec and rec["slow_ack"] is True


def test_cdp_type_handler_v072(monkeypatch):
    """type 也要有 activate/url_sub 与计时收据（此前完全裸奔）。"""
    from ashot import cdp as cdp_mod
    from ashot import mcp as mcp_mod
    import json as _json
    monkeypatch.setattr(mcp_mod, "_resolve_ws", lambda *a, **k: "ws")
    monkeypatch.setattr(cdp_mod, "page_visibility", lambda ws: "visible")

    def fake_dispatch(ws, seq, realtime=True, stats=None):
        stats["dispatch_ms"] = 20.0
        stats["max_event_ms"] = 10.0
        stats["planned_ms"] = 0.0
        return len(seq), []

    monkeypatch.setattr(cdp_mod, "dispatch", fake_dispatch)
    rec = _json.loads(mcp_mod._cdp_type("hello"))
    assert rec["dispatched"] == 1
    assert rec["per_event_ms"] == 20.0
    assert "slow_ack" not in rec


def test_cdp_tabs_url_sub_filter(monkeypatch):
    from ashot import cdp as cdp_mod
    from ashot import mcp as mcp_mod
    import json as _json
    monkeypatch.setattr(cdp_mod, "tabs", lambda port: [
        {"id": "1", "title": "A", "url": "https://a/"},
        {"id": "2", "title": "B", "url": "https://b/search?q=x"}])
    rec = _json.loads(mcp_mod._cdp_tabs(port=1, url_sub="b/search"))
    assert [t["id"] for t in rec["tabs"]] == ["2"]
    assert rec["filter"] == "b/search"
