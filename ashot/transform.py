# -*- coding: utf-8 -*-
"""Ashot.transform —— 图像几何：裁切 / 缩放 / PNG-JPEG 编码（v0.4.0）。

为什么单独一层：imgtool（Pillow 版）证明了三个缺口——**对已有图片裁切、
放大/缩小、把结果压成 JPEG**。本模块用**零第三方依赖**填掉它们：
引擎 = 系统自带 .NET System.Drawing（与矢量渲染同款，设计文档 §7.6.2），
不装 PIL，也不引入第二套标注实现。

模块纪律：不 import capture/annotate（对任意图片可用，被 cli/mcp 汇聚）。

坐标系（收据必须能自证）：
  · box 一律 **源图像素** 的 `x,y,w,h`（左上角 + 宽高）——**不是**
    x1,y1,x2,y2。混用是 imgtool 那批示例图出错的根因，收据同时回显
    `crop`（x,y,w,h）与 `crop_px`（x0,y0,x1,y1），错了看得见。
  · CSS 坐标由调用方乘 dpr（`dpr=` 参数就是这一步的语法糖，见 cli）。
  · 裁切越界 = **告警 + 夹到边界**，不静默、不整单失败；完全在图外才报错。
  · `max_side` **不放大**（与 preview 同语义）；`scale`/`width` 是显式
    请求，允许放大。
"""
import json
import os
import struct
import subprocess
import tempfile
import time

from . import output
_HERE = os.path.dirname(os.path.abspath(__file__))
_IMAGE_PS = os.path.join(_HERE, "_gdi_image.ps1")

FORMATS = ("png", "jpeg")


def png_size(png):
    """PNG IHDR -> (w, h)。非 PNG / 坏数据抛 ValueError（不瞎猜）。"""
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
        raise ValueError("不是合法的 PNG 字节")
    w, h = struct.unpack(">II", bytes(png[16:24]))
    if not w or not h:
        raise ValueError("PNG 尺寸为 0x0（文件已损坏）")
    return int(w), int(h)


def normalize_crop(box, w, h):
    """box=x,y,w,h（源图像素）-> ((x,y,w,h) 夹取后, [越界告警])。

    整块在图外 / 宽高非正 -> ValueError（静默返回空图等于吞错）。"""
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        raise ValueError("crop 需要 4 个数字 x,y,w,h：%r" % (box,))
    if len(vals) != 4:
        raise ValueError("crop 需要 4 个数字 x,y,w,h：%r" % (box,))
    x, y, cw, ch = (int(round(v)) for v in vals)
    if cw <= 0 or ch <= 0:
        raise ValueError("crop 宽高必须 > 0（got w=%s h=%s）" % (cw, ch))
    warns = []
    if x < 0:
        warns.append("crop 左边界越界 %d px（已夹到 0）" % -x)
    if y < 0:
        warns.append("crop 上边界越界 %d px（已夹到 0）" % -y)
    if x + cw > w:
        warns.append("crop 右边界越界 %d px（已夹到图宽 %d）"
                     % (x + cw - w, w))
    if y + ch > h:
        warns.append("crop 下边界越界 %d px（已夹到图高 %d）"
                     % (y + ch - h, h))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + cw), min(h, y + ch)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("crop 区域完全在图外：box=(%d,%d,%d,%d) 图=%dx%d"
                         % (x, y, cw, ch, w, h))
    return (x0, y0, x1 - x0, y1 - y0), warns


def plan_size(w, h, scale=None, width=None, max_side=None):
    """目标尺寸 -> (dw, dh, factor)。三个参数**互斥**（同给必报错：
    "缩了再缩"没有唯一解，猜一个不如让人写清）。

    scale=倍率（允许放大）；width=目标宽（允许放大）；max_side=最长边
    上限（**只缩不放**）。都不给 -> 原尺寸。"""
    given = [("scale", scale), ("width", width), ("max_side", max_side)]
    used = [(k, v) for k, v in given if v not in (None, 0, "", 0.0)]
    if len(used) > 1:
        raise ValueError("scale/width/max_side 只能给一个（got %s）"
                         % ", ".join(k for k, _ in used))
    if not used:
        return int(w), int(h), 1.0
    k, v = used[0]
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s 需要数字：%r" % (k, v))
    if v <= 0:
        raise ValueError("%s 必须 > 0（got %r）" % (k, v))
    if k == "scale":
        factor = v
    elif k == "width":
        factor = v / float(w)
    else:                                   # max_side：只缩不放
        factor = min(1.0, v / float(max(w, h)))
    # 四舍五入（+0.5）而不是 round()：round 是银行家舍入，2.5→2、
    # w=3/scale=1.5→4，宽高各自舍入还可能差 1px（审查 P2-7）
    dw = max(1, int(w * factor + 0.5))
    dh = max(1, int(h * factor + 0.5))
    return dw, dh, factor


def _run_ps(spec, timeout=60):
    """跑 _gdi_image.ps1 -> (出图字节, 失败原因|None, ps 报表)。"""
    tmp_spec = None
    try:
        fd, tmp_spec = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ensure_ascii=True：路径里的中文转 \uXXXX，PS 侧零编码风险
            json.dump(spec, fh)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _IMAGE_PS, tmp_spec],
            capture_output=True, timeout=timeout)
        lines = [x for x in r.stdout.decode("utf-8", "replace").splitlines()
                 if x.strip()]
        report = {}
        if lines:
            try:
                report = json.loads(lines[-1])
            except ValueError:
                report = {}
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip()
            return None, "ps_rc=%s: %s" % (r.returncode,
                                           err[:300] or "(无 stderr)"), report
        if not os.path.isfile(spec["out"]):
            return None, "ps 退出 0 但没有输出文件", report
        with open(spec["out"], "rb") as fh:
            return fh.read(), None, report
    except subprocess.TimeoutExpired:
        return None, "ps 超时（%ss）" % timeout, {}
    except Exception as e:  # noqa: BLE001 —— 失败原因如实上抛，不静默降级
        return None, "%s: %s" % (type(e).__name__, str(e)[:200]), {}
    finally:
        if tmp_spec:
            try:
                os.unlink(tmp_spec)
            except OSError:
                pass


def default_out(image, tag="cropped", ext=None):
    """缺省输出：<原名>_<tag><ext>。父目录带点也不会截错（Q07 同款坑）。"""
    base, old = os.path.splitext(str(image))
    return base + "_" + tag + (ext or old or ".png")


def out_path(out, image, tag="cropped", fmt="png"):
    """统一出口路径（v0.4.0 收口：5 处重复的「转 jpeg 就改扩展名」逻辑）。

    - out 为空：`default_out`；
    - out 是**已存在的目录**：目录 + 派生名（别写出一个叫目录名的 .jpg）；
    - 扩展名与格式不一致（fmt=jpeg 但 .png）：换成 .jpg/.png，不写错壳。
    """
    if not out:
        base = default_out(image, tag)
    elif os.path.isdir(str(out)) or str(out)[-1:] in ("/", "\\"):
        # 已存在目录，或「不存在但以分隔符结尾」——后者旧实现会产出
        # "C:/nope/dir/.jpg" 这种隐藏点文件（审查 P2-10）
        base = os.path.join(str(out), os.path.basename(default_out(image, tag)))
    else:
        base = str(out)
    want = ".jpg" if fmt == "jpeg" else ".png"
    root, old = os.path.splitext(base)
    if not old:
        return base + want
    if fmt == "jpeg":
        return base if old.lower() in (".jpg", ".jpeg") else root + want
    return base if old.lower() == ".png" else root + want


def apply(src, crop=None, scale=None, width=None, max_side=None,
          fmt="png", quality=85, dpr=None, timeout=60):
    """裁切 + 缩放 + 编码，一条流水线。

    顺序固定：**先裁后缩**（与 imgtool compose 一致；坐标基数因此是
    「裁切后的图」，收据 coord_space 如实标注）。
    src = **PNG 或 JPEG** 字节（v0.4.0 修正：GDI+ 本来就能读 JPEG，
    只认 PNG 会让「截图存成 .jpg 再裁一刀」报「PNG 坏了」这种误导错）。
    crop=源的 x,y,w,h；dpr 给了表示 crop 是 CSS 像素（乘 dpr）；
    dpr 只在有 crop 时有意义（没裁切就没有坐标可换算，传了直接报错）。
    fmt="png"|"jpeg"；quality 仅 jpeg 用。
    返回 (bytes, info)；失败一律抛错（ValueError 参数错 / RuntimeError
    引擎错），**绝不返回空字节**——交付 0 字节文件等于静默失败（审查 P0）。
    """
    t0 = time.time()
    sz = output.image_size(src)
    if not sz:
        raise ValueError("不是可识别的图片（只支持 PNG/JPEG）：前 8 字节=%r"
                         % (bytes(src[:8]),))
    sw, sh = sz
    raw_fmt = str(fmt).lower()
    if raw_fmt not in FORMATS and raw_fmt != "jpg":
        raise ValueError("fmt 只能是 png/jpeg：%r" % (fmt,))
    fmt = "jpeg" if raw_fmt in ("jpeg", "jpg") else "png"
    try:
        quality = int(quality if quality is not None else 85)
    except (TypeError, ValueError):
        raise ValueError("quality 需要 0~100 的整数：%r" % (quality,))
    if not 1 <= quality <= 100:
        raise ValueError("quality 需在 1~100：%r" % (quality,))
    if not crop and dpr not in (None, "", 0):
        raise ValueError("dpr 只在给了 crop 时有意义（没有裁切就没有坐标"
                         "可换算）：dpr=%r" % (dpr,))

    warns = []
    cbox = None
    if crop:
        if isinstance(crop, str):         # "10,20,300,400" 也认（agent 友好）
            crop = [x for x in crop.replace(" ", ",").split(",") if x.strip()]
        box = list(crop)
        if dpr not in (None, "", 0):
            k = float(dpr)
            if k <= 0:
                raise ValueError("dpr 必须 > 0：%r" % (dpr,))
            box = [float(v) * k for v in box]
        cbox, warns = normalize_crop(box, sw, sh)

    bw, bh = (cbox[2], cbox[3]) if cbox else (sw, sh)
    dw, dh, factor = plan_size(bw, bh, scale=scale, width=width,
                               max_side=max_side)

    info = {"src": [sw, sh], "w": dw, "h": dh,
            "crop": list(cbox) if cbox else None,
            "crop_px": ([cbox[0], cbox[1], cbox[0] + cbox[2],
                         cbox[1] + cbox[3]] if cbox else None),
            "scale": round(factor, 4), "format": fmt,
            "coord_space": "src_px"}
    if warns:
        info["bounds_warn"] = warns
    # 原样返回（无裁切/无缩放/PNG）：省一次进程，且像素零损失
    if (cbox is None and factor == 1.0 and fmt == "png"
            and bytes(src[:8]) == b"\x89PNG\r\n\x1a\n"):
        # v0.5.0：旧实现只判 fmt，JPEG 输入会被原样当 PNG 交出去
        # （扩展名 .png、内容是 JPEG）；现在必须源本身是 PNG 才零拷贝。
        info["engine"] = "passthrough"
        info["bytes"] = len(src)
        info["ms"] = int((time.time() - t0) * 1000)
        return src, info

    # 输出文件先占位、随即删掉：mkstemp 只用来拿唯一路径，unlink 之后
    # 「有没有写出文件」才重新成为有效判据（旧实现留着 0 字节空文件 →
    # 判据恒为真，PS 静默失败时会交付空图；审查 P0-1）。
    # 不用 mkdtemp：本机（Windows + 沙箱）以 0o700 建的目录不可写。
    fd, src_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    fd, out_path = tempfile.mkstemp(suffix=".jpg" if fmt == "jpeg" else ".png")
    os.close(fd)
    os.unlink(out_path)
    try:
        with open(src_path, "wb") as fh:
            fh.write(src)
        spec = {"in": src_path, "out": out_path,
                "crop": list(cbox) if cbox else None,
                "size": [dw, dh] if (dw, dh) != (bw, bh) else None,
                "format": fmt, "quality": quality}
        data, reason, report = _run_ps(spec, timeout=timeout)
        if data is None:
            raise RuntimeError("图像变换失败：%s" % reason)
        magic_ok = (data[:8] == b"\x89PNG\r\n\x1a\n" if fmt == "png"
                    else data[:2] == b"\xff\xd8")
        if len(data) < 64 or not magic_ok:
            raise RuntimeError("引擎输出不是合法 %s（%d 字节，魔数不匹配）"
                               % (fmt, len(data)))
        # ps 报的尺寸才是真的：缺失即失败，不一致即失败（旧实现会短路漏检）
        got = (report.get("w"), report.get("h"))
        if not got[0] or not got[1]:
            raise RuntimeError("引擎没有回报输出尺寸（report=%r）" % (report,))
        if (int(got[0]), int(got[1])) != (dw, dh):
            raise RuntimeError("输出尺寸与请求不一致：请求 %dx%d，引擎报 %sx%s"
                               % (dw, dh, got[0], got[1]))
        info["engine"] = "gdi+"
        info["bytes"] = len(data)
        info["quality"] = quality if fmt == "jpeg" else None
        info["ms"] = int((time.time() - t0) * 1000)
        return data, info
    finally:
        for p in (src_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
