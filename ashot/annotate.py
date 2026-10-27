# -*- coding: utf-8 -*-
"""Ashot.annotate —— 标注（七件绘制原语 + C 命令行形态；B 交互窗 v0.2 预留）。

模块纪律：不 import capture（对任意既有图片可用）；渲染走纯标准库
zlib/struct 手写 PNG（与 output 同款编码器思路），不依赖 PIL。

原语（ops JSON 数组的 kind）——形状七件：
  rect  x,y,w,h [color] [width]      矩形框
  ellipse x,y,w,h [color] [width]    椭圆框
  arrow  x1,y1,x2,y2 [color] [width] 箭头
  line   x1,y1,x2,y2 [color] [width] 直线
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
import struct
import zlib

DEFAULT_COLOR = (0xFF, 0x3B, 0x30)
DEFAULT_WIDTH = 3


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

    def rect(self, x, y, w, h, color, width=DEFAULT_WIDTH):
        self.line(x, y, x + w, y, color, width)
        self.line(x + w, y, x + w, y + h, color, width)
        self.line(x + w, y + h, x, y + h, color, width)
        self.line(x, y + h, x, y, color, width)

    def ellipse(self, x, y, w, h, color, width=DEFAULT_WIDTH):
        """中点椭圆（四象限对称 + 笔刷）。"""
        cx, cy = x + w / 2, y + h / 2
        a, b = w / 2, h / 2
        if a <= 0 or b <= 0:
            return
        step = max(64, int((a + b) * 2))
        prev = None
        for i in range(step + 1):
            t = 6.2831853 * i / step
            px, py = int(cx + a * (1 if t == 1.5707963 else __import__("math").cos(t))), \
                int(cy + b * __import__("math").sin(t))
            if prev:
                self.line(prev[0], prev[1], px, py, color, width)
            prev = (px, py)

    def arrow(self, x1, y1, x2, y2, color, width=DEFAULT_WIDTH):
        import math
        self.line(x1, y1, x2, y2, color, width)
        ang = math.atan2(y2 - y1, x2 - x1)
        ln = max(12, width * 4)
        for da in (2.6, -2.6):
            self.line(x2, y2, int(x2 + ln * math.cos(ang + da)),
                      int(y2 + ln * math.sin(ang + da)), color, width)

    def circle_filled(self, cx, cy, r, color):
        """实心圆（step/number 徽章底）。"""
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                    self._px(xx, yy, color)

    def text(self, x, y, s, color=DEFAULT_COLOR, size=16):
        """首版 ASCII 8x16 点阵；非 ASCII 字符画占位框（诚实降级，
        中文文本标注留 B 交互窗形态——点阵字体不破零依赖红线）。"""
        from . import font8x16
        cx = x
        sc = max(1, size // 16)   # v0.1.2 审查 P2-1：偏移与复制同一缩放——
        # 旧实现偏移用裸 size//16（<16 时为 0），字形所有点画到同一点
        for ch in s:
            glyph = font8x16.glyph(ch)
            if glyph is None:
                self.rect(cx, y, size, size, color, 1)
                cx += size + 2
                continue
            for row, bits in enumerate(glyph):
                for col in range(8):
                    if bits & (0x80 >> col):
                        for oy in range(sc):
                            for ox in range(sc):
                                self._px(cx + col * sc + ox,
                                         y + row * sc + oy, color)
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
    """有限 PNG 解码：仅支持本工具产出的 8-bit RGBA / capture 兜底 PNG 同族。
    其他形态如实报错（不追求通用解码器）。"""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos, idat, w, h, depth, ctype = 8, b"", 0, 0, 0, 0
    while pos < len(png):
        (ln,) = struct.unpack(">I", png[pos:pos + 4])
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", data[:10])
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
        pos += 12 + ln
    if depth != 8 or ctype != 6:
        raise ValueError("仅支持 8-bit RGBA PNG（got depth=%s ctype=%s）"
                         % (depth, ctype))
    raw = zlib.decompress(idat)
    stride = w * 4
    px = bytearray(w * h * 4)
    prev = bytearray(stride)
    for y in range(h):
        off = y * (stride + 1)
        ft = raw[off]
        row = bytearray(raw[off + 1:off + 1 + stride])
        if ft == 1:    # Sub
            for i in range(4, stride):
                row[i] = (row[i] + row[i - 4]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(stride):
                left = row[i - 4] if i >= 4 else 0
                row[i] = (row[i] + (left + prev[i]) // 2) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(stride):
                left = row[i - 4] if i >= 4 else 0
                ul = prev[i - 4] if i >= 4 else 0
                up = prev[i]
                pp = left + up - ul
                pa, pb, pc = abs(pp - left), abs(pp - up), abs(pp - ul)
                pr = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else ul)
                row[i] = (row[i] + pr) & 0xFF
        px[y * stride:(y + 1) * stride] = row
        prev = row
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
        width = int(op.get("width", DEFAULT_WIDTH))
        if kind in ("step", "number", "text"):
            # v0.1.2 审查 P3-2：x/y 缺省 0 是死代码（_nums 先抛错）——
            # step/number 跳过 _nums，缺 x/y 用缺省值
            cv.circle_filled(int(op.get("x", 0)), int(op.get("y", 0)),
                             int(op.get("size", 16)), color)
            if kind == "step":
                step_n += 1           # 先递增：编号从 1 起（'0' 是 bug 实锤）
                body, color_body = str(step_n), (255, 255, 255)
            elif kind == "number":
                body = str(op.get("value", op.get("n", "1")))
                color_body = (255, 255, 255)
            else:   # text
                body = str(op.get("text", ""))
                color_body = color
            sz = int(op.get("size", 16))
            if kind != "text":
                cv.circle_filled(int(op.get("x", 0)), int(op.get("y", 0)),
                                 sz, color)
                ox, oy = sz // 4, sz // 4
            else:
                ox = oy = 0
            cv.text(int(op.get("x", 0)) + ox, int(op.get("y", 0)) + oy,
                    body, color_body, sz)
            continue
        n = _nums(op, "xywh" if kind in ("rect", "ellipse", "mosaic", "blur",
                                         "spotlight", "smarterase")
                  else "xyxy" if kind == "arrow" else None)

        if kind == "rect":
            cv.rect(*n, color, width)
        elif kind == "ellipse":
            cv.ellipse(*n, color, width)
        elif kind == "arrow":
            cv.arrow(*n, color, width)
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
