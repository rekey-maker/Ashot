# -*- coding: utf-8 -*-
"""Ashot.cli —— 命令行入口（shot / annotate / screens / fonts / show /
cdp-tabs / cdp-shot）。"""
import argparse
import json
import os
import sys

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
    """cdp-* 输入命令公共解析：--port/--ws -> ws url（discover 兜底）。"""
    if getattr(a, "ws", None):
        return a.ws
    port = getattr(a, "port", None)
    if port is None:
        disc = cdp.discover()
        if not disc["ports"]:
            print("✗ %s" % disc["hint"], file=sys.stderr)
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
        seq = [
            {"type": "mouseMoved", "x": a.x, "y": a.y, "modifiers": 0},
            {"type": "mousePressed", "x": a.x, "y": a.y,
             "button": a.button, "buttons": 1, "clickCount": 1,
             "modifiers": 0},
            {"type": "mouseReleased", "x": a.x, "y": a.y,
             "button": a.button, "buttons": 0, "clickCount": 1,
             "modifiers": 0},
        ]
        n, _ = cdp.dispatch(ws, seq)
        print("dispatched: %d" % n)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_drag(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        seq = cdp.drag_events(a.x1, a.y1, a.x2, a.y2,
                              steps=a.steps, button=a.button)
        n, _ = cdp.dispatch(ws, seq)
        print("dispatched: %d" % n)
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
    _add_common(cc)
    cc.set_defaults(func=_cmd_cdp_click)

    cd = sub.add_parser("cdp-drag", help="CDP 鼠标拖拽（按下→插值移动→释放，v0.2.0）")
    cd.add_argument("x1", type=int, help="起点 x")
    cd.add_argument("y1", type=int, help="起点 y")
    cd.add_argument("x2", type=int, help="终点 x")
    cd.add_argument("y2", type=int, help="终点 y")
    cd.add_argument("--steps", type=int, default=8, help="插值步数")
    cd.add_argument("--button", default="left",
                    choices=["left", "right", "middle"], help="键")
    _add_common(cd)
    cd.set_defaults(func=_cmd_cdp_drag)

    a = ap.parse_args(argv)
    return a.func(a)


def os_startfile(path):
    os_startfile_impl(path)


def os_startfile_impl(path):
    import os
    os.startfile(path)


if __name__ == "__main__":
    sys.exit(main())
