# -*- coding: utf-8 -*-
"""Ashot.vision —— 图像指纹与差异（纯标准库，零第三方依赖，v0.2.7）。

为什么不是"验证码模块"：Ashot 不做验证码。这里只提供**通用**能力——
「这张图是不是原来那张」「两张图差在哪」——页面变化监控、UI 回归、截图
去重、以及调用方自己拼验证码流程（"图变了就重来"）都用它。

算法出处（2026-10-29 调研）：
  · dHash/aHash —— 感知哈希的经典低配版（imagehash 同思路）：
    dHash = 缩到 9×8 灰度、逐行比较相邻像素（64 bit）；
    aHash = 缩到 8×8 灰度、与均值比较。
  · diff —— 采用 pixelmatch 的 **YIQ 颜色距离 + threshold** 判据；
    pixelmatch 的"抗锯齿像素检测"本版**不做**（需要邻域启发式，纯 Python
    成本高），所以字体抗锯齿可能带来少量假差异，收据如实说明。

坐标/像素纪律：解码复用 annotate._decode_png（支持 8-bit 灰度/RGB/调色板/
灰度α/RGBA），编码复用 output.rgba_to_png；不引入 PIL/numpy。
"""
import hashlib

from . import annotate as _px
from . import output as _out

# pixelmatch 的 YIQ 权重（0~255 域），maxDelta = 35215 * threshold²
_YIQ_MAX = 35215.0


def _cell_samples(x0, x1, y0, y1, cap=64):
    """一个网格单元内的采样点（不逐像素遍历，4K 图也能秒级）。
    纯色/渐变区域用稀疏采样足够；哈希本来就对细节不敏感。"""
    cw, ch = max(1, x1 - x0), max(1, y1 - y0)
    step = max(1, int((cw * ch / float(cap)) ** 0.5))
    xs = range(x0, x1, step)
    ys = range(y0, y1, step)
    return xs, ys


def _gray_grid(px, w, h, gw, gh):
    """RGBA -> gh×gw 灰度网格（面积采样平均）。"""
    grid = []
    for gy in range(gh):
        y0 = gy * h // gh
        y1 = max(y0 + 1, (gy + 1) * h // gh)
        row = []
        for gx in range(gw):
            x0 = gx * w // gw
            x1 = max(x0 + 1, (gx + 1) * w // gw)
            xs, ys = _cell_samples(x0, x1, y0, y1)
            total = n = 0
            for y in ys:
                base = y * w * 4
                for x in xs:
                    i = base + x * 4
                    total += (px[i] * 299 + px[i + 1] * 587
                              + px[i + 2] * 114) // 1000
                    n += 1
            row.append(total // max(1, n))
        grid.append(row)
    return grid


def _bits_to_hex(bits):
    v = 0
    for b in bits:
        v = (v << 1) | (1 if b else 0)
    return "0x%016x" % v


def dhash(png):
    """64-bit 差值哈希（十六进制串）。对缩放/轻微亮度变化稳定。"""
    w, h, px = _px._decode_png(png)
    g = _gray_grid(px, w, h, 9, 8)
    bits = []
    for y in range(8):
        for x in range(8):
            bits.append(g[y][x] > g[y][x + 1])
    return _bits_to_hex(bits)


def ahash(png):
    """64-bit 均值哈希（十六进制串）。"""
    w, h, px = _px._decode_png(png)
    g = _gray_grid(px, w, h, 8, 8)
    flat = [v for row in g for v in row]
    avg = sum(flat) / float(len(flat) or 1)
    return _bits_to_hex([v > avg for v in flat])


def hamming(a, b):
    """两个十六进制哈希的汉明距离（不同 bit 数）。"""
    try:
        x, y = int(str(a), 16), int(str(b), 16)
    except ValueError:
        raise ValueError("哈希不是十六进制串：%r / %r" % (a, b))
    return bin(x ^ y).count("1")


def digest(png):
    """完整指纹收据：sha256（精确）+ dhash/ahash（感知）+ 尺寸。"""
    w, h, _ = _px._decode_png(png)
    return {
        "sha256": hashlib.sha256(bytes(png)).hexdigest(),
        "dhash": dhash(png),
        "ahash": ahash(png),
        "w": w,
        "h": h,
    }


def diff(a_png, b_png, threshold=0.12, make_image=False):
    """两张 PNG 的差异。

    threshold：0~1 的 YIQ 归一化阈值（pixelmatch 口径，0.1≈明显色差）；
               越大越宽容。
    尺寸不同：只比重叠区（左上对齐），收据亮 size_mismatch 与各自尺寸；
              没有重叠则 same=False、ratio=0、bbox=None。
    make_image：额外返回差异图（未变区域压暗 60%，变化像素涂红）。

    返回 {same, changed_px, total_px, ratio, bbox, size_mismatch,
          dims, threshold, image, note}。
    """
    wa, ha, pa = _px._decode_png(a_png)
    wb, hb, pb = _px._decode_png(b_png)
    w, h = min(wa, wb), min(ha, hb)
    out = {"threshold": float(threshold), "size_mismatch": (wa, ha) != (wb, hb),
           "dims": [[wa, ha], [wb, hb]], "changed_px": 0,
           "total_px": max(0, w) * max(0, h), "ratio": 0.0,
           "bbox": None, "same": False, "image": None}
    if w <= 0 or h <= 0:
        out["note"] = "两图没有重叠区域，无法比较"
        return _finish(out, pa, wa, ha, make_image)
    limit = _YIQ_MAX * float(threshold) ** 2
    changed = 0
    minx, miny, maxx, maxy = w, h, -1, -1
    canvas = None
    if make_image:
        canvas = bytearray(pa)
        for i in range(0, len(canvas), 4):   # 压暗未变区域
            canvas[i] = canvas[i] * 40 // 100
            canvas[i + 1] = canvas[i + 1] * 40 // 100
            canvas[i + 2] = canvas[i + 2] * 40 // 100
    for y in range(h):
        ra = y * wa * 4
        rb = y * wb * 4
        row_changed = False
        for x in range(w):
            ia = ra + x * 4
            ib = rb + x * 4
            r1, g1, b1 = pa[ia], pa[ia + 1], pa[ia + 2]
            r2, g2, b2 = pb[ib], pb[ib + 1], pb[ib + 2]
            if r1 == r2 and g1 == g2 and b1 == b2:
                continue
            # YIQ 距离（pixelmatch 公式）
            y1_ = 0.29889531 * r1 + 0.58662247 * g1 + 0.11448223 * b1
            i1_ = 0.59597799 * r1 - 0.27417610 * g1 - 0.32180189 * b1
            q1_ = 0.21147017 * r1 - 0.52261711 * g1 + 0.31114694 * b1
            y2_ = 0.29889531 * r2 + 0.58662247 * g2 + 0.11448223 * b2
            i2_ = 0.59597799 * r2 - 0.27417610 * g2 - 0.32180189 * b2
            q2_ = 0.21147017 * r2 - 0.52261711 * g2 + 0.31114694 * b2
            dy, di, dq = y1_ - y2_, i1_ - i2_, q1_ - q2_
            delta = 0.5053 * dy * dy + 0.299 * di * di + 0.1957 * dq * dq
            if delta <= limit:
                continue
            changed += 1
            row_changed = True
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if make_image:
                canvas[ia] = 255
                canvas[ia + 1] = 0
                canvas[ia + 2] = 0
        if row_changed:
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    out["changed_px"] = changed
    out["ratio"] = round(changed / float(max(1, w * h)), 6)
    out["same"] = (changed == 0 and not out["size_mismatch"])
    if changed:
        out["bbox"] = [minx, miny, maxx - minx + 1, maxy - miny + 1]
    out["note"] = ("尺寸不同：只比重叠区，same 恒为 False；另未做 "
                   "pixelmatch 式抗锯齿检测" if out["size_mismatch"] else
                   "未做 pixelmatch 式抗锯齿检测，字体边缘可能有少量假差异")
    return _finish(out, canvas if make_image else pa, wa, ha, make_image)


def _finish(out, px, w, h, make_image):
    if make_image:
        out["image"] = _out.rgba_to_png(w, h, bytes(px))
    return out
