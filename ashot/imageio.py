# -*- coding: utf-8 -*-
"""Ashot.imageio —— 图片输入归一化（PNG/JPEG → PNG，v0.5.0）。

为什么需要：`annotate`/`hash`/`diff` 原来只吃 PNG，但 `shot --jpg`、
`crop --jpg` 早就在产出 JPEG——自己产的文件自己读不了，是自相矛盾的
缺口。这里用**已有的 GDI+ 转码路**（`transform.apply`，系统 .NET，
零第三方依赖）把 JPEG 解成 PNG，再进原来的纯 Python 解码器。

边界：
  · 只认 PNG/JPEG（WebP 等 GDI+ 不保证，明确报错，不静默）；
  · 转码失败如实抛错（不返回空字节）；
  · 已缩放/裁切的图不必走这里——那是 transform 的活。
"""
import os

from . import output as _out
from . import transform as _tf

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8"


def is_png(data):
    return bytes(data[:8]) == PNG_MAGIC


def is_jpeg(data):
    return bytes(data[:2]) == JPEG_MAGIC


def format_of(data):
    if is_png(data):
        return "png"
    if is_jpeg(data):
        return "jpeg"
    return "unknown"


def to_png(data):
    """任意支持格式 -> PNG 字节（PNG 原样返回，零拷贝）。"""
    data = bytes(data)
    if is_png(data):
        return data
    if not is_jpeg(data):
        raise ValueError("不是可识别的图片（只支持 PNG/JPEG）：前 8 字节=%r"
                         % (data[:8],))
    w, h = _out.image_size(data) or (0, 0)
    if not w or not h:
        raise ValueError("JPEG 尺寸解析失败（文件可能截断）：%d 字节"
                         % len(data))
    # crop=[0,0,w,h] 是为了绕开 transform 的「PNG 原样返回」快路径，
    # 强制走 GDI+ 重编码成 PNG。
    png, _info = _tf.apply(data, crop=[0, 0, w, h], fmt="png")
    if not is_png(png):
        raise RuntimeError("GDI+ 转码没有产出 PNG（%d 字节）" % len(png))
    return png


def read_png(path):
    with open(path, "rb") as fh:
        return to_png(fh.read())


def info(path):
    """图片信息：{format, w, h, bytes, path}（PNG/JPEG）。"""
    with open(path, "rb") as fh:
        data = fh.read()
    w, h = _out.image_size(data) or (0, 0)
    return {"format": format_of(data), "w": w, "h": h,
            "bytes": len(data), "path": os.path.abspath(path)}
