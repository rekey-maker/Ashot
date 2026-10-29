# -*- coding: utf-8 -*-
"""Ashot.annotate —— 标注（七件绘制原语 + C 命令行形态；B 交互窗 v0.2 预留）。

模块纪律：不 import capture（对任意既有图片可用）；渲染走纯标准库
zlib/struct 手写 PNG（与 output 同款编码器思路），不依赖 PIL。

原语（ops JSON 数组的 kind）——形状七件：
  rect  x,y,w,h [color] [width] [radius]  矩形框（radius>0 圆角描边）
  ellipse x,y,w,h [color] [width]    椭圆框
  arrow  x1,y1,x2,y2 [color] [width] [style]  箭头——v0.1.6 缺省渐变实心
                                     （尾细头胖+三角头，微信截图风格，
                                     用户裁决）；style="line" 回退旧直杆
  line   x1,y1,x2,y2 [color] [width] 直线
  curve  x0,y0,c1x,c1y,c2x,c2y,x1,y1 三次贝塞尔（v0.4.1：采样成折线，
                                     与箭头同一条矢量原理）
  arc    x,y,w,h,start,sweep        椭圆弧（度、顺时针；sweep 可负）
  polyline points=[[x,y],...]       折线（或 coords="x1,y1,x2,y2,..."）
  text   x,y:内容 [color] [size]     文字（内置 8x16 点阵，仅 ASCII 稳定；
                                     中文留 B 交互窗形态，此处诚实降级为框）
  mosaic x,y,w,h [block]             马赛克（block 像素块均值涂抹）
  blur   x,y,w,h                     模糊（3x3 均值核迭代 2 次）

——v0.1.1 增补四件（ShareX 拆解引进，见设计文档 §7.5）：
  step   x,y [color] [size]          步骤编号（同一次 ops 内自动递增 ①②…
                                     以数字形态渲染，起步 1）
  number x,y [value] [color] [size]  显式编号（不受递增影响）
  spotlight x,y,w,h [dim]            聚光灯：目标区保持原样、四周压暗
                                     （dim 缺省 0.5，乘暗系数）
  smarterase x,y,w,h                 智能擦除：区域用边缘均值色实心填充
                                     （比马赛克干净，适合纯色背景遮挡）

颜色 #RRGGBB；缺省红 #FF3B30、宽 3。
B 交互形态（tkinter 全屏遮罩画布）v0.2 预留：接口 annotate_interactive()
已占位，首版不实现——用户画笔交互属增量交付。
"""
import json
import math
import os
import struct
import zlib

from . import geometry

DEFAULT_COLOR = (0xFF, 0x3B, 0x30)
DEFAULT_WIDTH = 3
WIDTH_MAX = 1000.0
STROKE_KINDS = ("rect", "ellipse", "line", "curve", "arc", "polyline",
                "arrow")


def default_out(image):
    """缺省输出路径：<原名>_annotated.png（v0.2.6 Q07 单源）。

    先看 **basename** 有没有点——旧 CLI 直接对全路径 rsplit(".")，
    父目录带点（…/my.dir/shot）时会把路径截到上一级、静默写错地方。
    与 MCP 面同源，避免两脸行为分叉。"""
    s = str(image)
    if "." in os.path.basename(s):
        return s.rsplit(".", 1)[0] + "_annotated.png"
    return s + "_annotated.png"


# ---------- 像素画布（RGBA，无 PIL） ----------

class Canvas:
    def __init__(self, png_bytes):
        self.w, self.h, self.px = _decode_png(png_bytes)

    # ---- 基础笔画 ----
    def _px(self, x, y, color, a=255):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            r, g, b = color
            px = self.px
            px[i], px[i + 1], px[i + 2] = r, g, b
            px[i + 3] = a

    def line(self, x1, y1, x2, y2, color, width=DEFAULT_WIDTH):
        """Bresenham 加粗（方形笔刷）。"""
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        half = width // 2
        while True:
            for oy in range(-half, half + 1):
                for ox in range(-half, half + 1):
                    self._px(x1 + ox, y1 + oy, color)
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x1 += sx
            if e2 < dx:
                err += dx
                y1 += sy

    def rect(self, x, y, w, h, color, width=DEFAULT_WIDTH, radius=0):
        if radius > 0:
            self._rect_round(x, y, w, h, color, width, radius)
            return
        self.line(x, y, x + w, y, color, width)
        self.line(x + w, y, x + w, y + h, color, width)
        self.line(x + w, y + h, x, y + h, color, width)
        self.line(x, y + h, x, y, color, width)

    def _rect_round(self, x, y, w, h, color, width, radius):
        """圆角矩形描边：四直段 + 四 90° 圆弧（参数方程步进连线）。"""
        r = max(0, min(radius, w // 2, h // 2))
        self.line(x + r, y, x + w - r, y, color, width)
        self.line(x + r, y + h, x + w - r, y + h, color, width)
        self.line(x, y + r, x, y + h - r, color, width)
        self.line(x + w, y + r, x + w, y + h - r, color, width)
        arcs = ((x + r, y + r, 3.14159265, 4.71238898),
                (x + w - r, y + r, 4.71238898, 6.2831853),
                (x + w - r, y + h - r, 0.0, 1.57079633),
                (x + r, y + h - r, 1.57079633, 3.14159265))
        for cx, cy, a0, a1 in arcs:
            steps = max(8, r)
            prev = None
            for i in range(steps + 1):
                t = a0 + (a1 - a0) * i / steps
                px, py = int(cx + r * math.cos(t)), int(cy + r * math.sin(t))
                if prev:
                    self.line(prev[0], prev[1], px, py, color, width)
                prev = (px, py)

    def ellipse(self, x, y, w, h, color, width=DEFAULT_WIDTH):
        """参数方程椭圆（步进连线 + 笔刷）。"""
        import math
        cx, cy = x + w / 2, y + h / 2
        a, b = w / 2, h / 2
        if a <= 0 or b <= 0:
            return
        step = max(64, int((a + b) * 2))
        prev = None
        for i in range(step + 1):
            t = 6.2831853 * i / step
            px, py = int(cx + a * math.cos(t)), int(cy + b * math.sin(t))
            if prev:
                self.line(prev[0], prev[1], px, py, color, width)
            prev = (px, py)

    def arrow(self, x1, y1, x2, y2, color, width=DEFAULT_WIDTH, style="fat"):
        """渐变实心箭头（v0.1.6 缺省；v0.1.8 几何重校准）：头长=头宽=
        3.5×width 细三角 + 短箭封顶 0.4×全长 + 杆恒定≈width（尾 0.35×width
        幂 0.75 温和渐变）+ 圆尾，与矢量版同参数语义（设计文档 §7.7.3）。
        style="line" 回退旧式恒粗直杆细箭头。"""
        if style == "line":
            self._arrow_line(x1, y1, x2, y2, color, width)
            return
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        ux, uy = dx / dist, dy / dist
        head_len = min(max(10.0, width * 3.5), dist * 0.4)   # 短箭封顶
        head_half = max(head_len * 0.5, width * 0.5)   # 头底不窄于杆端（极短箭域防凹肩）
        r_tail = max(1.2, width * 0.35)
        r_head = width * 0.5   # 杆接头=名义宽，零膨胀
        shaft_len = max(0.0, dist - head_len)
        steps = max(8, int(shaft_len * 2))
        for i in range(steps + 1):
            s = shaft_len * i / steps
            t = (s / shaft_len) ** 0.75 if shaft_len > 0 else 1.0
            r = r_tail + (r_head - r_tail) * t
            self._disc(x1 + ux * s, y1 + uy * s, r, color)
        bx, by = x2 - ux * head_len, y2 - uy * head_len   # 三角底边中点
        nx, ny = -uy, ux
        self._fill_tri((x2, y2),
                       (bx + nx * head_half, by + ny * head_half),
                       (bx - nx * head_half, by - ny * head_half), color)

    def _arrow_line(self, x1, y1, x2, y2, color, width):
        """旧式箭头：恒粗直杆 + 两条翼（style="line" 回退用）。"""
        self.line(x1, y1, x2, y2, color, width)
        ang = math.atan2(y2 - y1, x2 - x1)
        ln = max(12, width * 4)
        for da in (2.6, -2.6):
            self.line(x2, y2, int(x2 + ln * math.cos(ang + da)),
                      int(y2 + ln * math.sin(ang + da)), color, width)

    def _disc(self, cx, cy, r, color):
        """亚像素圆盘扫掠单元：r 可为小数（<0.5 收缩为单点）。"""
        ri = int(r + 0.5)
        if ri <= 0:
            self._px(int(cx), int(cy), color)
            return
        r2 = ri * ri
        for yy in range(int(cy - ri), int(cy + ri) + 1):
            for xx in range(int(cx - ri), int(cx + ri) + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r2:
                    self._px(xx, yy, color)

    def _fill_tri(self, p1, p2, p3, color):
        """实心三角（同侧法内点判定，包围盒扫描）。"""

        def sign(ax, ay, bx, by, cx, cy):
            return (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)

        minx = max(0, int(min(p1[0], p2[0], p3[0])))
        maxx = min(self.w - 1, int(max(p1[0], p2[0], p3[0])) + 1)
        miny = max(0, int(min(p1[1], p2[1], p3[1])))
        maxy = min(self.h - 1, int(max(p1[1], p2[1], p3[1])) + 1)
        for yy in range(miny, maxy + 1):
            for xx in range(minx, maxx + 1):
                d1 = sign(xx, yy, p1[0], p1[1], p2[0], p2[1])
                d2 = sign(xx, yy, p2[0], p2[1], p3[0], p3[1])
                d3 = sign(xx, yy, p3[0], p3[1], p1[0], p1[1])
                if not ((d1 < 0 or d2 < 0 or d3 < 0)
                        and (d1 > 0 or d2 > 0 or d3 > 0)):
                    self._px(xx, yy, color)

    def circle_filled(self, cx, cy, r, color):
        """实心圆（step/number 徽章底）。"""
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                    self._px(xx, yy, color)

    def text(self, x, y, s, color=DEFAULT_COLOR, size=16, max_width=None):
        """首版 ASCII 8x16 点阵；非 ASCII 字符画占位框（诚实降级，
        中文文本标注留 B 交互窗形态——点阵字体不破零依赖红线）。

        v0.2.6（Q15）：max_width（像素）给了就按点阵字宽贪心折行，
        `\\n` 显式换行——与矢量路（GDI+ RectangleF）语义对齐；
        不给=旧行为（单行，出界由上层 bounds_warn 告警）。"""
        from . import font8x16
        sc = max(1, size // 16)   # v0.1.2 审查 P2-1：偏移与复制同一缩放——
        # 旧实现偏移用裸 size//16（<16 时为 0），字形所有点画到同一点
        cx, cy = x, y
        line_h = 16 * sc + 4
        for ch in s:
            if ch == "\n":
                cx, cy = x, cy + line_h
                continue
            if max_width and cx > x and (cx + 8 * sc + 2) - x > max_width:
                cx, cy = x, cy + line_h   # 折行（至少画一个字符，防死循环）
            glyph = font8x16.glyph(ch)
            if glyph is None:
                self.rect(cx, cy, size, size, color, 1)
                cx += size + 2
                continue
            for row, bits in enumerate(glyph):
                for col in range(8):
                    if bits & (0x80 >> col):
                        for oy in range(sc):
                            for ox in range(sc):
                                self._px(cx + col * sc + ox,
                                         cy + row * sc + oy, color)
            cx += 8 * sc + 2

    def mosaic(self, x, y, w, h, block=12):
        for by in range(y, y + h, block):
            for bx in range(x, x + w, block):
                r = g = b = n = 0
                for yy in range(by, min(by + block, y + h)):
                    for xx in range(bx, min(bx + block, x + w)):
                        if 0 <= xx < self.w and 0 <= yy < self.h:
                            i = (yy * self.w + xx) * 4
                            r += self.px[i]; g += self.px[i + 1]
                            b += self.px[i + 2]; n += 1
                if n:
                    r, g, b = r // n, g // n, b // n
                    for yy in range(by, min(by + block, y + h)):
                        for xx in range(bx, min(bx + block, x + w)):
                            self._px(xx, yy, (r, g, b))

    def blur(self, x, y, w, h, iterations=2):
        for _ in range(iterations):
            src = bytes(self.px)
            for yy in range(max(1, y), min(self.h - 1, y + h)):
                for xx in range(max(1, x), min(self.w - 1, x + w)):
                    for c in range(3):
                        i = (yy * self.w + xx) * 4 + c
                        acc = (src[i - self.w * 4] + src[i - 4] + src[i] +
                               src[i + 4] + src[i + self.w * 4])
                        self.px[i] = acc // 5

    def spotlight(self, x, y, w, h, dim=0.5):
        """聚光灯：目标区保持原样，四周压暗（dim=保留亮度系数 0~1）。"""
        if not 0 <= dim <= 1:
            raise ValueError("dim 须在 0~1（保留亮度系数）：got %r" % dim)
        x, y = max(0, x), max(0, y)
        w = min(w, self.w - x)
        h = min(h, self.h - y)
        if w <= 0 or h <= 0:
            raise ValueError("spotlight 区域完全在图外（clamp 后 w=%s h=%s）"
                             % (w, h))   # 与 smarterase 同款防御：图外区域
        # 静默无操作等于吞错，如实报
        for yy in range(self.h):
            for xx in range(self.w):
                if x <= xx < x + w and y <= yy < y + h:
                    continue
                i = (yy * self.w + xx) * 4
                self.px[i] = int(self.px[i] * dim)
                self.px[i + 1] = int(self.px[i + 1] * dim)
                self.px[i + 2] = int(self.px[i + 2] * dim)

    def smarterase(self, x, y, w, h):
        """智能擦除：区域用「边缘均值色」实心填充——比马赛克干净
        （纯色/渐变背景上等于消失）。
        v0.1.2 审查 P2-3：只采**真正存在的外侧**像素（y>0 才采上环……），
        旧实现贴边时把目标区自己的首行/列采进环——擦除内容以染色形式
        残留 40% 权重；P3-3 顶点重复计数一并去重。四边全贴图边的退化
        情形如实报错（无外侧可采）。"""
        x, y = max(0, x), max(0, y)
        w = min(w, self.w - x)
        h = min(h, self.h - y)
        if w <= 0 or h <= 0:
            # v0.1.5 P3：区域完全在图外时 clamp 出负宽高，环采样按错行
            # 取像素——要么 IndexError 要么静默错采，根修=clamp 后校验
            raise ValueError("smarterase 区域完全在图外（clamp 后 w=%s h=%s）"
                             % (w, h))
        has_top, has_bottom = y > 0, y + h < self.h
        has_left, has_right = x > 0, x + w < self.w
        if not (has_top or has_bottom or has_left or has_right):
            raise ValueError("smarterase 区域覆盖整图，无外侧可采样")
        ring = set()
        if has_top:
            ring.update((xx, y - 1) for xx in range(x, x + w))
        if has_bottom:
            ring.update((xx, y + h) for xx in range(x, x + w))
        if has_left:
            ring.update((x - 1, yy) for yy in range(y, y + h))
        if has_right:
            ring.update((x + w, yy) for yy in range(y, y + h))
        ring_px = []
        for xx, yy in sorted(ring):
            i = (yy * self.w + xx) * 4
            ring_px.append(self.px[i:i + 3])
        if not ring:
            return
        n = len(ring_px)
        fill = (sum(c[0] for c in ring_px) // n,
                sum(c[1] for c in ring_px) // n,
                sum(c[2] for c in ring_px) // n)
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self._px(xx, yy, fill)

    # ---- 出码 ----
    def to_png(self):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            raw.extend(self.px[y * self.w * 4:(y + 1) * self.w * 4])

        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(
                ">I", zlib.crc32(c))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                + chunk(b"IEND", b""))


def _decode_png(png):
    """PNG 解码（v0.2.6 Q21 扩展）：8-bit、非隔行，颜色类型
    0(灰度)/2(RGB)/3(调色板)/4(灰度+α)/6(RGBA)。16-bit 与隔行如实
    拒绝并给出可操作提示——「降级路只吃 RGBA」曾让普通 RGB 导出图
    在降级时直接 ValueError（不是降级，是失败）。"""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos, idat, plte, trns = 8, b"", b"", b""
    w = h = depth = ctype = 0
    while pos < len(png):
        (ln,) = struct.unpack(">I", png[pos:pos + 4])
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[:10])
            if len(data) > 12 and data[12] != 0:
                # v0.1.5 P2：interlace 不校验会按逐行扫描线硬解 Adam7
                # 数据 → 静默花图，违背「其他形态如实报错」契约
                raise ValueError("不支持隔行（interlaced）PNG：如实拒绝")
        elif tag == b"PLTE":
            plte = data
        elif tag == b"tRNS":
            trns = data
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
        pos += 12 + ln
    if depth != 8:
        raise ValueError("仅支持 8-bit PNG（got depth=%s）——16-bit/低位深请先转 8-bit"
                         % depth)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if ch is None:
        raise ValueError("不支持的 PNG 颜色类型 %s" % ctype)
    if ctype == 3 and not plte:
        raise ValueError("调色板 PNG 缺 PLTE，文件已损坏")
    raw = zlib.decompress(idat)
    bpp = ch
    stride = w * bpp
    rows = []
    prev = bytearray(stride)
    for y in range(h):
        off = y * (stride + 1)
        ft = raw[off]
        row = bytearray(raw[off + 1:off + 1 + stride])
        if ft == 1:    # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + (left + prev[i]) // 2) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                ul = prev[i - bpp] if i >= bpp else 0
                up = prev[i]
                pp = left + up - ul
                pa, pb, pc = abs(pp - left), abs(pp - up), abs(pp - ul)
                pr = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else ul)
                row[i] = (row[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError("未知 PNG 行过滤器 %s" % ft)
        rows.append(row)
        prev = row
    joined = b"".join(bytes(r) for r in rows)
    px = bytearray(w * h * 4)
    if ctype == 6:
        px[:] = joined
    elif ctype == 2:
        px[0::4] = joined[0::3]
        px[1::4] = joined[1::3]
        px[2::4] = joined[2::3]
        px[3::4] = b"\xff" * (w * h)
    elif ctype == 0:
        px[0::4] = joined
        px[1::4] = joined
        px[2::4] = joined
        px[3::4] = b"\xff" * (w * h)
    elif ctype == 4:
        px[0::4] = joined[0::2]
        px[1::4] = joined[0::2]
        px[2::4] = joined[0::2]
        px[3::4] = joined[1::2]
    else:   # 3 = 调色板
        n = len(plte) // 3
        for i, idx in enumerate(joined):
            if idx >= n:
                raise ValueError("调色板索引越界（%d >= %d）" % (idx, n))
            o = i * 4
            p = idx * 3
            px[o] = plte[p]
            px[o + 1] = plte[p + 1]
            px[o + 2] = plte[p + 2]
            px[o + 3] = trns[idx] if idx < len(trns) else 255
    return w, h, px



# ---------- C 形态入口：JSON ops 批量标注 ----------

def annotate_png(png_bytes, ops):
    """对 PNG 字节执行 ops（JSON 数组）-> 新 PNG 字节。

    op 形如 {"kind": "rect", "x": .., ..}；坐标数组形 "100,100,200,50"
    亦可（agent 友好）。未知 kind 如实报错（绝不静默跳过）。
    step 编号在同一调用内自动递增（跨调用不共享状态——无全局账本）。"""
    cv = Canvas(png_bytes)
    step_n = 0
    for op in ops:
        if isinstance(op, str):
            op = json.loads(op)
        kind = op.get("kind")
        color = _color(op.get("color"))
        # v0.4.1：小数线宽四舍五入（旧实现 int() 截断，1.9 只画 1px，
        # 与矢量路差 2px）；<=0 / 过大一律报错，别静默不画（审查实测
        # width=-3 时像素路零输出）
        width_f = float(op.get("width", DEFAULT_WIDTH))
        if kind in STROKE_KINDS:
            if width_f <= 0:
                raise ValueError("width 必须 > 0（%s）：%r"
                                 % (kind, op.get("width")))
            if width_f > WIDTH_MAX:
                raise ValueError("width 过大（>%g）：%r"
                                 % (WIDTH_MAX, op.get("width")))
        width = max(1, int(width_f + 0.5))
        if kind in ("step", "number", "text"):
            # v0.1.3（二轮审查 P1-B 收口）：text **无圆底**——v0.1.2 重构
            # 把前置 circle_filled 残留给了三元组（step/number 画两遍、
            # text 画一遍实心盘且字形同色不可见）。现圆底仅 step/number。
            sz = int(op.get("size", 16))
            body, color_body, ox, oy, draw_disc = None, color, 0, 0, False
            if kind == "step":
                step_n += 1           # 先递增：编号从 1 起（'0' 是 bug 实锤）
                body, color_body = str(step_n), (255, 255, 255)
                draw_disc, ox, oy = True, sz // 4, sz // 4
            elif kind == "number":
                body, color_body = (str(op.get("value", op.get("n", "1"))),
                                    (255, 255, 255))
                draw_disc, ox, oy = True, sz // 4, sz // 4
            else:   # text
                body = str(op.get("text", ""))
            if draw_disc:
                cv.circle_filled(int(op.get("x", 0)), int(op.get("y", 0)),
                                 sz, color)
            cv.text(int(op.get("x", 0)) + ox, int(op.get("y", 0)) + oy,
                    body, color_body, sz,
                    max_width=int(op.get("w") or 0) or None)
            continue
        if kind in ("curve", "arc", "polyline"):
            # v0.4.1：曲线/弧线/折线。与矢量路共用 geometry 的同一套采样
            # （像素路只是把折线逐段画出来——硬边，收据 backend=pixel 已亮牌）
            if kind == "curve":
                pts = geometry.pad_points(
                    geometry.bezier_points(*geometry.parse_curve(op)))
            elif kind == "arc":
                pts = geometry.pad_points(
                    geometry.arc_points(*geometry.parse_arc(op)))
            else:
                pts = geometry.polyline_points(geometry.parse_polyline(op))
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                seg = geometry.clip_segment(ax, ay, bx, by, cv.w - 1, cv.h - 1)
                if seg is None:
                    continue        # 整段在画布外：不跑 Bresenham（审查 P2-4）
                cv.line(int(round(seg[0])), int(round(seg[1])),
                        int(round(seg[2])), int(round(seg[3])), color, width)
            continue
        n = _nums(op, "xywh" if kind in ("rect", "ellipse", "mosaic", "blur",
                                         "spotlight", "smarterase")
                  else "xyxy" if kind in ("arrow", "line")   # v0.1.3 二轮审查
                  # P1-A 收口：line 漏出 xyxy 组 = 原语全灭
                  else None)

        if kind == "rect":
            cv.rect(*n, color, width, radius=int(op.get("radius", 0)))
        elif kind == "ellipse":
            cv.ellipse(*n, color, width)
        elif kind == "arrow":
            cv.arrow(*n, color, width, style=str(op.get("style", "fat")))
        elif kind == "line":
            cv.line(*n, color, width)
        elif kind == "mosaic":
            cv.mosaic(*n, block=int(op.get("block", 12)))
        elif kind == "blur":
            cv.blur(*n)
        elif kind == "spotlight":
            cv.spotlight(*n, dim=float(op.get("dim", 0.5)))
        elif kind == "smarterase":
            cv.smarterase(*n)
        else:
            raise ValueError("未知标注 kind：%r" % kind)
    return cv.to_png()


_NUM_KEYS = {"xywh": ("x", "y", "w", "h"),
             "xyxy": ("x1", "y1", "x2", "y2")}   # v0.1.2：显式键组（旧实现
             # "xyxy" 按字符迭代读成 x/y/x2/y2——arrow 起点被 x2 顶替）

def _nums(op, shape):
    """从 op 取坐标四元组。两形态：显式键（x1,y1,x2,y2 / x,y,w,h）或
    "100,100,200,50" 逗号串（v0.1.2 实装——文档曾承诺但旧实现没写）。"""
    keys = _NUM_KEYS.get(shape)
    if keys is None:
        raise ValueError("未知标注 kind 或缺少坐标定义：%r" % (op.get("kind"),))
    if all(op.get(k) is None for k in keys):
        joined = op.get("coords") or op.get("area")
        if isinstance(joined, str):
            parts = [int(x) for x in joined.replace(" ", "").split(",")]
            if len(parts) == 4:
                return parts
    out = []
    for k in keys:
        v = op.get(k)
        if v is None:
            raise ValueError("op 缺坐标键 %s：%r" % (k, op))
        out.append(int(v))
    return out


def _color(v):
    if not v:
        return DEFAULT_COLOR
    v = str(v).lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def annotate_interactive(png_bytes):
    """B 形态占位（tkinter 遮罩画布）——v0.2 交付，首版诚实亮牌。"""
    raise NotImplementedError(
        "交互标注器 v0.2 交付；当前请用 C 形态 annotate_png（JSON ops）")
