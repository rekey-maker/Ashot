# -*- coding: utf-8 -*-
"""Ashot.mcp —— stdio MCP 脸（零业务，转发 capture/output/annotate）。

范式：alrec_mcp 同款换行分帧 JSON-RPC 2.0；注册宿主 mcp.servers.ashot：
  {"ashot": {"type": "stdio", "command": "python",
             "args": ["<仓库根>/ashot_mcp.py"], "cwd": "<仓库根>"}}
"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import (__version__, annotate, annotate_gdi, capture, cdp, dom, fonts,  # noqa: E402
                   imageio, output, show, transform, vision)
from ashot._coerce import as_bool, as_int  # noqa: E402

TOOLS = {}

# 参数名 -> 语义类型（v0.2.6 审计）：这些是像素坐标/计数/端口，默认值
# 为 None 时也能给出正确 schema，别让 agent 猜"要不要加引号"。
_NUMERIC_PARAMS = frozenset((
    "port", "screen", "index", "x", "y", "x1", "y1", "x2", "y2",
    "from_x", "from_y", "dx", "dy", "count", "steps",
))


def _tool(fn):
    """简易 schema：从默认值推 required/optional + **按默认值推类型**
    （v0.2.6 Q13：旧实现一律 {"type":"string"}，连 x/y/count 都是字符串，
    agent 得猜要不要加引号）。无默认值的参数仍按 string 声明（是否数字
    由工具内自转型决定），有默认值的按 bool/int/float/str 声明；
    坐标/端口/计数类参数按名字兜底为 integer（默认 None 也判得准）。"""
    code = fn.__code__
    names = code.co_varnames[:code.co_argcount]
    defaults = fn.__defaults__ or ()
    req = list(names[:len(names) - len(defaults)])
    props = {}
    dmap = dict(zip(names[len(names) - len(defaults):], defaults))
    for n in names:
        d = dmap.get(n, None)
        if isinstance(d, bool):
            t = "boolean"
        elif isinstance(d, int):
            t = "integer"
        elif isinstance(d, float):
            t = "number"
        elif n in _NUMERIC_PARAMS:
            t = "integer"
        else:
            t = "string"
        props[n] = {"type": t}
    TOOLS[fn.__name__] = {
        "name": fn.__name__,
        "description": fn.__doc__ or "",
        "inputSchema": {"type": "object", "properties": props,
                        "required": req},
    }
    return fn


def _content_with_image(receipt_text, jpeg):
    """预览内容块（v0.1.11）：文本收据 + ImageContent（audience:user，
    语义「给用户看」；宿主是否渲染/是否喂模型由宿主实现决定——设计
    文档 §7.10 实验协议）。"""
    return [
        {"type": "text", "text": receipt_text},
        {"type": "image", "data": base64.b64encode(jpeg).decode(),
         "mimeType": "image/jpeg",
         "annotations": {"audience": ["user"], "priority": 0.9}},
    ]


def _parse_area(area):
    """area 三种写法都认（v0.2.6 实弹）：JSON 数组 "[l,t,w,h]"、
    逗号串 "0,0,800,600"、空格串 "0 0 800 600"。
    旧实现只认 JSON，agent 按 CLI 习惯传逗号串时直接 JSONDecodeError。"""
    s = str(area).strip()
    if not s:
        return None
    if s.startswith("["):
        return json.loads(s)
    parts = [x.strip() for x in s.replace(" ", ",").split(",") if x.strip()]
    if len(parts) != 4:
        raise ValueError('area 需要 4 个整数（"[l,t,w,h]" 或 "l,t,w,h"）：%r'
                         % area)
    return [int(float(x)) for x in parts]


def _shot(mode="full", screen=None, out=None, clip=False, keep=False,
          area=None, retention_days=30, preview=True, scale=0.0,
          max_side=0, jpg=0, quality=85):
    """桌面截图：mode=full(全虚拟桌面)/screen(单屏,screen=序号)/win(前台窗口)
    /area(区域,area=[l,t,w,h])。返回图片绝对路径；clip=true 只进剪贴板
    不落盘（**clip 与 preview 同传时 clip 优先，preview 被忽略**）。
    每次运行顺手清理超 retention_days 的旧图（keep=true 跳过）。

    **v0.4.0：截完可直接缩放/压缩**（不必再调一次 ashot_resize）——
    scale>0 倍率（允许放大，如 0.5 / 1.5）、max_side>0 最长边上限
    （**只缩不放**，如 1600）、jpg>0 直接存 JPEG（质量 jpg；out 以 .jpg
    结尾也自动转）。收据带 src/w/h/format/bytes，一眼看出缩没缩。
    clip=true 时缩放在 PNG 上做（剪贴板要位图），jpg 只影响落盘。

    preview **缺省 true**（v0.2.6 Q16）：收据升级多内容块，附 1200px /
    ≤200KB JPEG 缩图 ImageContent——模型不必再 read_image 多一跳。
    preview=false 退回旧单字符串收据（省上下文/省一次缩图进程）。
    收据另带 box_source（virtual/screen/dwm/rect/area）与 gdi_error
    （主路失败原因，兜底成功时也在）。"""
    if isinstance(area, str):
        area = _parse_area(area)
    r = capture.shot(mode=mode or "full", screen=screen, area=area)
    all_black = None
    if r["kind"] == "raw":
        png = output.bgra_to_png(r["w"], r["h"], r["bgra"])
        all_black = capture.is_all_black(r["bgra"], r["w"], r["h"])
    else:
        png = r["png"]   # PS 兜底路径是 PNG 字节，黑帧检测不拆解（如实 None）
    fmt, q = _fmt_choice(jpg, quality, out)
    if as_bool(clip):
        if scale or max_side:   # 剪贴板要位图：缩放在 PNG 上做，不转 JPEG
            png, _t = transform.apply(png, scale=scale, max_side=max_side)
        if not output.clip_png(png):
            raise RuntimeError("剪贴板写入失败")
        return json.dumps({"ok": True, "clipboard": True}, ensure_ascii=False)
    receipt = {"ok": True, "all_black": all_black,
               "box_source": r.get("box_source")}
    if scale or max_side or fmt == "jpeg":
        png, tinfo = transform.apply(png, scale=scale, max_side=max_side,
                                     fmt=fmt, quality=q)
        for k in ("src", "w", "h", "format", "bytes", "engine", "ms"):
            if k in tinfo:
                receipt[k] = tinfo[k]
    path = output.save(png, out=out,
                       ext=".jpg" if fmt == "jpeg" else ".png")
    n, mb = output.gc(retention_days=as_int(retention_days, 30),
                      keep=as_bool(keep))
    receipt["path"] = path
    receipt["gc"] = {"removed": n, "freed_mb": round(mb, 1)}
    if r.get("gdi_error"):
        receipt["gdi_error"] = r["gdi_error"]   # Q09：降级原因不静默
    if as_bool(preview):
        try:
            jpeg, info = output.preview_jpeg(png)
            receipt["preview"] = info
            return _content_with_image(json.dumps(receipt,
                                                  ensure_ascii=False), jpeg)
        except Exception as e:  # noqa: BLE001 —— 预览失败不吞主收据（审计 P2-1）
            receipt["preview"] = {"error": "%s: %s"
                                  % (type(e).__name__, str(e)[:200])}
    return json.dumps(receipt, ensure_ascii=False)


def _screens():
    """列出显示器（index/分辨率/偏移/主屏标记）。"""
    return json.dumps({"ok": True, "screens": capture.list_screens()},
                      ensure_ascii=False)


def _annotate(image, ops, out=None, preview=True, jpg=0, quality=85,
              max_side=0, dpr=0.0):
    """对既有 PNG/JPEG 标注：ops=JSON 数组，kind ∈ rect/ellipse/arrow/line/
    **v0.4.1 新增 curve(三次贝塞尔 x0,y0,c1x,c1y,c2x,c2y,x1,y1)/
    arc(x,y,w,h,start,sweep 度、顺时针)/polyline(points 或 coords)**——
    与箭头同一条原理：Python 采样成点列 → GDI+ 抗锯齿描边。
    text(中文可标注，GDI+ 系统字体；v0.1.9 起可选 font=字体族名/bold=
    粗体开关，缺省微软雅黑+粗体；未安装字体名静默回退默认；font/bold
    仅矢量路生效，像素降级路不认；**v0.2.6 起 text 可带 w=布局宽，
    由 GDI+ 按真实字体度量自动换行**)/mosaic/blur/step(自动递增编号)/
    number(显式编号 value)/spotlight(聚光灯 dim)/smarterase(智能擦除)。
    矢量抗锯齿渲染（GDI+），失败自动降级纯像素画布——**降级原因写进
    degrade_reason**（v0.2.6 Q08，设计内降级 vs 环境坏了可区分）。
    收据 backend=形状渲染后端（gdi+=矢量成功/pixel=降级或纯像素，混合
    ops 时 gdi+ 仍成立）；pixel_ops=像素操作数量；bounds_warn=实测超界
    告警（v0.2.6 Q15，ps1 MeasureString 实测，非估算）。
    像素 ops 恒在形状之后叠加（与 ops 数组顺序无关）。
    **v0.4.0**：jpg>0 = 标注后输出 JPEG（质量为 jpg；out 以 .jpg 结尾
    也自动转，质量取 quality）；max_side>0 = 顺带限制最长边（只缩不放）。
    preview **缺省 true**（v0.2.6 Q16）：收据升级多内容块 + ≤200KB JPEG。
    返回标注后 PNG 绝对路径；out 缺省写 <原名>_annotated.png——绝不覆盖
    原图（v0.1.5 P1 根修）。
    **v0.5.0**：image 支持 PNG/JPEG；**dpr>0 时 ops 坐标按 CSS→物理
    像素缩放（只缩放坐标，字号/线宽不变，缺省 0=不换算）**；text 的
    `w`（布局宽）也会被缩放，换行位置可能变。"""
    png = imageio.read_png(str(image))
    ops_list = json.loads(ops) if isinstance(ops, str) else ops
    if dpr:
        ops_list = annotate.scale_ops(ops_list or [], dpr)
    stats = {}
    out_bytes, backend, pixel_n = annotate_gdi.annotate_png_vector(
        png, ops_list or [], stats=stats)
    fmt, q = _fmt_choice(jpg, quality, out)
    path = transform.out_path(out, image, "annotated", fmt)
    receipt = {"ok": True, "backend": backend, "pixel_ops": pixel_n}
    if stats.get("degrade_reason"):
        receipt["degrade_reason"] = stats["degrade_reason"]
        receipt["backend_fallback"] = True
    if stats.get("bounds_warn"):
        receipt["bounds_warn"] = stats["bounds_warn"]
    if fmt == "jpeg" or int(max_side or 0) > 0:
        out_bytes, tinfo = transform.apply(
            out_bytes, max_side=int(max_side or 0), fmt=fmt, quality=q)
        for k in ("w", "h", "format", "bytes", "engine", "ms"):
            if k in tinfo:
                receipt[k] = tinfo[k]
    path = output.save(out_bytes, out=path)
    receipt["path"] = path
    if as_bool(preview):
        try:
            jpeg, info = output.preview_jpeg(out_bytes)
            receipt["preview"] = info
            return _content_with_image(json.dumps(receipt,
                                                  ensure_ascii=False), jpeg)
        except Exception as e:  # noqa: BLE001 —— 预览失败不吞主收据（审计 P2-1）
            receipt["preview"] = {"error": "%s: %s"
                                  % (type(e).__name__, str(e)[:200])}
    return json.dumps(receipt, ensure_ascii=False)


def _crop(image, box, out=None, scale=0.0, width=0, max_side=0, jpg=0,
          quality=85, dpr=0.0, preview=True):
    """裁切既有图片（v0.4.0，补 imgtool 的裁切缺口）：box="x,y,w,h"
    （**源图像素**的左上角+宽高，**不是** x1,y1,x2,y2）。
    dpr>0 表示 box 给的是 CSS 像素（如浏览器 DevTools 的
    getBoundingClientRect），内部先乘 dpr——省掉手算，也避免
    「CSS 当像素用」这类静默错位。
    顺带缩放：scale>0 倍率（允许放大）/ width>0 目标宽 / max_side>0
    最长边（只缩不放）——三选一。jpg>0 直接输出 JPEG（质量 jpg）。
    **越界处理**：夹到图边并写 bounds_warn（不静默裁掉内容、也不整单
    失败）；区域完全在图外才报错。收据回显 crop(x,y,w,h) 与
    crop_px(x0,y0,x1,y1)——box 语义写反时一眼可见。
    preview 缺省 true（附缩图，方便确认裁对了）。本工具需宿主重连后
    才会出现在工具表。"""
    with open(str(image), "rb") as fh:
        png = fh.read()
    fmt, q = _fmt_choice(jpg, quality, out)
    data, info = transform.apply(
        png, crop=_parse_box(box), scale=scale, width=width,
        max_side=max_side, fmt=fmt, quality=q, dpr=dpr)
    path = transform.out_path(out, image, "cropped", fmt)
    rec = {"ok": True, "path": output.save(data, out=path)}
    rec.update(info)
    return _maybe_preview(rec, data, preview)


def _resize(image, out=None, scale=0.0, width=0, max_side=0, jpg=0,
            quality=85, preview=True):
    """缩放既有图片（v0.4.0）：scale=倍率（允许放大）/ width=目标宽 /
    max_side=最长边上限（**只缩不放**）——三选一，同给必报错。
    jpg>0 输出 JPEG（质量 jpg）；out 以 .jpg 结尾也自动转。
    收据含 src/w/h/scale/format/bytes/engine（gdi+=系统 GDI+ 高质量
    双三次；失败如实报错，不静默降质）。preview 缺省 true。
    本工具需宿主重连后才会出现在工具表。"""
    with open(str(image), "rb") as fh:
        png = fh.read()
    if not (scale or width or max_side):
        raise ValueError("resize 至少给 scale / width / max_side 之一")
    fmt, q = _fmt_choice(jpg, quality, out)
    data, info = transform.apply(png, scale=scale, width=width,
                                 max_side=max_side, fmt=fmt, quality=q)
    path = transform.out_path(out, image, "resized", fmt)
    rec = {"ok": True, "path": output.save(data, out=path)}
    rec.update(info)
    return _maybe_preview(rec, data, preview)


def _parse_box(box):
    """"x,y,w,h"（也收空格分隔或 JSON 数组）-> [x,y,w,h]。与 ashot_shot
    的 area 解析同款，agent 不必记两套引号规则。"""
    if isinstance(box, (list, tuple)):
        return list(box)
    s = str(box).strip()
    if s.startswith("["):
        vals = json.loads(s)
        if not isinstance(vals, (list, tuple)) or len(vals) != 4:
            raise ValueError('box 需要 4 个数字 x,y,w,h：%r' % (box,))
        return list(vals)
    parts = [x.strip() for x in s.replace(" ", ",").split(",") if x.strip()]
    if len(parts) != 4:
        raise ValueError('box 需要 4 个数字 x,y,w,h（"10,20,300,400"）：%r'
                         % (box,))
    return [float(x) for x in parts]


def _fmt_choice(jpg, quality, out):
    """-> (fmt, quality)。jpg>0 显式 JPEG；否则看输出扩展名。"""
    if int(jpg or 0) > 0:
        return "jpeg", int(jpg)
    if str(out or "").lower().endswith((".jpg", ".jpeg")):
        return "jpeg", int(quality or 85)
    return "png", int(quality or 85)


def _maybe_preview(rec, data, preview):
    if as_bool(preview):
        try:
            jpeg, info = output.preview_jpeg(data)
            rec["preview"] = info
            return _content_with_image(json.dumps(rec, ensure_ascii=False),
                                       jpeg)
        except Exception as e:  # noqa: BLE001 —— 预览失败不吞主收据
            rec["preview"] = {"error": "%s: %s"
                              % (type(e).__name__, str(e)[:200])}
    return json.dumps(rec, ensure_ascii=False)


def _tool_named(name, fn):
    _tool(fn)
    entry = TOOLS.pop(fn.__name__)
    entry["name"] = name
    entry["_fn"] = fn
    TOOLS[name] = entry


def _fonts(filter=None, refresh=False):
    """列出系统已装字体族名（v0.1.10）。数据源与渲染器同源
    （.NET InstalledFontCollection）——查出的名字保证 text op 的 font
    字段可解析（未装名会静默回退默认字体，先查后用）。filter=不区分
    大小写子串过滤；refresh=true 强制重枚举（v0.2.6 Q11；缺省走 300s
    缓存——常驻进程装了新字体最多等 5 分钟，或显式 refresh）。
    收据 {ok, count, families:[...]}。本工具需宿主重连后才会出现在工具表。"""
    names = fonts.list_families(filter, refresh=as_bool(refresh))
    return json.dumps({"ok": True, "count": len(names),
                       "families": names}, ensure_ascii=False)


def _show(image, title, out_dir, caption=None, width=1200):
    """用户可见展示（v0.1.12）：图片 → 缩图 JPEG → base64 内嵌 HTML
    片段落 <out_dir>/<title>.html。MCP ImageContent 只喂模型不渲染
    用户（ZCode 实测，设计文档 §7.10.3 修正定稿）——用户看图唯一被
    证实通道 = 数据 URL 内嵌 + 会话侧 ::visualize 引用。out_dir=会话
    可视化目录（必填——::visualize 只渲染该目录内文件）。width 缩图
    宽（不放大）。本工具需宿主重连后才会出现在工具表。返回收据
    {ok, html, title, caption, preview}。"""
    return json.dumps(show.build_html(image, title, out_dir,
                                      caption=caption,
                                      width=int(width or 1200)),
                      ensure_ascii=False)


def _cdp_tabs(port=None):
    """列 CDP 浏览器（Chromium 家族）的 page 标签页（v0.2.0）。port=
    调试端口（缺省=discover：进程命令行→DevToolsActivePort→常见端口，
    审计 P1-2）。无头/有头通吃、与 AI 宿主无关。
    多实例时返回**分组结果**（groups:[{port, tabs}]），只读安全。
    收据 {ok, port, tabs, groups}。本工具需宿主重连后才会出现在工具表。"""
    if port in (None, "", 0):
        disc = cdp.discover()
        if not disc["ports"]:
            raise RuntimeError(disc["hint"])
        if len(disc["ports"]) > 1:
            groups = []
            for p in disc["ports"]:
                try:
                    groups.append({"port": int(p), "tabs": cdp.tabs(int(p))})
                except Exception as e:  # noqa: BLE001 —— 单个读失败如实标记
                    groups.append({"port": int(p), "error":
                                   "%s: %s" % (type(e).__name__,
                                               str(e)[:120])})
            return json.dumps({"ok": True, "ambiguous": True,
                               "port": None, "tabs": [],
                               "groups": groups,
                               "hint": "多实例：下一步操作请显式带 --port"},
                              ensure_ascii=False)
        port = disc["ports"][0]
    return json.dumps({"ok": True, "port": int(port),
                       "tabs": cdp.tabs(int(port))}, ensure_ascii=False)


def _cdp_shot(port=None, index=0, fullpage=True, out=None, preview=True,
              stitch=True):
    """CDP 浏览器标签页截图（v0.2.0）：Page.captureScreenshot，
    无头/有头通吃、与 AI 宿主无关（设计文档 v0.2.0 §4.2）。port 缺省
    =discover；index=第几个 page 标签；fullpage=captureBeyondViewport
    （Chrome 90+，视口外也截）。**超长页**（>16384px）自动滚动拼接，
    stitch=false 关闭。Chrome 136+ 默认 profile 拒远程调试
    （default_profile_denied）——用非默认 --user-data-dir 启动。返回
    截图 PNG 路径；收据含 dpr、**to_css**（截图像素 × to_css = 点击用的
    CSS 坐标）与 coord_space（viewport/document——全页截图是文档坐标，
    点首屏以下要先减 scrollY，v0.2.6 Q06）。preview 缺省 true（Q16）。
    本工具需宿主重连后才会出现在工具表。"""
    ws_url = _resolve_ws(port, index)
    png, info = cdp.shot(None, ws=ws_url,
                         fullpage=as_bool(fullpage, True),
                         stitch=as_bool(stitch, True))
    path = output.save(png, out=out)
    rec = {"ok": True, "path": path}
    for k in ("w", "h", "vw", "vh", "dpr", "to_css", "coord_space",
              "scroll_y", "hint", "fullpage", "fullpage_truncated",
              "stitched", "shots", "stitch_error", "fixed_hidden"):
        if k in info:
            rec[k] = info[k]
    if as_bool(preview):
        try:
            jpeg, pinfo = output.preview_jpeg(png)
            rec["preview"] = pinfo
            return _content_with_image(json.dumps(rec, ensure_ascii=False),
                                       jpeg)
        except Exception as e:  # noqa: BLE001
            rec["preview"] = {"error": "%s: %s"
                              % (type(e).__name__, str(e)[:200])}
    return json.dumps(rec, ensure_ascii=False)


def _cdp_view(port=None, index=0, ws=None, timeout=15):
    """CDP 标签页视口信息（v0.2.5）：vw/vh = CSS 像素视口尺寸，
    dpr = devicePixelRatio，content_w/h = 整页内容尺寸。
    截图出图是物理像素（= CSS × dpr），直接拿截图坐标去点击必然落空。"""
    ws_url = _resolve_ws(port, index, ws)
    lay, dpr = cdp.layout(ws_url, timeout=int(timeout or 15))
    rec = {"ok": True, "vw": lay["vw"], "vh": lay["vh"],
           "content_w": lay["content_w"], "content_h": lay["content_h"],
           "dpr": dpr}
    if lay.get("scroll_y") is not None:
        rec["scroll_y"] = lay["scroll_y"]
    if lay["vw"] and lay["vh"] and dpr:
        rec["hint"] = ("截图按 dpr=%s 放大（物理=%sx%s），点击请用 CSS 坐标"
                       % (dpr, int(lay["vw"] * dpr), int(lay["vh"] * dpr)))
    return json.dumps(rec, ensure_ascii=False)


def _cdp_eval(js, port=None, index=0, ws=None, await_promise=False,
              timeout=30):
    """在 CDP 标签页里跑一段 JS 并取值（v0.2.5）。js 可写函数体（内部
    return）或表达式。用途：算坐标、读页面状态确认操作生效、拿 dpr。
    **只发 Runtime.evaluate，绝不发 Runtime.enable**（字节系检测点，
    一发即杀实例）。收据 {ok, value, value_type, exception}——异常如实
    带出不静默；value_type 区分 null / undefined / 不可序列化对象
    （v0.2.6 Q14：三者旧收据同形 None）。"""
    ws_url = _resolve_ws(port, index, ws)
    res = cdp.evaluate(ws_url, js, timeout=as_int(timeout, 30),
                       await_promise=as_bool(await_promise))
    exc = res.get("exceptionDetails")
    rec = {"ok": exc is None}
    if exc:
        rec["exception"] = ((exc.get("exception") or {}).get("description")
                            or exc.get("text") or str(exc)[:200])
    else:
        res_obj = res.get("result") or {}
        vtype = res_obj.get("type")
        rec["value"] = res_obj.get("value")
        rec["value_type"] = vtype
        if vtype == "undefined":
            rec["note"] = "undefined（多半传了表达式却没写 return）"
        elif (vtype == "object" and res_obj.get("value") is None
              and res_obj.get("subtype") not in ("null", "array")):
            # null 是合法结果；数组在 returnByValue 下 value 有值——
            # 只有"对象但没值"才是不可序列化（v0.2.6 审计修正）
            rec["note"] = ("对象未按值返回（不可序列化）——请 return 具体字段，"
                           "如 return document.title")
    return json.dumps(rec, ensure_ascii=False)


_LAST_TARGET = {}   # 最近一次解析出的目标身份（收据盖章用，stdio 单线程）


def _resolve_ws(port, index=0, ws=None, allow_multi=False):
    """cdp 工具公共解析：-> page ws，并记录目标身份（v0.2.6 Q04）。

    安全边界：discover 多实例时输入类动作**必须显式 --port**；单实例
    也不再"静默命中"——target（端口/进程名/页签 title+url/扫描警告）
    由 _serve 盖进收据，agent 能一眼看出这是不是自己的浏览器。"""
    _LAST_TARGET.clear()   # 先清：解析失败时不会把上一次的目标带进来
    if ws:
        _LAST_TARGET["ws"] = ws
        return ws
    p, info = cdp.pick_port(port, allow_multi=allow_multi)
    info = dict(info)
    info.update({k: v for k, v in cdp.target_info(p, index).items()
                 if k != "port"})
    _LAST_TARGET.update(info)   # 就地更新（与 _serve 的 clear 同一对象）
    return cdp.ws_for(p, index=int(index or 0))


def _cdp_key(key, text=None, modifiers=None, port=None, index=0, ws=None):
    """CDP 按键/组合键/文本注入（v0.2.0 §4.2.2）：key=键名（a/enter/
    tab/arrowup/s…）；modifiers=组合键 "ctrl+shift"（位掩码
    Alt1/Ctrl2/Meta4/Shift8）；text=覆盖产生的文本（如中文）。可见
    字符 rawKeyDown+char 双发，控制键 keyDown+keyUp。返回
    {ok, dispatched}。需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    mods = modifiers if isinstance(modifiers, int) else (modifiers or 0)
    seq = cdp.key_events(key, mods, text=text)
    n, unresolved = cdp.dispatch(ws_url, seq)
    rec = {"ok": True, "dispatched": n}
    if unresolved:
        rec["unresolved_keys"] = unresolved   # 无 VK 码透传，如实亮牌
    return json.dumps(rec, ensure_ascii=False)


def _cdp_wheel(dx=0, dy=600, x=100, y=100, port=None, index=0, ws=None):
    """CDP 鼠标滚轮（v0.2.0）：dy 正=向下滚动，dx 横向；x/y=事件坐标
    （CSS 像素）。返回 {ok, dispatched}。需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    ev = {"type": "mouseWheel", "x": int(x), "y": int(y),
          "deltaX": int(dx), "deltaY": int(dy), "modifiers": 0}
    n, _ = cdp.dispatch(ws_url, [ev])
    return json.dumps({"ok": True, "dispatched": n}, ensure_ascii=False)


def _cdp_click(x, y, button="left", human=True, seed=None, port=None,
               index=0, ws=None, timing=True, verify="",
               from_x=None, from_y=None):
    """CDP 鼠标单击（v0.2.0/0.2.4）：x/y=CSS 像素；button=left/right/
    middle；human=True（缺省）先沿人类化贝塞尔轨迹移动到位（带微抖动、
    有节奏地靠近），timing=false 或 --teleport 可退回瞬移（批处理时省掉
    每次约 200ms 的靠近耗时）。
    from_x/from_y=接近轨迹起点（v0.2.6 Q12；缺省在目标周围随机方位，
    不再恒从屏幕左上角出发——那是稳定指纹）。
    verify=一段 JS（可选）：点完立刻求值，结果进收据 verify 字段——
    **dispatched 只说明事件发出去了，不说明生效**（v0.2.5 诚实化）。
    返回 {ok, dispatched}。需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    start = (from_x, from_y) if (from_x is not None and
                                 from_y is not None) else None
    seq = cdp.click_events(int(x), int(y), button=button,
                           human=as_bool(human, True),
                           seed=int(seed) if seed not in (None, "") else None,
                           start=start)
    t0 = time.time()
    n, _ = cdp.dispatch(ws_url, seq, realtime=as_bool(timing, True))
    rec = {"ok": True, "dispatched": n,
           "seconds": round(time.time() - t0, 2)}
    if verify:
        try:
            r = cdp.evaluate(ws_url, verify)
            exc = r.get("exceptionDetails")
            rec["verify"] = ({"exception": str(exc)[:200]} if exc
                             else (r.get("result") or {}).get("value"))
        except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
            rec["verify"] = {"error": "%s: %s" % (type(e).__name__,
                                                  str(e)[:160])}
    return json.dumps(rec, ensure_ascii=False)


def _cdp_drag(x1, y1, x2, y2, steps=0, button="left", human=True,
              seed=None, port=None, index=0, ws=None, pace="normal",
              total_ms=None, constrained=True, max_perp=2.5,
              timing=True, verify=""):
    """CDP 鼠标拖拽（v0.2.4/0.2.5）：按下 → 节奏化移动 → 末端过冲回退
    → 松手。

    pace=节奏档（**速度可调，用户 2026-10-28 要求**）：
      · normal（缺省）≈ 260 + dist×1.1 ms，夹在 320~1400ms
      · **captcha ≈ 700 + dist×2.4 ms，夹在 900~2600ms——过验证码用这档**
      · fast ≈ 120 + dist×0.45 ms，夹在 150~600ms（批处理/不赶风控时用）
    total_ms=显式指定总时长（**优先于 pace**）；给 0 = 不睡、全速派发。
    timing=false 也能一键关掉所有等待（等价于全速）。
    constrained=true（缺省）= 受轨道约束（垂直偏移 ≤ max_perp），
    拖滑块/进度条/分栏必须开；false=自由拖拽（画图框选）走贝塞尔弧线。
    human=false = 直线插值（旧行为，最像机器，仅供对照）。
    verify=一段 JS（可选）：拖完立刻求值，结果进收据——用来确认真的拖到了。

    返回 {ok, dispatched, seconds, pace, constrained}。需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    seq = cdp.drag_events(
        x1, y1, x2, y2,
            steps=int(steps) if steps not in (None, "", 0) else 0,
            button=button,
            human=as_bool(human, True),
            seed=int(seed) if seed not in (None, "") else None,
        constrained=as_bool(constrained, True),
        max_perp=float(max_perp or 2.5),
        total_ms=(None if total_ms in (None, "") else float(total_ms)),
        pace=pace or "normal")
    stats = {}
    t0 = time.time()
    n, _ = cdp.dispatch(ws_url, seq, realtime=as_bool(timing, True),
                        stats=stats)
    rec = {"ok": True, "dispatched": n,
           "seconds": round(time.time() - t0, 2),
           "pace": str(pace or "normal"),
           "timing": as_bool(timing, True),
           "constrained": as_bool(constrained, True),
           "max_perp": float(max_perp or 2.5)}
    if stats.get("planned_ms"):
        rec["planned_ms"] = stats["planned_ms"]
    if stats.get("clipped_ms"):
        rec["clipped_ms"] = stats["clipped_ms"]
        rec["hint"] = "等待被 3s 上限夹断，实际节奏比请求慢档短"
    if verify:
        try:
            r = cdp.evaluate(ws_url, verify)
            exc = r.get("exceptionDetails")
            rec["verify"] = ({"exception": str(exc)[:200]} if exc
                             else (r.get("result") or {}).get("value"))
        except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
            rec["verify"] = {"error": "%s: %s" % (type(e).__name__,
                                                  str(e)[:160])}
    return json.dumps(rec, ensure_ascii=False)


def _cdp_dblclick(x, y, button="left", count=2, human=True, seed=None,
                  port=None, index=0, ws=None, from_x=None, from_y=None):
    """CDP 双击/多击（v0.2.3/0.2.4）：clickCount 递增序列，浏览器据此
    合成 dblclick 事件；human=True（缺省）先人类化轨迹到位。x/y=CSS
    像素；from_x/from_y 可选起点（v0.2.6 Q12）。返回 {ok, dispatched}。
    需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    start = (from_x, from_y) if (from_x is not None and
                                 from_y is not None) else None
    seq = cdp.dblclick_events(x, y, button=button, count=int(count or 2),
                              human=as_bool(human, True),
                              seed=int(seed) if seed not in (None,
                                                             "") else None,
                              start=start)
    n, _ = cdp.dispatch(ws_url, seq)
    return json.dumps({"ok": True, "dispatched": n}, ensure_ascii=False)


def _cdp_type(text, x=None, y=None, port=None, index=0, ws=None,
              verify=""):
    """CDP 整段文本输入（v0.2.3 填表利器）：Input.insertText 粘贴式
    （不逐键击、不触发每键 keydown）。x/y 可选——先点击聚焦输入框
    再输入。**与用户键鼠天然隔离**：CDP 事件只进指定标签页，不占用户
    键盘（v0.2.0 §4.2.2）。verify=一段 JS（可选）：输完立刻求值
    （如 `return document.activeElement.value`），结果进收据——用来
    确认字真的进去了。返回 {ok, dispatched}。需宿主重连出现。"""
    ws_url = _resolve_ws(port, index, ws)
    seq = ([{"type": "mouseMoved", "x": int(x), "y": int(y),
             "modifiers": 0},
            {"type": "mousePressed", "x": int(x), "y": int(y),
             "button": "left", "buttons": 1, "clickCount": 1,
             "modifiers": 0},
            {"type": "mouseReleased", "x": int(x), "y": int(y),
             "button": "left", "buttons": 0, "clickCount": 1,
             "modifiers": 0}] if x is not None and y is not None
        else []) + cdp.insert_text_events(text)
    n, _ = cdp.dispatch(ws_url, seq)
    rec = {"ok": True, "dispatched": n}
    if verify:
        try:
            r = cdp.evaluate(ws_url, verify)
            exc = r.get("exceptionDetails")
            rec["verify"] = ({"exception": str(exc)[:200]} if exc
                             else (r.get("result") or {}).get("value"))
        except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
            rec["verify"] = {"error": "%s: %s" % (type(e).__name__,
                                                  str(e)[:160])}
    return json.dumps(rec, ensure_ascii=False)


def _hash(image, algo="dhash"):
    """图像指纹（v0.2.7）：sha256（精确）+ dhash/ahash（感知，64 bit 十六
    进制）。用途：截图去重、页面变化监控、UI 回归。algo 指定时收据额外给
    `value`。收据 {ok, sha256, dhash, ahash, w, h, value?}。"""
    png = imageio.read_png(str(image))
    rec = vision.digest(png)
    if algo:
        rec["value"] = rec.get(str(algo))
    rec["ok"] = True
    return json.dumps(rec, ensure_ascii=False)


def _diff(a, b, threshold=0.12, out=None):
    """两张 PNG 差异（v0.2.7）：YIQ 颜色距离 + threshold（0~1），返回
    changed_px/ratio/bbox/size_mismatch；out 给了就落盘差异图（未变区域
    压暗、变化像素涂红）。**未做 pixelmatch 式抗锯齿检测**——字体边缘
    可能有少量假差异，收据 note 会写明。"""
    pa = imageio.read_png(str(a))
    pb = imageio.read_png(str(b))
    rec = vision.diff(pa, pb, threshold=float(threshold or 0.12),
                      make_image=bool(out))
    img = rec.pop("image", None)
    if out and img:
        rec["out"] = output.save(img, out=out)
    rec["ok"] = True
    return json.dumps(rec, ensure_ascii=False)


def _element(selector, port=None, index=0, ws=None, scroll=False):
    """元素在视口里的 CSS 矩形 + 可见性（v0.2.7）：x/y/w/h/cx/cy、
    visible（checkVisibility）/in_viewport/visible_ratio/occluded
    （elementFromPoint 中心）/pointer_events/dpr/scroll。**坐标是主页面
    视口 CSS 像素，可直接喂 cdp_click**；截图坐标要先乘 to_css。"""
    ws_url = _resolve_ws(port, index, ws)
    rec = dom.element_rect(ws_url, selector, scroll=as_bool(scroll))
    rec["ok"] = True
    return json.dumps(rec, ensure_ascii=False)


def _frames(port=None, index=0, ws=None):
    """frame 树（v0.2.7）：id/url/name/parent_id/depth，尽力附 iframe
    自身矩形（跨站 OOPIF 拿不到就留空）。收据 {ok, frames:[...]}。"""
    ws_url = _resolve_ws(port, index, ws)
    return json.dumps({"ok": True, "frames": dom.frames(ws_url)},
                      ensure_ascii=False)


def _frame_element(iframe, selector, port=None, index=0, ws=None):
    """iframe 内元素 → 主页面视口 CSS 矩形（v0.2.7）。iframe=选择器字符串
    （单层）或 JSON 数组（同源嵌套）；同源走 JS 递归，同进程跨域走
    createIsolatedWorld，跨站 OOPIF 如实报 oopif_unsupported。"""
    ws_url = _resolve_ws(port, index, ws)
    rec = dom.frame_element_rect(ws_url, iframe, selector)
    rec["ok"] = True
    return json.dumps(rec, ensure_ascii=False)


_tool_named("ashot_shot", _shot)
_tool_named("ashot_screens", _screens)
_tool_named("ashot_annotate", _annotate)
_tool_named("ashot_crop", _crop)
_tool_named("ashot_resize", _resize)
_tool_named("ashot_fonts", _fonts)
_tool_named("ashot_show", _show)
_tool_named("ashot_hash", _hash)
_tool_named("ashot_diff", _diff)
_tool_named("ashot_element", _element)
_tool_named("ashot_frames", _frames)
_tool_named("ashot_frame_element", _frame_element)
_tool_named("ashot_cdp_tabs", _cdp_tabs)
_tool_named("ashot_cdp_shot", _cdp_shot)
_tool_named("ashot_cdp_view", _cdp_view)
_tool_named("ashot_cdp_eval", _cdp_eval)
_tool_named("ashot_cdp_key", _cdp_key)
_tool_named("ashot_cdp_wheel", _cdp_wheel)
_tool_named("ashot_cdp_click", _cdp_click)
_tool_named("ashot_cdp_drag", _cdp_drag)
_tool_named("ashot_cdp_dblclick", _cdp_dblclick)
_tool_named("ashot_cdp_type", _cdp_type)

_stop = False


def _stamp(out):
    """收据盖章（单一出口，v0.2.6）：ver=进程内版本（Q18——文件版本号
    对了但进程还是旧的，这一行就能识破）；target=本次 cdp 目标身份
    （Q04——单实例也不许静默，收据里必须有"是谁的浏览器"）。
    非 JSON 文本原样返回。"""
    def patch(text):
        try:
            rec = json.loads(text)
        except (ValueError, TypeError):
            return text
        if not isinstance(rec, dict):
            return text
        rec.setdefault("ver", __version__)
        if _LAST_TARGET and "target" not in rec:
            rec["target"] = dict(_LAST_TARGET)
        return json.dumps(rec, ensure_ascii=False)

    if isinstance(out, list):
        for blk in out:
            if isinstance(blk, dict) and blk.get("type") == "text":
                blk["text"] = patch(blk.get("text") or "")
                break
        return out
    return patch(out)


def _serve():
    try:
        # 宿主可能以 GBK locale 裸拉起：异常文本含非 GBK 字符时 print
        # 抛 UnicodeEncodeError 直接杀死服务——显式锁 utf-8
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 —— 老版本无 reconfigure 不致命
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": "坏帧"}}), flush=True)
            continue
        if not isinstance(req, dict):
            # 合法 JSON 但非对象（数组/数字/字符串帧）：req.get 会抛
            # AttributeError 杀死服务进程（v0.1.5 P2 实锤）——回 -32600
            # 继续服务
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32600, "message": "非对象帧"}}), flush=True)
            continue
        method = req.get("method", "")
        rid = req.get("id")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ashot", "version": __version__}}}
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {}}
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "tools": [{"name": t["name"], "description": t["description"],
                           "inputSchema": t["inputSchema"]}
                          for t in TOOLS.values()]}}
        elif method == "tools/call":
            name = (req.get("params") or {}).get("name")
            entry = TOOLS.get(name)
            if entry is None:
                resp = {"jsonrpc": "2.0", "id": rid, "result": {
                    "isError": True,
                    "content": [{"type": "text", "text":
                                 "未知工具 %s（有：%s）" % (name, ", ".join(TOOLS))}]}}
            else:
                args = (req.get("params") or {}).get("arguments") or {}
                _LAST_TARGET.clear()   # 每次调用清空：不把上个目标带进本次收据
                try:
                    out = entry["_fn"](**args)
                    out = _stamp(out)
                    # v0.1.11：handler 返回 list = 预成形多内容块
                    # （文本收据+ImageContent）；str = 旧单文本（兼容）
                    content = (out if isinstance(out, list)
                               else [{"type": "text", "text": out}])
                    resp = {"jsonrpc": "2.0", "id": rid, "result": {
                        "content": content}}
                except Exception as e:  # noqa: BLE001 —— 业务失败走 isError
                    # 错误收据同样盖章（v0.2.6 审计：只盖成功路径等于在
                    # 最需要识破旧进程的时候没有 ver）
                    err = {"ok": False, "error": "%s: %s"
                           % (type(e).__name__, str(e)[:200])}
                    resp = {"jsonrpc": "2.0", "id": rid, "result": {
                        "isError": True, "content": [{"type": "text", "text":
                        _stamp(json.dumps(err, ensure_ascii=False))}]}}
        elif rid is not None:
            resp = {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32601, "message": "未知方法 %s" % method}}
        else:
            continue
        print(json.dumps(resp, ensure_ascii=False), flush=True)


def main():
    _serve()


if __name__ == "__main__":
    main()
