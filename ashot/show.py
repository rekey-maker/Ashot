# -*- coding: utf-8 -*-
"""Ashot.show —— 用户可见展示（v0.1.12，自 tmp/show.py 升格入库）。

分工（设计文档 §7.10.3 修正定稿）：preview=true = 模型侧自检通道
（宿主转视觉块喂模型，不渲染给用户）；用户看图 = 本模块产出数据 URL
内嵌 HTML + 会话侧 ::visualize 引用——ZCode 实测唯一被证实的用户可见
通道。base64 数据必须磁盘侧拼装（不过模型上下文），故为正式能力。

模块纪律：缩图/编码复用 output.preview_jpeg（单源）；不碰 capture/
annotate；输出目录由调用方给（::visualize 场景=会话可视化目录，
Ashot 不持有会话状态）。"""
import base64
import html
import os
import re

from . import output

_TEMPLATE = ('<div id="show-%s">\n  <figure style="margin:0">\n'
             '    <img src="data:image/jpeg;base64,%s" alt="%s" '
             'style="max-width:100%%;height:auto">\n'
             '    <figcaption class="text-small text-muted">%s</figcaption>\n'
             '  </figure>\n</div>\n')


def build_html(image_path, title, out_dir, caption=None, width=1200):
    """图片 → <out_dir>/<title>.html（数据 URL 内嵌缩图 JPEG）。
    title 规范化为 [a-z0-9-]（空/超 80 字符如实报错；校验前置——不白跑
    缩图子进程）；caption 缺省=文件名（html.escape）；out_dir 不存在
    自动创建；同 title 重复调用=覆盖（确定性命名，与 output.save 的
    「绝不覆盖」契约无关——本函数产物是展示件不是原件）。返回收据
    {ok, html, title, caption, preview}。"""
    safe = re.sub(r"[^a-z0-9-]+", "-", str(title).lower()).strip("-")
    if not safe:
        raise ValueError("title 规范化后为空：%r" % title)
    if len(safe) > 80:
        raise ValueError("title 过长（规范化后 %d 字符，上限 80）"
                         % len(safe))
    with open(str(image_path), "rb") as fh:
        png = fh.read()
    jpeg, info = output.preview_jpeg(png, width=int(width))
    cap = html.escape(str(caption) if caption is not None
                      else os.path.basename(str(image_path)))
    frag = _TEMPLATE % (safe, base64.b64encode(jpeg).decode(), cap, cap)
    os.makedirs(str(out_dir), exist_ok=True)
    out = os.path.join(str(out_dir), safe + ".html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(frag)
    return {"ok": True, "html": os.path.abspath(out), "title": safe,
            "caption": cap, "preview": info}
