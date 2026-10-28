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

from ashot import __version__, annotate, annotate_gdi, capture, cdp, fonts, output, show  # noqa: E402

TOOLS = {}


def _tool(fn):
    # 简易 schema：从默认值推 required/optional；统一 string，工具内自转型
    code = fn.__code__
    names = code.co_varnames[:code.co_argcount]
    defaults = fn.__defaults__ or ()
    req = list(names[:len(names) - len(defaults)])
    props = {n: {"type": "string"} for n in names}
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


def _shot(mode="full", screen=None, out=None, clip=False, keep=False,
          area=None, retention_days=30, preview=False):
    """桌面截图：mode=full(全虚拟桌面)/screen(单屏,screen=序号)/win(前台窗口)
    /area(区域,area=[l,t,w,h])。返回 PNG 绝对路径；clip=true 只进剪贴板
    不落盘（**clip 与 preview 同传时 clip 优先，preview 被忽略**）。
    每次运行顺手清理超 retention_days 的旧图（keep=true 跳过）。
    preview=true（v0.1.11 实验特性）：收据升级多内容块，附 1200px JPEG
    缩图 ImageContent（audience:user；≤500KB 梯次降档；宿主渲染行为待
    实测，设计文档 §7.10）。"""
    if isinstance(area, str):
        area = json.loads(area) if area else None
    r = capture.shot(mode=mode or "full", screen=screen, area=area)
    all_black = None
    if r["kind"] == "raw":
        png = output.bgra_to_png(r["w"], r["h"], r["bgra"])
        all_black = capture.is_all_black(r["bgra"], r["w"], r["h"])
    else:
        png = r["png"]   # PS 兜底路径是 PNG 字节，黑帧检测不拆解（如实 None）
    if clip in (True, "true", "True", "1"):
        if not output.clip_png(png):
            raise RuntimeError("剪贴板写入失败")
        return json.dumps({"ok": True, "clipboard": True}, ensure_ascii=False)
    path = output.save(png, out=out)
    n, mb = output.gc(retention_days=int(retention_days or 30), keep=keep in (True, "true", "True", "1"))
    receipt = {"ok": True, "path": path, "all_black": all_black,
               "gc": {"removed": n, "freed_mb": round(mb, 1)}}
    if preview in (True, "true", "True", "1"):
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


def _annotate(image, ops, out=None, preview=False):
    """对既有 PNG 标注：ops=JSON 数组，kind ∈ rect/ellipse/arrow/line/
    text(中文可标注，GDI+ 系统字体；v0.1.9 起可选 font=字体族名/bold=
    粗体开关，缺省微软雅黑+粗体；未安装字体名静默回退默认；font/bold
    仅矢量路生效，像素降级路不认)/mosaic/blur/step(自动递增编号)/
    number(显式编号 value)/spotlight(聚光灯 dim)/smarterase(智能擦除)。
    矢量抗锯齿渲染（GDI+），失败自动降级纯像素画布。收据 backend=形状
    渲染后端（gdi+=矢量成功/pixel=降级或纯像素，混合 ops 时 gdi+ 仍
    成立）；pixel_ops=像素操作数量。像素 ops 恒在形状之后叠加（与 ops
    数组顺序无关）。preview=true（v0.1.11 实验特性）：收据升级多内容
    块，附 1200px JPEG 缩图 ImageContent（audience:user；≤500KB 梯次
    降档；宿主渲染行为待实测，设计文档 §7.10）。返回标注后 PNG 绝对
    路径；out 缺省写 <原名>_annotated.png——绝不覆盖原图（v0.1.5 P1
    根修，与 CLI 对齐）。"""
    with open(str(image), "rb") as fh:
        png = fh.read()
    ops_list = json.loads(ops) if isinstance(ops, str) else ops
    out_bytes, backend, pixel_n = annotate_gdi.annotate_png_vector(
        png, ops_list or [])
    stem = str(image)
    default_out = (stem.rsplit(".", 1)[0] + "_annotated.png"
                   if "." in os.path.basename(stem)
                   else stem + "_annotated.png")
    path = output.save(out_bytes, out=out or default_out)
    receipt = {"ok": True, "path": path, "backend": backend,
               "pixel_ops": pixel_n}
    if preview in (True, "true", "True", "1"):
        try:
            jpeg, info = output.preview_jpeg(out_bytes)
            receipt["preview"] = info
            return _content_with_image(json.dumps(receipt,
                                                  ensure_ascii=False), jpeg)
        except Exception as e:  # noqa: BLE001 —— 预览失败不吞主收据（审计 P2-1）
            receipt["preview"] = {"error": "%s: %s"
                                  % (type(e).__name__, str(e)[:200])}
    return json.dumps(receipt, ensure_ascii=False)


def _tool_named(name, fn):
    _tool(fn)
    entry = TOOLS.pop(fn.__name__)
    entry["name"] = name
    entry["_fn"] = fn
    TOOLS[name] = entry


def _fonts(filter=None):
    """列出系统已装字体族名（v0.1.10）。数据源与渲染器同源
    （.NET InstalledFontCollection）——查出的名字保证 text op 的 font
    字段可解析（未装名会静默回退默认字体，先查后用）。filter=不区分
    大小写子串过滤。收据 {ok, count, families:[...]}。本工具需宿主
    重连后才会出现在工具表。"""
    names = fonts.list_families(filter)
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


def _cdp_shot(port=None, index=0, fullpage=True, out=None):
    """CDP 浏览器标签页截图（v0.2.0）：Page.captureScreenshot，
    无头/有头通吃、与 AI 宿主无关（设计文档 v0.2.0 §4.2）。port 缺省
    =discover；index=第几个 page 标签；fullpage=captureBeyondViewport
    （Chrome 90+，视口外也截）。Chrome 136+ 默认 profile 拒远程调试
    （default_profile_denied）——用非默认 --user-data-dir 启动。返回
    截图 PNG 路径；本工具需宿主重连后才会出现在工具表。收据含 dpr 与
    **to_css**：截图像素 × to_css = 点击用的 CSS 坐标。"""
    ws = _resolve_cdp(port, index)
    png, info = cdp.shot(None, ws=ws, fullpage=fullpage not in (
        False, "false", "False", "0"))
    path = output.save(png, out=out)
    rec = {"ok": True, "path": path}
    for k in ("w", "h", "vw", "vh", "dpr", "to_css", "hint", "fullpage"):
        if k in info:
            rec[k] = info[k]
    return json.dumps(rec, ensure_ascii=False)


def _cdp_view(port=None, index=0, ws=None, timeout=15):
    """CDP 标签页视口信息（v0.2.5）：vw/vh = CSS 像素视口尺寸，
    dpr = devicePixelRatio，content_w/h = 整页内容尺寸。
    截图出图是物理像素（= CSS × dpr），直接拿截图坐标去点击必然落空。"""
    ws_url = ws or _resolve_cdp(port, index)
    lay, dpr = cdp.layout(ws_url, timeout=int(timeout or 15))
    rec = {"ok": True, "vw": lay["vw"], "vh": lay["vh"],
           "content_w": lay["content_w"], "content_h": lay["content_h"],
           "dpr": dpr}
    if lay["vw"] and lay["vh"] and dpr:
        rec["hint"] = ("截图按 dpr=%s 放大（物理=%sx%s），点击请用 CSS 坐标"
                       % (dpr, int(lay["vw"] * dpr), int(lay["vh"] * dpr)))
    return json.dumps(rec, ensure_ascii=False)


def _cdp_eval(js, port=None, index=0, ws=None, await_promise=False,
              timeout=30):
    """在 CDP 标签页里跑一段 JS 并取值（v0.2.5）。js 可写函数体（内部
    return）或表达式。用途：算坐标、读页面状态确认操作生效、拿 dpr。
    **只发 Runtime.evaluate，绝不发 Runtime.enable**（字节系检测点，
    一发即杀实例）。收据 {ok, value, exception}——异常如实带出不静默。"""
    ws_url = ws or _resolve_cdp(port, index)
    res = cdp.evaluate(ws_url, js, timeout=int(timeout or 30),
                       await_promise=await_promise in (
                           True, "true", "True", "1"))
    exc = res.get("exceptionDetails")
    rec = {"ok": exc is None}
    if exc:
        rec["exception"] = ((exc.get("exception") or {}).get("description")
                            or exc.get("text") or str(exc)[:200])
    else:
        res_obj = res.get("result") or {}
        rec["value"] = res_obj.get("value")
        if res_obj.get("type") == "undefined":
            rec["note"] = "undefined（多半传了表达式却没写 return）"
    return json.dumps(rec, ensure_ascii=False)


def _describe_ports(ports):
    """多端口时把每个实例的首个页签列出来，让人一眼认出是谁的浏览器
    （v0.2.5：discover 直接取 [0] 会把操作打到别人的实例上——实测
    曾把 ALrec 的 9225 当成目标）。列不出来就只给端口，不编造。"""
    lines = []
    for p in ports:
        try:
            ts = cdp.tabs(int(p))
            head = ts[0] if ts else None
            if head:
                lines.append("  --port %s  %s | %s"
                             % (p, (head.get("title") or "")[:40],
                                (head.get("url") or "")[:60]))
                continue
        except Exception:  # noqa: BLE001 —— 标注失败不影响报错本身
            pass
        lines.append("  --port %s  （无法读取页签）" % p)
    return lines


def _resolve_cdp(port, index=0, allow_multi=False):
    """cdp 输入工具公共解析：port 缺省 discover -> page ws。

    **安全边界（v0.2.5）**：discover 命中多个调试端口时，输入类动作
    **必须显式指定 --port**——静默取第一个会把鼠标事件打到完全不相干的
    浏览器实例上（可能带对方的登录态、可能正在被对方手动使用）。
    只有只读的 cdp-tabs 允许 allow_multi（它本就能一次列多实例）。"""
    if port in (None, "", 0):
        disc = cdp.discover()
        if not disc["ports"]:
            raise RuntimeError(disc["hint"])
        if len(disc["ports"]) > 1 and not allow_multi:
            raise RuntimeError(
                "发现 %d 个调试浏览器实例，不安全猜：请用 --port 指定目标\n%s"
                % (len(disc["ports"]), "\n".join(_describe_ports(
                    disc["ports"]))))
        port = disc["ports"][0]
    return cdp.ws_for(int(port), index=int(index or 0))


def _cdp_key(key, text=None, modifiers=None, port=None, index=0, ws=None):
    """CDP 按键/组合键/文本注入（v0.2.0 §4.2.2）：key=键名（a/enter/
    tab/arrowup/s…）；modifiers=组合键 "ctrl+shift"（位掩码
    Alt1/Ctrl2/Meta4/Shift8）；text=覆盖产生的文本（如中文）。可见
    字符 rawKeyDown+char 双发，控制键 keyDown+keyUp。返回
    {ok, dispatched}。需宿主重连出现。"""
    ws_url = ws or _resolve_cdp(port, index)
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
    ws_url = ws or _resolve_cdp(port, index)
    ev = {"type": "mouseWheel", "x": int(x), "y": int(y),
          "deltaX": int(dx), "deltaY": int(dy), "modifiers": 0}
    n, _ = cdp.dispatch(ws_url, [ev])
    return json.dumps({"ok": True, "dispatched": n}, ensure_ascii=False)


def _cdp_click(x, y, button="left", human=True, seed=None, port=None,
               index=0, ws=None, timing=True, verify=""):
    """CDP 鼠标单击（v0.2.0/0.2.4）：x/y=CSS 像素；button=left/right/
    middle；human=True（缺省）先沿人类化贝塞尔轨迹移动到位（带微抖动、
    有节奏地靠近），timing=false 或 --teleport 可退回瞬移（批处理时省掉
    每次约 200ms 的靠近耗时）。
    verify=一段 JS（可选）：点完立刻求值，结果进收据 verify 字段——
    **dispatched 只说明事件发出去了，不说明生效**（v0.2.5 诚实化）。
    返回 {ok, dispatched}。需宿主重连出现。"""
    ws_url = ws or _resolve_cdp(port, index)
    seq = cdp.click_events(int(x), int(y), button=button,
                           human=human not in (False, "false", "False",
                                               "0"),
                           seed=int(seed) if seed not in (None, "") else None)
    t0 = time.time()
    n, _ = cdp.dispatch(ws_url, seq,
                        realtime=timing not in (False, "false", "False", "0"))
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
    ws_url = ws or _resolve_cdp(port, index)
    seq = cdp.drag_events(
        x1, y1, x2, y2,
            steps=int(steps) if steps not in (None, "", 0) else 0,
            button=button,
            human=human not in (False, "false", "False", "0"),
            seed=int(seed) if seed not in (None, "") else None,
        constrained=constrained not in (False, "false", "False", "0"),
        max_perp=float(max_perp or 2.5),
        total_ms=(None if total_ms in (None, "") else float(total_ms)),
        pace=pace or "normal")
    stats = {}
    t0 = time.time()
    n, _ = cdp.dispatch(ws_url, seq,
                        realtime=timing not in (False, "false", "False", "0"),
                        stats=stats)
    rec = {"ok": True, "dispatched": n,
           "seconds": round(time.time() - t0, 2),
           "pace": str(pace or "normal"),
           "timing": timing not in (False, "false", "False", "0"),
           "constrained": constrained not in (False, "false", "False", "0"),
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
                  port=None, index=0, ws=None):
    """CDP 双击/多击（v0.2.3/0.2.4）：clickCount 递增序列，浏览器据此
    合成 dblclick 事件；human=True（缺省）先人类化轨迹到位。x/y=CSS
    像素。返回 {ok, dispatched}。需宿主重连出现。"""
    ws_url = ws or _resolve_cdp(port, index)
    seq = cdp.dblclick_events(x, y, button=button, count=int(count or 2),
                              human=human not in (False, "false", "False",
                                                  "0"),
                              seed=int(seed) if seed not in (None,
                                                             "") else None)
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
    ws_url = ws or _resolve_cdp(port, index)
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


_tool_named("ashot_shot", _shot)
_tool_named("ashot_screens", _screens)
_tool_named("ashot_annotate", _annotate)
_tool_named("ashot_fonts", _fonts)
_tool_named("ashot_show", _show)
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
                try:
                    out = entry["_fn"](**args)
                    # v0.1.11：handler 返回 list = 预成形多内容块
                    # （文本收据+ImageContent）；str = 旧单文本（兼容）
                    content = (out if isinstance(out, list)
                               else [{"type": "text", "text": out}])
                    resp = {"jsonrpc": "2.0", "id": rid, "result": {
                        "content": content}}
                except Exception as e:  # noqa: BLE001 —— 业务失败走 isError
                    resp = {"jsonrpc": "2.0", "id": rid, "result": {
                        "isError": True, "content": [{"type": "text", "text":
                        json.dumps({"ok": False, "error": "%s: %s"
                                    % (type(e).__name__, str(e)[:200])},
                                   ensure_ascii=False)}]}}
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
