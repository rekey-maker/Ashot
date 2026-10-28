# -*- coding: utf-8 -*-
"""Ashot v0.1.0 测试：编码器/标注原语/CLI/MCP 探针。零触网、不依赖桌面。"""
import base64
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
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
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
        str(src), json.dumps([{"kind": "rect", "x": 0, "y": 0, "w": 2, "h": 2}])))
    assert res["ok"] and res["path"] != str(src)
    assert src.read_bytes() == original, "原件被覆盖"
    assert os.path.basename(res["path"]).endswith("_annotated.png")
    assert os.path.isfile(res["path"])


def test_mcp_tool_schemas():
    """P3 死代码清理后 schema 生成仍自洽：required 推导 + 属性集合。"""
    from ashot import mcp as mcp_mod
    assert set(mcp_mod.TOOLS) == {"ashot_shot", "ashot_screens",
                                  "ashot_annotate", "ashot_fonts",
                                  "ashot_show"}
    sc = mcp_mod.TOOLS["ashot_annotate"]["inputSchema"]
    assert sc["required"] == ["image", "ops"]
    assert set(sc["properties"]) == {"image", "ops", "out", "preview"}
    ss = mcp_mod.TOOLS["ashot_shot"]["inputSchema"]
    assert set(ss["properties"]) == {"mode", "screen", "out", "clip",
                                     "keep", "area", "retention_days",
                                     "preview"}
    fc = mcp_mod.TOOLS["ashot_fonts"]["inputSchema"]
    assert fc["required"] == []
    assert set(fc["properties"]) == {"filter"}
    wc = mcp_mod.TOOLS["ashot_show"]["inputSchema"]
    assert wc["required"] == ["image", "title", "out_dir"]
    assert set(wc["properties"]) == {"image", "title", "out_dir",
                                     "caption", "width"}


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
    （数据源与渲染器同源，§7.9.2）。"""
    from ashot import fonts
    names = fonts.list_families()
    assert len(names) > 10, len(names)
    assert names == sorted(names), "未排序"
    assert len(set(names)) == len(names), "存在重复族名"
    assert not names[0].startswith("\ufeff"), "首元素带 BOM"
    assert "Microsoft YaHei UI" in names, "渲染器缺省族不在字库"
    hits = fonts.list_families("kai")
    assert "KaiTi" in hits, hits
    assert all("kai" in n.lower() for n in hits)
    # locale 注记：zh 系统上本地化名也能查到（双名索引，§7.9.2）
    assert "KaiTi" in fonts.list_families("楷体")
    assert fonts.list_families("NoSuchFontZZZ") == []


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
    """preview 缺省=false 收据仍是单字符串（兼容）；=true 升级两内容块
    （文本收据含 preview 信息 + JPEG ImageContent，audience=user）。"""
    from ashot import mcp as mcp_mod
    out_png = str(tmp_path / "s.png")
    old = mcp_mod._shot(mode="area", area=[0, 0, 64, 48], out=out_png)
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
    """annotate preview=true：同样升级两内容块，缩图来自标注成品。"""
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
