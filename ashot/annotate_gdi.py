# -*- coding: utf-8 -*-
"""Ashot.annotate_gdi —— 矢量标注编排：vector 编译 + GDI+ 光栅化 + 降级。

管线：ops -> vector.compile_ops（几何）-> _gdi_render.ps1（System.Drawing
抗锯齿光栅化，真矢量）-> 若有像素 ops（mosaic/blur/spotlight/smarterase）
再过纯像素画布。PS 任一环节失败 -> 降级 annotate_png（纯像素硬边版），
**并把失败原因如实带出**（v0.2.6 Q08：设计内降级与环境坏了必须可区分）。

出界告警（v0.2.6 Q15）：ps1 用 MeasureString 实测每个 text/dot 的渲染
bbox 回传，本模块对 path 形状自行算 bbox，统一与画布尺寸比对，超界写
`bounds_warn`——**告警优于裁切**（裁切会悄悄丢内容）。

GDI+ 附带红利：DrawString 走系统字体（微软雅黑），**中文文字可标注**，
解除像素版 8x16 点阵仅 ASCII 的限制。
"""
import json
import os
import struct
import subprocess
import tempfile

from . import vector

_HERE = os.path.dirname(os.path.abspath(__file__))
_RENDER_PS = os.path.join(_HERE, "_gdi_render.ps1")

_BOUND_TOL = 1.0    # 亚像素舍入容差：差 1px 以内不算出界


def _png_size(png):
    """PNG IHDR -> (w, h)；坏数据返回 None（告警是附加项，不炸主流程）。"""
    try:
        if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
            return None
        w, h = struct.unpack(">II", bytes(png[16:24]))
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return None


def _parse_boxes(stdout):
    """ps1 末行 JSON -> [{i,x,y,w,h}]；解析失败返回 []（不炸渲染）。"""
    try:
        lines = [x for x in stdout.decode("utf-8", "replace").splitlines()
                 if x.strip()]
        if not lines:
            return []
        obj = json.loads(lines[-1])
        out = []
        for b in obj.get("boxes") or []:
            out.append({"i": int(b.get("i", -1)),
                        "x": float(b.get("x", 0)),
                        "y": float(b.get("y", 0)),
                        "w": float(b.get("w", 0)),
                        "h": float(b.get("h", 0))})
        return out
    except Exception:  # noqa: BLE001
        return []


def _render_ps(spec, timeout=60):
    """spec -> (png_bytes|None, 失败原因|None, 实测 boxes)。

    失败原因只在降级时有用：上层把它写进收据（degrade_reason），
    让「GDI+ 不可用」与「PS 脚本坏了/超时」不再同形。"""
    tmp_in = tmp_out = tmp_spec = None
    reason = None
    try:
        fd, tmp_in = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with open(tmp_in, "wb") as fh:
            fh.write(spec["_src_png"])
        fd, tmp_out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        fd, tmp_spec = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"in": tmp_in, "out": tmp_out,
                       "shapes": spec["shapes"]}, fh, ensure_ascii=False)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _RENDER_PS, tmp_spec],
            capture_output=True, timeout=timeout)
        boxes = _parse_boxes(r.stdout)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip()
            reason = "ps_rc=%s: %s" % (r.returncode, err[:200] or "(无 stderr)")
            return None, reason, boxes
        if not os.path.isfile(tmp_out):
            return None, "ps 退出 0 但没有输出文件", boxes
        with open(tmp_out, "rb") as fh:
            return fh.read(), None, boxes
    except subprocess.TimeoutExpired:
        return None, "ps 超时（%ss）" % timeout, []
    except Exception as e:  # noqa: BLE001 —— 矢量路失败降级，但要留原因
        return None, "%s: %s" % (type(e).__name__, str(e)[:200]), []
    finally:
        for p in (tmp_in, tmp_out, tmp_spec):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _shape_boxes(spec, measured):
    """形状 bbox 汇总 -> [(op_i, kind, x, y, w, h)]。

    path 形状（stroke/fill）由点列精确计算（含半笔宽外扩）；
    text/dot 用 ps1 的 MeasureString 实测值（拿不到就跳过，不瞎估）。
    同一条 op 可能编译成多个 shape（旧式 line 箭头=三笔），取并集。
    """
    by_i = {}
    for b in measured:
        i = b["i"]
        if i < 0:
            continue
        cur = by_i.get(i)
        if cur is None:
            by_i[i] = [b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]]
        else:
            cur[0] = min(cur[0], b["x"])
            cur[1] = min(cur[1], b["y"])
            cur[2] = max(cur[2], b["x"] + b["w"])
            cur[3] = max(cur[3], b["y"] + b["h"])
    out = []
    for sh in spec["shapes"]:
        i = sh.get("i")
        if i is None:
            continue
        t = sh.get("t")
        if t in ("text", "dot"):
            box = by_i.get(i)
            if box is None:
                continue
            out.append((i, t, box[0], box[1], box[2] - box[0],
                        box[3] - box[1]))
        else:
            pts = sh.get("pts") or []
            if not pts:
                continue
            pad = float(sh.get("width", 0)) / 2.0 if t == "stroke" else 0.0
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            x0, y0 = min(xs) - pad, min(ys) - pad
            x1, y1 = max(xs) + pad, max(ys) + pad
            out.append((i, t, x0, y0, x1 - x0, y1 - y0))
    return out


def bounds_warnings(spec, measured, canvas):
    """超界告警（v0.2.6 Q15）-> ["op[2] text 超出右 87px", ...]。"""
    if not canvas:
        return []
    cw, ch = canvas
    warns = []
    for i, kind, x, y, w, h in _shape_boxes(spec, measured):
        over = []
        if x + w - cw > _BOUND_TOL:
            over.append("右 %.0fpx" % (x + w - cw))
        if y + h - ch > _BOUND_TOL:
            over.append("下 %.0fpx" % (y + h - ch))
        if x < -_BOUND_TOL:
            over.append("左 %.0fpx" % (-x))
        if y < -_BOUND_TOL:
            over.append("上 %.0fpx" % (-y))
        if over:
            warns.append("op[%d] %s 超出画布：%s"
                         % (i, kind, "、".join(over)))
    return warns


def _estimate_boxes(spec):
    """像素降级路的 bbox 估算（v0.2.6 二轮审查补）。

    降级时没有 GDI+ 的 MeasureString，但点阵渲染的字宽是确定的
    （每字符 adv=8*sc+2、行高 16*sc+4），按同一套规则估算就能给出
    "出界多少"的告警——否则像素路仍是"静默丢内容"（Q15 的另一半）。"""
    out = []
    for sh in spec["shapes"]:
        i = sh.get("i")
        t = sh.get("t")
        if i is None:
            continue
        if t == "dot":
            r = float(sh.get("r", 0))
            out.append({"i": i, "x": sh["cx"] - r, "y": sh["cy"] - r,
                        "w": 2 * r, "h": 2 * r})
        elif t == "text":
            size = int(float(sh.get("size", 16)))
            sc = max(1, size // 16)
            adv = 8 * sc + 2
            line_h = 16 * sc + 4
            x, y = float(sh["x"]), float(sh["y"])
            maxw = float(sh.get("w") or 0)
            cx, cy = x, y
            right = x
            for ch in str(sh.get("s", "")):
                if ch == "\n":
                    cx, cy = x, cy + line_h
                    continue
                if maxw and cx > x and (cx + adv - x) > maxw:
                    cx, cy = x, cy + line_h
                cx += adv
                right = max(right, cx)
            out.append({"i": i, "x": x, "y": y,
                        "w": max(0.0, right - x), "h": cy + line_h - y})
    return out


def annotate_png_vector(png_bytes, ops, stats=None):
    """矢量标注入口。返回 (png_bytes, backend, pixel_ops)：
    backend: "gdi+"=矢量形状经 GDI+ 渲染成功（像素 ops 若有则另叠加，
             见 pixel_ops——v0.1.8 A 方案：backend 只反映形状渲染后端，
             混合 ops 不再谎报 pixel）；"pixel"=形状降级纯像素画布，
             或无矢量形状（纯像素 ops）。
    pixel_ops: 参与叠加的像素操作数量（恒返回，收据透出）。
    stats: 可选 dict（v0.2.6），写入
      · degrade_reason：矢量路失败原因（仅降级时有）
      · bounds_warn：超界告警列表（有则非空）
      · canvas：画布 (w, h)
    混合 ops（矢量形状+像素操作）：GDI+ 先画形状，像素操作再叠加——
    像素 ops 恒最后生效，与 ops 数组位置无关（设计文档 §7.7.5）。"""
    from . import annotate as _px   # 像素画布（降级路 + 像素 ops 叠加路）
    if stats is None:
        stats = {}
    ops = vector.apply_pad(ops)
    spec = vector.compile_ops(ops)
    spec["_src_png"] = png_bytes
    pixel_n = len(spec["pixel_ops"])
    canvas = _png_size(png_bytes)
    stats["canvas"] = canvas
    out = None
    measured = []
    reason = None
    if spec["shapes"]:
        out, reason, measured = _render_ps(spec)
    if out is None:
        if spec["shapes"]:   # 矢量路失败：整单降级像素版
            stats["degrade_reason"] = reason or "unknown"
            stats["backend_fallback"] = True
            est = _estimate_boxes(spec)
            stats["boxes"] = est
            warns = bounds_warnings(spec, est, canvas)
            if warns:
                stats["bounds_warn"] = warns
            return _px.annotate_png(png_bytes, ops), "pixel", pixel_n
        out = png_bytes      # 纯像素 ops：无矢量形状，跳过 GDI+
        backend = "pixel"
    else:
        backend = "gdi+"
    stats["backend_fallback"] = False
    stats["boxes"] = measured   # 实测 bbox（测试与排障可见）
    if spec["pixel_ops"]:
        cv = _px.Canvas(out)
        for op in spec["pixel_ops"]:
            kind = op.get("kind")
            n = _px._nums(op, "xywh")
            if kind == "mosaic":
                cv.mosaic(*n, block=int(op.get("block", 12)))
            elif kind == "blur":
                cv.blur(*n)
            elif kind == "spotlight":
                cv.spotlight(*n, dim=float(op.get("dim", 0.5)))
            elif kind == "smarterase":
                cv.smarterase(*n)
        out = cv.to_png()
    warns = bounds_warnings(spec, measured, canvas)
    if warns:
        stats["bounds_warn"] = warns
    return out, backend, pixel_n
