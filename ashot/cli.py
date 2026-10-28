# -*- coding: utf-8 -*-
"""Ashot.cli —— 命令行入口（shot / annotate / screens / fonts / show /
cdp-tabs / cdp-shot）。"""
import argparse
import json
import os
import sys
import time

from . import __version__, annotate, annotate_gdi, capture, cdp, fonts, output, show


def _cmd_shot(a):
    try:
        r = capture.shot(mode=a.mode, screen=a.screen,
                         area=a.area and tuple(a.area))
    except Exception as e:  # noqa: BLE001 —— 零静默纪律
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    if r["kind"] == "raw":
        png = output.bgra_to_png(r["w"], r["h"], r["bgra"])
    else:
        png = r["png"]
    if a.clip:
        if not output.clip_png(png):
            print("✗ 剪贴板写入失败", file=sys.stderr)
            return 1
        print("已进剪贴板（未落盘）")
        return 0
    path = output.save(png, out=a.out)
    if a.open:
        os_startfile(path)
    n, mb = output.gc(retention_days=a.retention_days, keep=a.keep)
    if n:
        print("（retention 清理：%d 张旧图，释放 %.1f MB）" % (n, mb))
    print(path)
    return 0


def _cmd_annotate(a):
    try:
        with open(a.image, "rb") as fh:
            png = fh.read()
        if a.ops_file is None:
            ops = json.loads(a.ops)
        else:
            with open(a.ops_file, encoding="utf-8") as fh:
                ops = json.load(fh)
        out, backend, pixel_n = annotate_gdi.annotate_png_vector(png, ops)
        path = output.save(out, out=a.out or
                           a.image.rsplit(".", 1)[0] + "_annotated.png")
        print(path)
        print("backend: %s" % backend)
        print("pixel_ops: %d" % pixel_n)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_fonts(a):
    try:
        names = fonts.list_families(a.filter)
        for n in names:
            print(n)
        print("total: %d" % len(names), file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_show(a):
    try:
        res = show.build_html(a.image, a.title, a.out_dir,
                              caption=a.caption, width=a.width)
        print(res["html"])
        print("preview: width=%d quality=%d bytes=%d fit=%s"
              % (res["preview"]["width"], res["preview"]["quality"],
                 res["preview"]["bytes"], res["preview"]["fit"]),
              file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_tabs(a):
    try:
        port = a.port
        if port is None:
            disc = cdp.discover()
            if not disc["ports"]:
                print("✗ %s" % disc["hint"], file=sys.stderr)
                return 1
            port = disc["ports"][0]
            print("discovered port: %d" % port, file=sys.stderr)
        for t in cdp.tabs(port):
            print("%s\t%s\t%s" % (t["id"][:8], t["title"], t["url"]))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_shot(a):
    try:
        port = a.port
        if port is None:
            disc = cdp.discover()
            if not disc["ports"]:
                print("✗ %s" % disc["hint"], file=sys.stderr)
                return 1
            port = disc["ports"][0]
            print("discovered port: %d" % port, file=sys.stderr)
        png, info = cdp.shot(port, index=a.index, fullpage=not a.viewport)
        path = output.save(png, out=a.out)
        print(path)
        print("fullpage: %s" % info["fullpage"], file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _resolve_cdp_ws(a):
    """cdp-* 输入命令公共解析：--port/--ws -> ws url（discover 兜底）。

    **安全边界（v0.2.5）**：discover 命中多个调试端口时拒绝猜——静默
    取第一个会把鼠标事件打到完全不相干的浏览器实例上（实测曾把 ALrec
    的 9225 当目标）。此时列出各实例首个页签让人挑，显式带 --port 重跑。
    """
    if getattr(a, "ws", None):
        return a.ws
    port = getattr(a, "port", None)
    if port is None:
        disc = cdp.discover()
        if not disc["ports"]:
            print("✗ %s" % disc["hint"], file=sys.stderr)
            return None
        if len(disc["ports"]) > 1:
            print("✗ 发现 %d 个调试浏览器实例，不安全猜——请用 "
                  "--port 指定目标：" % len(disc["ports"]), file=sys.stderr)
            for p in disc["ports"]:
                try:
                    ts = cdp.tabs(int(p))
                    head = ts[0] if ts else None
                    if head:
                        print("  --port %s  %s | %s"
                              % (p, (head.get("title") or "")[:40],
                                 (head.get("url") or "")[:60]),
                              file=sys.stderr)
                        continue
                except Exception:  # noqa: BLE001 —— 标注失败不影响报错本身
                    pass
                print("  --port %s  （无法读取页签）" % p, file=sys.stderr)
            return None
        port = disc["ports"][0]
        print("discovered port: %d" % port, file=sys.stderr)
    return cdp.ws_for(int(port), index=int(getattr(a, "index", 0) or 0))


def _cmd_cdp_key(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        mods = a.modifiers if a.modifiers is not None and a.modifiers != "" \
            else 0
        if a.text:
            seq = cdp.key_events(a.key or "a", mods, text=a.text)
        else:
            seq = cdp.key_events(a.key, mods)
        n, unresolved = cdp.dispatch(ws, seq)
        print("dispatched: %d" % n)
        if unresolved:
            print("⚠ 未解析键名（无 VK 码透传，部分页面可能收不到）：%s"
                  % ", ".join(unresolved), file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_wheel(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        ev = {"type": "mouseWheel", "x": a.x, "y": a.y,
              "deltaX": a.dx, "deltaY": a.dy, "modifiers": 0}
        n, _ = cdp.dispatch(ws, [ev])
        print("dispatched: %d" % n)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_click(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        seq = cdp.click_events(a.x, a.y, button=a.button,
                               human=not a.teleport, seed=a.seed)
        t0 = time.time()
        n, _ = cdp.dispatch(ws, seq,
                            realtime=not getattr(a, "no_timing", False))
        print("dispatched: %d" % n)
        print("seconds: %.2f" % (time.time() - t0))
        if getattr(a, "verify", ""):
            try:
                r = cdp.evaluate(ws, a.verify)
                exc = r.get("exceptionDetails")
                print("verify: %s" % json.dumps(
                    {"exception": str(exc)[:200]} if exc
                    else (r.get("result") or {}).get("value"),
                    ensure_ascii=False))
            except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
                print("⚠ verify 失败：%s: %s" % (type(e).__name__, e),
                      file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_drag(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        seq = cdp.drag_events(
            a.x1, a.y1, a.x2, a.y2,
            steps=a.steps, button=a.button, human=not a.teleport,
            seed=a.seed, pace=getattr(a, "pace", "normal") or "normal",
            total_ms=(None if getattr(a, "total_ms", None) in (None, "")
                      else float(a.total_ms)),
            constrained=not getattr(a, "free", False),
            max_perp=float(getattr(a, "max_perp", 2.5) or 2.5))
        stats = {}
        t0 = time.time()
        n, _ = cdp.dispatch(ws, seq,
                            realtime=not getattr(a, "no_timing", False),
                            stats=stats)
        print("dispatched: %d" % n)
        print("seconds: %.2f" % (time.time() - t0))
        print("pace: %s  constrained: %s"
              % (getattr(a, "pace", "normal") or "normal",
                 not getattr(a, "free", False)))
        if stats.get("planned_ms"):
            print("planned_ms: %s" % stats["planned_ms"])
        if stats.get("clipped_ms"):
            print("clipped_ms: %s  ⚠ 等待被 3s 上限夹断"
                  % stats["clipped_ms"])
        if getattr(a, "verify", ""):
            try:
                r = cdp.evaluate(ws, a.verify)
                exc = r.get("exceptionDetails")
                print("verify: %s" % json.dumps(
                    {"exception": str(exc)[:200]} if exc
                    else (r.get("result") or {}).get("value"),
                    ensure_ascii=False))
            except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
                print("⚠ verify 失败：%s: %s" % (type(e).__name__, e),
                      file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_dblclick(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        seq = cdp.dblclick_events(a.x, a.y, button=a.button,
                                  count=a.count, human=not a.teleport,
                                  seed=a.seed)
        n, _ = cdp.dispatch(ws, seq)
        print("dispatched: %d" % n)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_type(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        # 聚焦前置：click 到目标坐标（若指定），再 insertText 整段输入
        if (a.x is None) != (a.y is None):
            print("✗ --x 与 --y 需成对给出（只给其一时无法聚焦）",
                  file=sys.stderr)
            return 1
        seq = ([{"type": "mouseMoved", "x": a.x, "y": a.y,
                 "modifiers": 0},
                {"type": "mousePressed", "x": a.x, "y": a.y,
                 "button": "left", "buttons": 1, "clickCount": 1,
                 "modifiers": 0},
                {"type": "mouseReleased", "x": a.x, "y": a.y,
                 "button": "left", "buttons": 0, "clickCount": 1,
                 "modifiers": 0}] if a.x is not None else []) + \
            cdp.insert_text_events(a.text)
        n, _ = cdp.dispatch(ws, seq)
        print("dispatched: %d" % n)
        if getattr(a, "verify", ""):
            try:
                r = cdp.evaluate(ws, a.verify)
                exc = r.get("exceptionDetails")
                print("verify: %s" % json.dumps(
                    {"exception": str(exc)[:200]} if exc
                    else (r.get("result") or {}).get("value"),
                    ensure_ascii=False))
            except Exception as e:  # noqa: BLE001 —— 校验失败不吞主收据
                print("⚠ verify 失败：%s: %s" % (type(e).__name__, e),
                      file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_view(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        lay, dpr = cdp.layout(ws, timeout=int(getattr(a, "timeout", 15) or 15))
        rec = {"ok": True, "vw": lay["vw"], "vh": lay["vh"],
               "content_w": lay["content_w"], "content_h": lay["content_h"],
               "dpr": dpr}
        if lay["vw"] and lay["vh"] and dpr:
            rec["hint"] = ("截图按 dpr=%s 放大（物理=%sx%s），点击请用 CSS 坐标"
                           % (dpr, int(lay["vw"] * dpr), int(lay["vh"] * dpr)))
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_eval(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        res = cdp.evaluate(ws, a.js, timeout=int(getattr(a, "timeout", 30) or 30),
                           await_promise=bool(getattr(a, "await", False)))
        exc = res.get("exceptionDetails")
        if exc:
            rec = {"ok": False,
                   "exception": ((exc.get("exception") or {}).get("description")
                                 or exc.get("text") or str(exc)[:200])}
        else:
            obj = res.get("result") or {}
            rec = {"ok": True, "value": obj.get("value")}
            if obj.get("type") == "undefined":
                rec["note"] = "undefined（多半传了表达式却没写 return）"
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_screens(_a):
    try:
        for sc in capture.list_screens():
            print("#%(index)d %(w)dx%(h)d offset=(%(left)d,%(top)d)%(primary)s"
                  % {**sc, "primary": " [主屏]" if sc["primary"] else ""})
        return 0
    except Exception as e:  # noqa: BLE001 —— 非 Win 平台如实报（审计 P2-2）
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def main(argv=None):
    # 管道重定向下 print 走 locale 编码（cp936），非 GBK 族名会截断输出
    # ——显式锁 utf-8（审计 P3-3，与 mcp._serve 同款）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 —— 老版本无 reconfigure 不致命
            pass
    ap = argparse.ArgumentParser(
        prog="ashot", description="Ashot —— agent 友好的桌面截图与标注工具")
    ap.add_argument("--version", action="version",
                    version="ashot " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shot", help="截图")
    s.add_argument("mode", nargs="?", default="full",
                   choices=["full", "screen", "win", "area"], help="截图模式")
    s.add_argument("--screen", type=int, default=None, help="screen 模式的屏序号")
    s.add_argument("--area", nargs=4, type=int, metavar=("L", "T", "W", "H"),
                   help="area 模式区域")
    s.add_argument("--out", default=None, help="输出路径（缺省 ~/Ashot/shots）")
    s.add_argument("--clip", action="store_true", help="只进剪贴板不落盘")
    s.add_argument("--open", action="store_true", help="截完用看图器打开")
    s.add_argument("--retention-days", type=int,
                   default=output.RETENTION_DAYS_DEFAULT,
                   help="shots 目录保留天数（运行顺手清理过期）")
    s.add_argument("--keep", action="store_true", help="本次跳过 retention 清理")
    s.set_defaults(func=_cmd_shot)

    s = sub.add_parser("annotate", help="对既有 PNG 标注（C 形态）")
    s.add_argument("image", help="PNG 路径")
    s.add_argument("ops", nargs="?", default=None, help='ops JSON（如 '
                   '"[{\\"kind\\":\\"rect\\",\\"x\\":10,\\"y\\":10,'
                   '\\"w\\":100,\\"h\\":50}]"）')
    s.add_argument("--ops-file", default=None, help="ops JSON 文件（复杂标注）")
    s.add_argument("--out", default=None, help="输出路径（缺省 *_annotated.png）")
    s.set_defaults(func=_cmd_annotate)

    s = sub.add_parser("screens", help="列出显示器")
    s.set_defaults(func=_cmd_screens)

    f = sub.add_parser("fonts", help="列出已装字体族（text 的 font 先查后用）")
    f.add_argument("filter", nargs="?", default=None,
                   help="不区分大小写子串过滤，如 kai / yahei")
    f.set_defaults(func=_cmd_fonts)

    w = sub.add_parser("show", help="图片→内嵌 HTML（用户可见展示，配 ::visualize）")
    w.add_argument("image", help="图片路径")
    w.add_argument("--title", required=True, help="HTML 标识（规范化为 a-z0-9-）")
    w.add_argument("--caption", default=None, help="图注（缺省=文件名）")
    w.add_argument("--out-dir", default=os.getcwd(),
                   help="输出目录（缺省=当前目录；::visualize 场景传会话可视化目录）")
    w.add_argument("--width", type=int, default=1200, help="缩图宽度（不放大）")
    w.set_defaults(func=_cmd_show)

    ct = sub.add_parser("cdp-tabs", help="列 CDP 浏览器的 page 标签页（v0.2.0）")
    ct.add_argument("--port", type=int, default=None,
                    help="调试端口（缺省=discover 自动发现）")
    ct.set_defaults(func=_cmd_cdp_tabs)

    cs = sub.add_parser("cdp-shot", help="CDP 浏览器标签页截图（无头/有头通吃，v0.2.0）")
    cs.add_argument("--port", type=int, default=None,
                    help="调试端口（缺省=discover 自动发现）")
    cs.add_argument("--index", type=int, default=0, help="第几个 page 标签")
    cs.add_argument("--viewport", action="store_true",
                    help="只抓视口（缺省 captureBeyondViewport 全页）")
    cs.add_argument("--out", default=None, help="输出路径（缺省 ~/Ashot/shots）")
    cs.set_defaults(func=_cmd_cdp_shot)

    def _add_common(p):
        p.add_argument("--port", type=int, default=None,
                       help="调试端口（缺省=discover）")
        p.add_argument("--index", type=int, default=0, help="第几个 page 标签")
        p.add_argument("--ws", default=None,
                       help="直接给 page 级 ws url（优先于 port/index）")

    ck = sub.add_parser("cdp-key", help="CDP 按键/组合键/文本注入（v0.2.0）")
    ck.add_argument("key", help="键名：a / enter / tab / arrowup / s（配 --modifiers）")
    ck.add_argument("--text", default=None, help="覆盖产生的文本（缺省=key 本身）")
    ck.add_argument("--modifiers", default=None,
                    help="组合键：alt/ctrl/meta/shift 可加和，如 ctrl+shift")
    _add_common(ck)
    ck.set_defaults(func=_cmd_cdp_key)

    cw = sub.add_parser("cdp-wheel", help="CDP 鼠标滚轮（v0.2.0）")
    cw.add_argument("--dx", type=int, default=0, help="横向滚动量")
    cw.add_argument("--dy", type=int, default=600, help="纵向滚动量（正=向下）")
    cw.add_argument("--x", type=int, default=100, help="事件坐标 x")
    cw.add_argument("--y", type=int, default=100, help="事件坐标 y")
    _add_common(cw)
    cw.set_defaults(func=_cmd_cdp_wheel)

    cc = sub.add_parser("cdp-click", help="CDP 鼠标单击（v0.2.0）")
    cc.add_argument("x", type=int, help="点击 x（CSS 像素）")
    cc.add_argument("y", type=int, help="点击 y")
    cc.add_argument("--button", default="left",
                    choices=["left", "right", "middle"], help="键")
    cc.add_argument("--teleport", action="store_true",
                    help="跳过人类化移动轨迹（瞬移到位，旧行为）")
    cc.add_argument("--no-timing", dest="no_timing", action="store_true",
                    help="关掉靠近轨迹的节奏等待（human 轨迹每次约多耗 "
                         "120~320ms；批处理时可关）")
    cc.add_argument("--seed", type=int, default=None,
                    help="轨迹随机种子（复现用；缺省每次随机）")
    cc.add_argument("--verify", default="",
                    help="点完后立刻求值的一段 JS，结果进收据"
                         "（如 \"return document.title\"）——dispatched "
                         "只代表事件发出，不代表生效")
    _add_common(cc)
    cc.set_defaults(func=_cmd_cdp_click)

    cd = sub.add_parser("cdp-drag", help="CDP 鼠标拖拽（人类化轨迹按下→移动→释放，v0.2.4）")
    cd.add_argument("x1", type=int, help="起点 x")
    cd.add_argument("y1", type=int, help="起点 y")
    cd.add_argument("x2", type=int, help="终点 x")
    cd.add_argument("y2", type=int, help="终点 y")
    cd.add_argument("--steps", type=int, default=0,
                    help="轨迹步数（缺省按距离自适应：受约束 18~48 / "
                         "自由 20~56）")
    cd.add_argument("--button", default="left",
                    choices=["left", "right", "middle"], help="键")
    cd.add_argument("--teleport", action="store_true",
                    help="退回直线插值（非人类化轨迹）")
    cd.add_argument("--seed", type=int, default=None, help="轨迹随机种子")
    cd.add_argument("--pace", default="normal",
                    choices=["fast", "normal", "captcha"],
                    help="节奏档（v0.2.5）：fast≈150~600ms / "
                         "normal≈320~1400ms / **captcha≈900~2600ms"
                         "——过滑块验证码用 captcha**")
    cd.add_argument("--total-ms", dest="total_ms", default=None,
                    help="显式指定拖拽总时长（毫秒；优先于 --pace；"
                         "给 0 = 全速不等）")
    cd.add_argument("--free", action="store_true",
                    help="自由拖拽（走贝塞尔弧线；缺省是受轨道约束的直线，"
                         "拖滑块/进度条不要加这个）")
    cd.add_argument("--max-perp", dest="max_perp", default=2.5,
                    help="受约束模式下允许的垂直抖动上限（CSS 像素）")
    cd.add_argument("--no-timing", dest="no_timing", action="store_true",
                    help="关掉节奏等待（全速派发）")
    cd.add_argument("--verify", default="",
                    help="拖完后立刻求值的一段 JS，结果进收据"
                         "（如 \"return document.title\"）")
    _add_common(cd)
    cd.set_defaults(func=_cmd_cdp_drag)

    cb = sub.add_parser("cdp-dblclick", help="CDP 鼠标双击/多击（人类化接近轨迹，v0.2.4）")
    cb.add_argument("x", type=int, help="双击 x（CSS 像素）")
    cb.add_argument("y", type=int, help="双击 y")
    cb.add_argument("--button", default="left",
                    choices=["left", "right", "middle"], help="键")
    cb.add_argument("--count", type=int, default=2,
                    help="点击数（2=双击，3=三连击）")
    cb.add_argument("--teleport", action="store_true",
                    help="跳过人类化移动轨迹")
    cb.add_argument("--seed", type=int, default=None, help="轨迹随机种子")
    _add_common(cb)
    cb.set_defaults(func=_cmd_cdp_dblclick)

    cv = sub.add_parser("cdp-view", help="CDP 标签页视口信息（vw/vh/dpr，v0.2.5）")
    cv.add_argument("--timeout", type=int, default=15, help="CDP 超时（秒）")
    _add_common(cv)
    cv.set_defaults(func=_cmd_cdp_view)

    ce = sub.add_parser("cdp-eval", help="CDP 标签页执行 JS 并取值（v0.2.5）")
    ce.add_argument("js", help="JS：函数体（内部 return）或表达式")
    ce.add_argument("--await", dest="await", action="store_true",
                    help="await 返回的 Promise 再取值")
    ce.add_argument("--timeout", type=int, default=30, help="CDP 超时（秒）")
    _add_common(ce)
    ce.set_defaults(func=_cmd_cdp_eval)

    ct2 = sub.add_parser("cdp-type", help="CDP 整段文本输入（填表，粘贴式不逐键，v0.2.3）")
    ct2.add_argument("text", help="整段文本（Input.insertText，不触发每键 keydown）")
    ct2.add_argument("--x", type=int, default=None,
                     help="可选：先点击该坐标聚焦输入框再输入")
    ct2.add_argument("--y", type=int, default=None, help="点击 y")
    ct2.add_argument("--verify", default="",
                     help='输完立刻求值的一段 JS，结果进收据（如 '
                     '"return document.activeElement.value"）')
    _add_common(ct2)
    ct2.set_defaults(func=_cmd_cdp_type)

    a = ap.parse_args(argv)
    return a.func(a)


def os_startfile(path):
    os_startfile_impl(path)


def os_startfile_impl(path):
    import os
    os.startfile(path)


if __name__ == "__main__":
    sys.exit(main())
