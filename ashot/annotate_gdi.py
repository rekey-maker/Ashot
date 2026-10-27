# -*- coding: utf-8 -*-
"""Ashot.annotate_gdi —— 矢量标注编排：vector 编译 + GDI+ 光栅化 + 降级。

管线：ops -> vector.compile_ops（几何）-> _gdi_render.ps1（System.Drawing
抗锯齿光栅化，真矢量）-> 若有像素 ops（mosaic/blur/spotlight/smarterase）
再过纯像素画布。PS 任一环节失败 -> 返回 None，上层降级 annotate_png
（纯像素硬边版）——收据如实带 backend 字段。

GDI+ 附带红利：DrawString 走系统字体（微软雅黑），**中文文字可标注**，
解除像素版 8x16 点阵仅 ASCII 的限制。
"""
import json
import os
import subprocess
import tempfile
import time

from . import vector

_HERE = os.path.dirname(os.path.abspath(__file__))
_RENDER_PS = os.path.join(_HERE, "_gdi_render.ps1")


def _render_ps(spec, timeout=60):
    """spec -> GDI+ 渲染 -> PNG bytes；任何失败返回 None（上层降级）。"""
    tmp_in = tmp_out = tmp_spec = None
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
        if r.returncode != 0 or not os.path.isfile(tmp_out):
            return None
        with open(tmp_out, "rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001 —— 矢量路失败静默降级像素版
        return None
    finally:
        for p in (tmp_in, tmp_out, tmp_spec):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def annotate_png_vector(png_bytes, ops):
    """矢量标注入口。返回 (png_bytes, backend)：
    ("gdi+")=矢量抗锯齿成功；("pixel")=降级纯像素画布。
    混合 ops（矢量形状+像素操作）：GDI+ 先画形状，像素操作再叠加。"""
    from . import annotate as _px   # 像素画布（降级路 + 像素 ops 叠加路）
    spec = vector.compile_ops(ops)
    spec["_src_png"] = png_bytes
    out = None
    if spec["shapes"]:
        out = _render_ps(spec)
    if out is None:
        if spec["shapes"]:   # 矢量路失败：整单降级像素版
            return _px.annotate_png(png_bytes, ops), "pixel"
        out = png_bytes      # 纯像素 ops：无矢量形状，跳过 GDI+
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
        return out, "pixel"
    return out, "gdi+"
