# -*- coding: utf-8 -*-
"""Ashot.cli —— 命令行入口（shot / annotate 两子命令）。"""
import argparse
import json
import sys

from . import __version__, annotate, annotate_gdi, capture, fonts, output


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


def _cmd_screens(_a):
    for sc in capture.list_screens():
        print("#%(index)d %(w)dx%(h)d offset=(%(left)d,%(top)d)%(primary)s"
              % {**sc, "primary": " [主屏]" if sc["primary"] else ""})
    return 0


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

    a = ap.parse_args(argv)
    return a.func(a)


def os_startfile(path):
    os_startfile_impl(path)


def os_startfile_impl(path):
    import os
    os.startfile(path)


if __name__ == "__main__":
    sys.exit(main())
