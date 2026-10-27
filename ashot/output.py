# -*- coding: utf-8 -*-
"""Ashot.output —— 交付：PNG 编码 / 落盘命名 / 剪贴板 / retention 清理。

模块纪律：只被 cli/mcp 汇聚调用；不 import capture/annotate。
"""
import ctypes
import os
import struct
import subprocess
import tempfile
import time
import zlib

SHOTS_DIR = os.path.join(os.path.expanduser("~"), "Ashot", "shots")
RETENTION_DAYS_DEFAULT = 30          # 用户裁决缺省（--retention-days 覆盖）
CLIPCF_DIB = 17                      # CF_DIB
CF_UNICODETEXT = 13


# ---------- PNG 编码（标准库 zlib 手写，零 PIL） ----------

def bgra_to_png(w, h, bgra):
    """BGRA 像素 -> PNG 字节（8-bit RGBA）。纯标准库。"""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)                   # filter: None
        row = bgra[y * stride:(y + 1) * stride]
        for x in range(0, stride, 4):   # BGRA -> RGBA
            b, g, r = row[x], row[x + 1], row[x + 2]
            raw.extend(bytes((r, g, b, row[x + 3])))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


# ---------- 落盘 ----------

def default_dir():
    d = SHOTS_DIR
    os.makedirs(d, exist_ok=True)
    return d


_NAME_SEQ = 0


def _default_name():
    """缺省文件名：秒级时间戳 + 进程内单调序号。纯秒级命名同秒连截两张
    会同名静默覆盖（v0.1.5 审查实锤）；时钟尾数防撞不行——Windows 时钟
    粒度粗，连续两次 time_ns 同值（测试实锤），序号才是严格唯一。"""
    global _NAME_SEQ
    _NAME_SEQ += 1
    return time.strftime("shot_%Y%m%d_%H%M%S") + "_%04d.png" % _NAME_SEQ


def save(png_bytes, out=None):
    """PNG 落盘。out=None 时缺省目录+时间戳命名；out 是目录（或无扩展名
    路径）则**在其中**生成缺省文件名（v0.1.5 P2 根修：旧实现无视传入
    目录、悄悄落到缺省目录）。"""
    if out:
        if os.path.isdir(out) or not os.path.splitext(out)[1]:
            out = os.path.join(out, _default_name())
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    else:
        out = os.path.join(default_dir(), _default_name())
    with open(out, "wb") as fh:
        fh.write(png_bytes)
    return out


# ---------- 剪贴板（--clip：阅后即焚路径；无落盘诉求时不写文件） ----------

def clip_png(png_bytes):
    """PNG 进剪贴板（CF_DIB 位图形态——PNG 剪贴板格式接收方支持参差）。
    独立进程承载（OpenClipboard 生命周期隔离），成功返回 True。"""
    # 解 PNG 需像素：偷懒走 PowerShell 一条龙（Set-Clipboard 接图片文件，
    # Win10 1903+ 原生支持）——零 PIL 红线不破。
    tmp = os.path.join(os.environ.get("TEMP", "."),
                       "ashot_clip_%d.png" % time.time_ns())
    with open(tmp, "wb") as fh:
        fh.write(png_bytes)
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "Set-Clipboard -Path '%s'" % tmp.replace("'", "''"))
    try:
        subprocess_ok = os.system('powershell -NoProfile -Command "%s"' % ps) == 0
    finally:
        try:
            os.unlink(tmp)   # 阅后即焚：剪贴板持有位图数据，临时文件即删
        except OSError:
            pass
    return bool(subprocess_ok)


# ---------- retention 清理（搭自身运行便车，无常驻） ----------

def gc(retention_days=RETENTION_DAYS_DEFAULT, keep=False, directory=None):
    """清 shots 目录超 N 天的旧 PNG。返回 (清了几张, 释放 MB)。"""
    if keep:
        return 0, 0.0
    d = directory or default_dir()
    n, freed = 0, 0
    now = time.time()
    cutoff = now - retention_days * 86400
    for name in os.listdir(d):
        f = os.path.join(d, name)
        if not name.lower().endswith(".png") or not os.path.isfile(f):
            continue
        try:
            st = os.stat(f)
        except OSError:
            continue
        if now - st.st_mtime < 120:
            continue   # 刚落盘的新图一律豁免：retention_days=0 且 mtime
            # 同秒时 cutoff≈mtime，时钟粒度会误删本次调用刚存的图
        if st.st_mtime < cutoff:
            freed += st.st_size
            os.unlink(f)
            n += 1
    return n, freed / 2**20


# ---------- 预览缩图（v0.1.11，MCP ImageContent 实验，设计文档 §7.10） ----------

PREVIEW_WIDTH_DEFAULT = 1200
PREVIEW_MAX_BYTES_DEFAULT = 500 * 1024


def preview_jpeg(png_bytes, width=PREVIEW_WIDTH_DEFAULT,
                 max_bytes=PREVIEW_MAX_BYTES_DEFAULT):
    """交付侧预览缩图：PNG → 等比缩小 JPEG。编码走系统 .NET
    System.Drawing（渲染器同引擎，零依赖红线不破）。梯次 (宽,质量)
    降档直至 ≤ max_bytes（业界口径 ~1280px/JPEG<500KB，超限保护宿主
    上下文）；**不放大**（目标宽 = min(width, 原宽)）。
    返回 (jpeg_bytes, info)；info = {width, quality, bytes, fit}——
    fit=False 表示梯次到底仍超限，如实交付最小档不假装。"""
    w2 = max(1, int(width * 0.75))
    w3 = max(1, int(width * 0.5))
    ladder = ((width, 85), (width, 70), (w2, 75), (w3, 60))
    ladder_ps = ",".join("(%d,%d)" % s for s in ladder)
    src_fd, src_path = tempfile.mkstemp(suffix=".png")
    dst_path = src_path + ".jpg"
    os.close(src_fd)
    try:
        with open(src_path, "wb") as fh:
            fh.write(png_bytes)
        script = (
            "$ErrorActionPreference='Stop';"
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
            "Add-Type -AssemblyName System.Drawing;"
            "$img=[System.Drawing.Image]::FromFile('%s');"
            "foreach ($step in @(%s)) {"
            "  $w=[Math]::Min($step[0], $img.Width);"
            "  $h=[int]([double]$img.Height*$w/$img.Width);"
            "  if ($h -lt 1) { $h = 1 }"
            "  $bmp=New-Object System.Drawing.Bitmap($w,$h);"
            "  $g=[System.Drawing.Graphics]::FromImage($bmp);"
            "  $g.InterpolationMode="
            "[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic;"
            "  $g.DrawImage($img,0,0,$w,$h);"
            "  $ep=New-Object System.Drawing.Imaging.EncoderParameters(1);"
            "  $ep.Param[0]=New-Object System.Drawing.Imaging."
            "EncoderParameter([System.Drawing.Imaging.Encoder]::Quality,"
            "[long]$step[1]);"
            "  $codec=[System.Drawing.Imaging.ImageCodecInfo]::"
            "GetImageEncoders()|Where-Object {$_.MimeType -eq 'image/jpeg'};"
            "  $bmp.Save('%s',$codec,$ep);"
            "  $g.Dispose();$bmp.Dispose();$ep.Dispose();"
            "  $len=(Get-Item -LiteralPath '%s').Length;"
            "  Write-Output (\"$w $($step[1]) $len\");"
            "  if ($len -le %d) { break }"
            "};"
            "$img.Dispose()" % (src_path.replace("'", "''"),
                                ladder_ps,
                                dst_path.replace("'", "''"),
                                dst_path.replace("'", "''"),
                                max_bytes))
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, timeout=30)
        if r.returncode != 0 or not os.path.isfile(dst_path):
            raise RuntimeError(
                "预览缩图失败（rc=%s）：%s" % (
                    r.returncode,
                    r.stderr.decode("utf-8", "replace").strip()[:200]))
        lines = [x for x in
                 r.stdout.decode("utf-8", "replace").splitlines()
                 if x.strip()]
        w_s, q_s, len_s = lines[-1].split()
        info = {"width": int(w_s), "quality": int(q_s),
                "bytes": int(len_s), "fit": int(len_s) <= max_bytes}
        with open(dst_path, "rb") as fh:
            jpeg = fh.read()
        return jpeg, info
    finally:
        for p in (src_path, dst_path):
            try:
                os.unlink(p)
            except OSError:
                pass
