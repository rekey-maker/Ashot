# -*- coding: utf-8 -*-
"""Ashot.output —— 交付：PNG 编码 / 落盘命名 / 剪贴板 / retention 清理。

模块纪律：只被 cli/mcp 汇聚调用；不 import capture/annotate。
"""
import ctypes
import os
import struct
import subprocess
import sys
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


def rgba_to_png(w, h, rgba):
    """RGBA 像素 -> PNG 字节（8-bit RGBA）。拼接全页截图用（v0.2.6）。"""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)                   # filter: None
        raw.extend(rgba[y * stride:(y + 1) * stride])
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

def _decode_console(data):
    """控制台字节 -> 文本（PowerShell 的 stderr 走 OEM/GBK，按 utf-8 解
    会出乱码；依次尝试 utf-8 / 本地代码页 / gbk，全失败才替换解码）。"""
    import locale
    for enc in ("utf-8", locale.getpreferredencoding(False), "gbk", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def clip_png(png_bytes):
    """PNG 进剪贴板（CF_DIB 位图形态——PNG 剪贴板格式接收方支持参差）。
    独立进程承载（OpenClipboard 生命周期隔离），成功返回 True。

    v0.2.6（Q10）：os.system 换成 subprocess.run——旧实现三重病：
    双引号拼接（路径含 " / % / & 即坏）、stderr 直接进控制台（MCP 场景
    等于丢失）、PS 侧无 ErrorActionPreference（失败也可能 0 退出码）。
    现在失败原因落 stderr，返回值仍只有 bool（调用方只关心成败）。"""
    # 解 PNG 需像素：偷懒走 PowerShell 一条龙（Set-Clipboard 接图片文件，
    # Win10 1903+ 原生支持）——零 PIL 红线不破。
    tmp = os.path.join(os.environ.get("TEMP", "."),
                       "ashot_clip_%d.png" % time.time_ns())
    with open(tmp, "wb") as fh:
        fh.write(png_bytes)
    ps = ("$ErrorActionPreference='Stop';"
          "Add-Type -AssemblyName System.Windows.Forms;"
          "Set-Clipboard -Path '%s'" % tmp.replace("'", "''"))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            err = _decode_console(r.stderr).strip()
            if err:
                print("ashot: 剪贴板写入失败：%s" % err[:300], file=sys.stderr)
            return False
        return True
    except Exception as e:  # noqa: BLE001 —— 剪贴板失败不该炸主流程
        print("ashot: 剪贴板写入失败：%s: %s"
              % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return False
    finally:
        try:
            os.unlink(tmp)   # 阅后即焚：剪贴板持有位图数据，临时文件即删
        except OSError:
            pass


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
# v0.2.6（Q16）：500KB → 200KB——preview 改缺省开后，每次调用都进上下文，
# 200KB 对「确认截对了」足够（base64 后约 267KB，仍是可接受量级）。
PREVIEW_MAX_BYTES_DEFAULT = 200 * 1024
# v0.2.6 实弹（维基 49446px 长页）：只按宽度缩，高度仍是 49446×0.6≈3 万像素，
# 梯次到底还有 2.8MB——直接进模型上下文会炸。缩图必须**同时约束高**
# （整页缩略图：宽度会被压得很窄，但至少上下文安全）。
PREVIEW_MAX_HEIGHT_DEFAULT = 4000


def _png_size(png):
    """PNG IHDR -> (w, h)；坏数据返回 None。"""
    try:
        if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
            return None
        return struct.unpack(">II", bytes(png[16:24]))
    except Exception:  # noqa: BLE001
        return None


def preview_jpeg(png_bytes, width=PREVIEW_WIDTH_DEFAULT,
                 max_bytes=PREVIEW_MAX_BYTES_DEFAULT,
                 max_height=PREVIEW_MAX_HEIGHT_DEFAULT):
    """交付侧预览缩图：PNG → 等比缩小 JPEG。编码走系统 .NET
    System.Drawing（渲染器同引擎，零依赖红线不破）。梯次 (宽,质量)
    降档直至 ≤ max_bytes；**不放大**；**高度也设上限**（超长页整页缩略
    图不能把上下文撑爆，v0.2.6 实弹：49446px 长页按宽缩仍有 2.8MB）。
    返回 (jpeg_bytes, info)；info = {width, height, quality, bytes, fit}——
    fit=False 表示梯次到底仍超限，如实交付最小档不假装。"""
    w = int(width)
    sz = _png_size(png_bytes)
    if sz and sz[0] and sz[1] and max_height:
        # 按高约束反推宽度：h' = w' * (src_h/src_w) ≤ max_height
        by_h = int(max(1, float(max_height) * sz[0] / float(sz[1])))
        w = min(w, by_h)
    w = max(1, w)
    w2 = max(1, int(w * 0.75))
    w3 = max(1, int(w * 0.5))
    ladder = ((w, 85), (w, 70), (w2, 75), (w3, 60))
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
            "  Write-Output (\"$w $h $($step[1]) $len\");"
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
        w_s, h_s, q_s, len_s = lines[-1].split()
        info = {"width": int(w_s), "height": int(h_s),
                "quality": int(q_s),
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
