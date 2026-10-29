# -*- coding: utf-8 -*-
"""Ashot.cli —— 命令行入口（shot / annotate / crop / resize / compose /
screens / fonts / show / hash / diff / element / frames / cdp-*）。"""
import argparse
import json
import os
import sys
import time

from . import (__version__, annotate, annotate_gdi, capture, cdp, dom, fonts,
               imageio, output, show, transform, vision)


def _csv(s, n, name):
    """"a,b,c" -> [a,b,c]（n 个数字）。CLI 与 MCP 同一套解析规则。"""
    try:
        parts = [x.strip() for x in str(s).replace(" ", ",").split(",")
                 if x.strip()]
        if len(parts) != n:
            raise ValueError
        return [float(x) for x in parts]
    except (TypeError, ValueError):
        raise ValueError("%s 需要 %d 个数字（逗号分隔）：%r" % (name, n, s))


def _area4(vals, name="--area"):
    """屏幕区域 -> (l,t,w,h)。`--area 100 100 800 600` 与 `--area
    "100,100,800,600"` 都认（与 MCP 的 _parse_area 同款——两脸别记两套）。"""
    if not vals:
        return None
    parts = [p for v in vals
             for p in str(v).replace(" ", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise ValueError("%s 需要 4 个数字（空格或逗号分隔）：%r"
                         % (name, vals))
    return tuple(int(float(p)) for p in parts)


def _want_jpeg(args, out):
    """-> (fmt, quality)。`--jpg Q` 显式要求 JPEG；否则看输出扩展名。"""
    jpg = getattr(args, "jpg", 0) or 0
    ext = os.path.splitext(str(out or ""))[1].lower()
    if jpg:
        return "jpeg", int(jpg)
    if ext in (".jpg", ".jpeg"):
        return "jpeg", int(getattr(args, "quality", 85) or 85)
    return "png", int(getattr(args, "quality", 85) or 85)


def _print_transform_info(info, stream=sys.stderr):
    print("size: %dx%d (src %dx%d)" % (info["w"], info["h"],
                                       info["src"][0], info["src"][1]),
          file=stream)
    if info.get("crop"):
        print("crop: x,y,w,h=%s  px=%s"
              % (",".join(str(v) for v in info["crop"]),
                 ",".join(str(v) for v in info["crop_px"])), file=stream)
    if info.get("scale") not in (None, 1.0):
        print("scale: %s" % info["scale"], file=stream)
    print("format: %s (quality=%s)  bytes: %d  ms: %s"
          % (info["format"], info.get("quality"), info.get("bytes", 0),
             info.get("ms")), file=stream)
    for w in info.get("bounds_warn") or []:
        print("⚠ %s" % w, file=stream)


def _cmd_shot(a):
    try:
        r = capture.shot(mode=a.mode, screen=a.screen,
                         area=_area4(a.area))
    except Exception as e:  # noqa: BLE001 —— 零静默纪律
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    if r["kind"] == "raw":
        png = output.bgra_to_png(r["w"], r["h"], r["bgra"])
    else:
        png = r["png"]
    fmt, q = _want_jpeg(a, a.out)
    if a.clip:
        # 剪贴板始终要位图（clip_png 收 PNG），JPEG 只影响落盘
        if a.scale or a.max_side:
            png, info = transform.apply(png, scale=a.scale,
                                        max_side=a.max_side)
            _print_transform_info(info)
        if a.jpg:
            print("⚠ --clip 不落盘：--jpg 只影响落盘格式，剪贴板仍是位图",
                  file=sys.stderr)
        if not output.clip_png(png):
            print("✗ 剪贴板写入失败", file=sys.stderr)
            return 1
        print("已进剪贴板（未落盘）", file=sys.stderr)
        return 0
    if a.scale or a.max_side or fmt == "jpeg":
        png, info = transform.apply(png, scale=a.scale, max_side=a.max_side,
                                    fmt=fmt, quality=q)
        _print_transform_info(info)
    path = output.save(png, out=a.out,
                       ext=".jpg" if fmt == "jpeg" else ".png")
    if a.open:
        os_startfile(path)
    # v0.2.6：区域来源 / 降级原因都亮出来（Q09/Q17，stdout 只留路径）
    print("box_source: %s" % r.get("box_source"), file=sys.stderr)
    if r.get("gdi_error"):
        print("⚠ GDI 主路降级：%s" % r["gdi_error"], file=sys.stderr)
    n, mb = output.gc(retention_days=a.retention_days, keep=a.keep)
    if n:
        print("（retention 清理：%d 张旧图，释放 %.1f MB）" % (n, mb),
              file=sys.stderr)
    print(path)
    return 0


def _cmd_annotate(a):
    try:
        png = imageio.read_png(a.image)
        if a.ops_file is None:
            ops = json.loads(a.ops) if a.ops else []
        else:
            with open(a.ops_file, encoding="utf-8") as fh:
                ops = json.load(fh)
        if not ops and not a.template:
            raise ValueError("annotate 需要 ops（内联或 --ops-file）或 --template")
        if a.template:
            with open(a.template, encoding="utf-8") as fh:
                tpl = json.load(fh)
            if isinstance(tpl, dict):
                if "ops" not in tpl:
                    raise ValueError("--template 的对象形式必须含 ops 键：%r"
                                     % (a.template,))
                tpl = tpl["ops"]
            if not isinstance(tpl, list):
                raise ValueError("--template 需要 ops 数组（或 {\"ops\": […] }）")
            ops = list(tpl) + list(ops)
        if not ops:
            raise ValueError("annotate 合并后 ops 为空（模板/内联都没给标注）")
        if any(isinstance(o, dict) and (o.get("selector") or o.get("ref"))
               for o in ops):
            ws = _resolve_cdp_ws(a)
            if not ws:
                return 1      # _resolve_cdp_ws 已打印过具体原因，别重复误导
            ops = dom.apply_selectors(ws, ops, space=a.space)
        if a.dpr:
            ops = annotate.scale_ops(ops, a.dpr)
            print("dpr: x%g（只缩放坐标，字号/线宽不变）" % a.dpr,
                  file=sys.stderr)
        stats = {}
        out, backend, pixel_n = annotate_gdi.annotate_png_vector(
            png, ops, stats=stats)
        out_path = transform.out_path(a.out, a.image, "annotated",
                                      _want_jpeg(a, a.out)[0])
        fmt, q = _want_jpeg(a, a.out)
        max_side = getattr(a, "max_side", 0) or 0
        if fmt == "jpeg" or max_side:
            out, info = transform.apply(out, max_side=max_side, fmt=fmt,
                                        quality=q)
            _print_transform_info(info)
        path = output.save(out, out=out_path)
        print(path)
        print("backend: %s" % backend, file=sys.stderr)
        print("pixel_ops: %d" % pixel_n, file=sys.stderr)
        # v0.2.6：降级原因与超界告警都走 stderr（stdout 保持"路径"契约）
        if stats.get("degrade_reason"):
            print("⚠ 矢量路降级：%s" % stats["degrade_reason"], file=sys.stderr)
        for w in stats.get("bounds_warn") or []:
            print("⚠ %s" % w, file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_crop(a):
    """裁切（可顺带缩放/转 JPEG）。box 是 **x,y,w,h**，不是 x1,y1,x2,y2。"""
    try:
        with open(a.image, "rb") as fh:
            png = fh.read()
        fmt, q = _want_jpeg(a, a.out)
        out_path = transform.out_path(a.out, a.image, "cropped", fmt)
        data, info = transform.apply(
            png, crop=_csv(a.box, 4, "--box"), scale=a.scale,
            width=a.width, max_side=a.max_side, fmt=fmt, quality=q,
            dpr=a.dpr)
        path = output.save(data, out=out_path)
        print(path)
        _print_transform_info(info)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _check_size_args(a):
    """进批/单张之前先把非法尺寸挡掉（别按文件重复报错）。"""
    for name in ("scale", "width", "max_side"):
        v = getattr(a, name, 0) or 0
        if v and float(v) <= 0:
            raise ValueError("--%s 必须 > 0：%r" % (name.replace("_", "-"), v))


def _resize_dir(a):
    """目录批处理：只处理 .png/.jpg/.jpeg，输出到 --out-dir。"""
    src = os.path.abspath(a.dir)
    if not os.path.isdir(src):
        raise ValueError("--dir 不是目录：%r" % (a.dir,))
    dst = os.path.abspath(a.out_dir or (src.rstrip("\\/") + "_resized"))
    os.makedirs(dst, exist_ok=True)
    fmt = "jpeg" if a.jpg else "png"
    q = a.jpg or a.quality
    exts = (".png", ".jpg", ".jpeg")
    files = sorted(f for f in os.listdir(src)
                   if os.path.splitext(f)[1].lower() in exts)
    if not files:
        raise ValueError("目录里没有 PNG/JPEG：%r" % src)
    ok = fail = 0
    used = set()
    for name in files:
        ip = os.path.join(src, name)
        base = os.path.splitext(name)[0]
        ext = ".jpg" if fmt == "jpeg" else ".png"
        op = os.path.join(dst, base + ext)
        n = 1
        while op in used:   # 只处理同批撞名；重跑要覆盖旧产物（审查 P2-6）
            n += 1
            op = os.path.join(dst, "%s-%d%s" % (base, n, ext))
        used.add(op)
        try:
            with open(ip, "rb") as fh:
                data, _info = transform.apply(
                    fh.read(), scale=a.scale, width=a.width,
                    max_side=a.max_side, fmt=fmt, quality=q)
            output.save(data, out=op)
            print(op)
            ok += 1
        except Exception as e:  # noqa: BLE001 —— 单张失败不拖垮整批
            print("✗ %s: %s" % (name, e), file=sys.stderr)
            fail += 1
    print("batch: %d 成功 / %d 失败 -> %s" % (ok, fail, dst),
          file=sys.stderr)
    return 0 if fail == 0 else 1


def _cmd_info(a):
    try:
        rec = imageio.info(a.image)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_resize(a):
    """只改尺寸（可顺带转 JPEG）。scale/width/max_side 三选一。

    --dir 给目录时进入批处理（v0.5.0）：逐张 apply，输出到 --out-dir
    （缺省 <dir>_resized），每行一个路径；单张失败不中断其余，收尾汇总。
    """
    try:
        if not (a.scale or a.width or a.max_side):
            raise ValueError("resize 至少给 --scale / --width / --max-side 之一")
        _check_size_args(a)
        if a.dir:
            if a.out:
                raise ValueError("--dir 与 --out 不能同时使用（批处理请用 --out-dir）")
            return _resize_dir(a)
        if a.out_dir:
            raise ValueError("--out-dir 只能和 --dir 一起用")
        if not a.image:
            raise ValueError("resize 需要 image 或 --dir")
        png = imageio.read_png(a.image)
        fmt, q = _want_jpeg(a, a.out)
        out_path = transform.out_path(a.out, a.image, "resized", fmt)
        data, info = transform.apply(
            png, scale=a.scale, width=a.width, max_side=a.max_side,
            fmt=fmt, quality=q)
        path = output.save(data, out=out_path)
        print(path)
        _print_transform_info(info)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _compose_ops(a):
    """compose 的 CLI 标注参数 -> ops 数组（坐标=裁缩后的图，coord_space
    随收据回显）。--text 支持 "x,y:文字" 让每处文字独立——imgtool 里
    多个 --text 共用一条 --label 的坑不复制。"""
    ops = []
    for spec in a.rect or []:
        x, y, w, h = _csv(spec, 4, "--rect")
        ops.append({"kind": "rect", "x": x, "y": y, "w": w, "h": h,
                    "width": a.line_width, "color": a.color})
    for spec in a.arrow or []:
        x1, y1, x2, y2 = _csv(spec, 4, "--arrow")
        ops.append({"kind": "arrow", "x1": x1, "y1": y1, "x2": x2,
                    "y2": y2, "width": a.line_width, "color": a.color})
    for spec in a.text or []:
        s = str(spec)
        body = a.label or ""
        if ":" in s:
            pos, body = s.split(":", 1)
        else:
            pos = s
        x, y = _csv(pos, 2, "--text")
        ops.append({"kind": "text", "x": x, "y": y, "text": body,
                    "size": a.font_size, "color": a.color})
    return ops


def _cmd_compose(a):
    """一条命令出图：截屏/读图 -> 裁 -> 缩 -> 标注 -> 存盘（PNG/JPEG）。"""
    t0 = time.time()
    try:
        if a.src:
            png = imageio.read_png(a.src)
            shot_info = {"kind": "file", "src": a.src}
        elif a.area:
            r = capture.shot(mode="area", area=_area4(a.area))
            png = (output.bgra_to_png(r["w"], r["h"], r["bgra"])
                   if r["kind"] == "raw" else r["png"])
            shot_info = {"kind": "shot", "box_source": r.get("box_source")}
        else:
            raise ValueError("compose 需要 --src（已有图片）或 --area（屏幕区域）")
        fmt, q = _want_jpeg(a, a.out)
        out_path = transform.out_path(a.out, a.src or "compose", "shot", fmt)
        steps = []
        if a.box or a.scale or a.width or a.max_side:
            png, info = transform.apply(
                png, crop=_csv(a.box, 4, "--box") if a.box else None,
                scale=a.scale, width=a.width, max_side=a.max_side,
                dpr=a.dpr)
            steps.append({"stage": "transform", "size": [info["w"],
                                                         info["h"]],
                          "crop": info.get("crop"), "scale": info.get("scale"),
                          "bounds_warn": info.get("bounds_warn")})
        ops = _compose_ops(a)
        backend = None
        if ops:
            stats = {}
            png, backend, pixel_n = annotate_gdi.annotate_png_vector(
                png, ops, stats=stats)
            steps.append({"stage": "annotate", "ops": len(ops),
                          "backend": backend, "pixel_ops": pixel_n,
                          "bounds_warn": stats.get("bounds_warn")})
        if fmt == "jpeg":
            png, info = transform.apply(png, fmt="jpeg", quality=q)
        path = output.save(png, out=out_path)
        print(path)
        size = transform.png_size(png) if png[:8] == b"\x89PNG\r\n\x1a\n" \
            else output.image_size(png)
        print("size: %dx%d  format: %s  ms: %d"
              % (size[0], size[1], fmt, int((time.time() - t0) * 1000)),
              file=sys.stderr)
        print("coord_space: ops 坐标按裁缩后的图（%dx%d）"
              % size, file=sys.stderr)
        for s in steps:
            for w in s.get("bounds_warn") or []:
                print("⚠ %s" % w, file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_hash(a):
    try:
        png = imageio.read_png(a.image)
        rec = vision.digest(png)
        if a.algo:
            rec["value"] = rec.get(a.algo)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_diff(a):
    try:
        pa = imageio.read_png(a.a)
        pb = imageio.read_png(a.b)
        rec = vision.diff(pa, pb, threshold=a.threshold,
                          make_image=bool(a.out))
        img = rec.pop("image", None)
        if a.out and img:
            rec["out"] = output.save(img, out=a.out)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_element(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        rec = dom.element_rect(ws, a.selector, scroll=a.scroll)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_frame_element(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        frames_arg = a.iframe
        if frames_arg.strip().startswith("["):
            frames_arg = json.loads(frames_arg)
        rec = dom.frame_element_rect(ws, frames_arg, a.selector)
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_snapshot(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        rec = dom.snapshot(ws, max_nodes=int(a.max_nodes or 150))
        rec["ok"] = True
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_frames(a):
    try:
        ws = _resolve_cdp_ws(a)
        if not ws:
            return 1
        print(json.dumps({"ok": True, "frames": dom.frames(ws)},
                         ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_fonts(a):
    try:
        names = fonts.list_families(a.filter, refresh=bool(a.refresh))
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
        ports = None
        if a.port is None:
            disc = cdp.discover()
            if not disc["ports"]:
                print("✗ %s" % disc["hint"], file=sys.stderr)
                return 1
            for w in disc.get("warnings") or []:
                print("⚠ %s" % w, file=sys.stderr)
            ports = disc["ports"]
            if len(ports) > 1:
                # 只读命令：多实例一次列全（v0.2.5 分组语义；与 MCP 对齐）
                for p in ports:
                    print("== port %s ==" % p)   # 表头进 stdout（消费方可对号）
                    try:
                        for t in cdp.tabs(p):
                            print("%s\t%s\t%s"
                                  % (t["id"][:8], t["title"], t["url"]))
                    except Exception as e:  # noqa: BLE001
                        print("  （读取失败：%s）" % e, file=sys.stderr)
                return 0
            print("discovered port: %d" % ports[0], file=sys.stderr)
        port = a.port if a.port is not None else ports[0]
        for t in cdp.tabs(port):
            print("%s\t%s\t%s" % (t["id"][:8], t["title"], t["url"]))
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _cmd_cdp_shot(a):
    try:
        port, info = cdp.pick_port(a.port)
        for w in info.get("warnings") or []:
            print("⚠ %s" % w, file=sys.stderr)
        png, meta = cdp.shot(port, index=a.index,
                             fullpage=not a.viewport,
                             stitch=not getattr(a, "no_stitch", False))
        path = output.save(png, out=a.out)
        print(path)
        # v0.2.6 Q22：换算依据不能只给 MCP——CLI 同样输出坐标语义
        print("fullpage: %s" % meta["fullpage"], file=sys.stderr)
        for k in ("w", "h", "vw", "vh", "dpr", "to_css", "coord_space",
                  "scroll_y", "fullpage_truncated", "stitched", "shots",
                  "stitch_error", "fixed_hidden"):
            if k in meta:
                print("%s: %s" % (k, meta[k]), file=sys.stderr)
        if meta.get("hint"):
            print("hint: %s" % meta["hint"], file=sys.stderr)
        return 0
    except Exception as e:  # noqa: BLE001
        print("✗ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


def _resolve_cdp_ws(a):
    """cdp-* 输入命令公共解析：--port/--ws -> ws url（discover 兜底）。

    **安全边界（v0.2.5/0.2.6）**：discover 命中多个调试端口时拒绝猜——
    静默取第一个会把鼠标事件打到完全不相干的浏览器实例上（实测曾把
    ALrec 的 9225 当目标）。单实例也把目标身份（端口/进程/页签标题）
    打到 stderr，便于核对是不是自己的浏览器。"""
    if getattr(a, "ws", None):
        return a.ws
    try:
        port, info = cdp.pick_port(getattr(a, "port", None))
    except RuntimeError as e:
        print("✗ %s" % e, file=sys.stderr)
        return None
    for w in info.get("warnings") or []:
        print("⚠ %s" % w, file=sys.stderr)
    tgt = cdp.target_info(port, int(getattr(a, "index", 0) or 0))
    print("target: port=%s%s%s"
          % (port,
             (" process=%s" % info["process"]) if info.get("process") else "",
             (" | %s" % tgt.get("title")) if tgt.get("title") else ""),
          file=sys.stderr)
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
        start = ((getattr(a, "from_x", None), getattr(a, "from_y", None))
                 if getattr(a, "from_x", None) is not None
                 and getattr(a, "from_y", None) is not None else None)
        seq = cdp.click_events(a.x, a.y, button=a.button,
                               human=not a.teleport, seed=a.seed,
                               start=start)
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
        start = ((getattr(a, "from_x", None), getattr(a, "from_y", None))
                 if getattr(a, "from_x", None) is not None
                 and getattr(a, "from_y", None) is not None else None)
        seq = cdp.dblclick_events(a.x, a.y, button=a.button,
                                  count=a.count, human=not a.teleport,
                                  seed=a.seed, start=start)
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
        try:
            rec["scrollables"] = cdp.scrollables(ws)
        except Exception as e:  # noqa: BLE001 —— 失败亮牌，不静默
            rec["scrollables_error"] = str(e)[:200]
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
        prog="ashot", description="Ashot —— agent 友好的桌面截图与标注工具",
        # v0.2.6 Q22：关掉前缀缩写——`--ops '[{...}]'` 曾被子命令的
        # --ops-file 前缀匹配吞成"打开文件"，报 OSError 而不是用法错误
        allow_abbrev=False)
    ap.add_argument("--version", action="version",
                    version="ashot " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shot", help="截图")
    s.add_argument("mode", nargs="?", default="full",
                   choices=["full", "screen", "win", "area"], help="截图模式")
    s.add_argument("--screen", type=int, default=None, help="screen 模式的屏序号")
    s.add_argument("--area", nargs="+", metavar="N",
                   help="area 模式区域 L T W H（空格或逗号分隔，"
                        "如 --area 0 0 800 600 / --area 0,0,800,600）")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--scale", type=float, default=0.0,
                   help="截完按倍率缩放（允许放大；0.5=一半，1.5=放大）")
    g.add_argument("--max-side", dest="max_side", type=int, default=0,
                   help="截完限制最长边（**只缩不放**，如 1600）")
    s.add_argument("--jpg", type=int, default=0,
                   help="直接存 JPEG（给质量，如 85；体积比 PNG 小一个量级）")
    s.add_argument("--quality", type=int, default=85,
                   help="JPEG 质量（--out 以 .jpg 结尾且未给 --jpg 时用）")
    s.add_argument("--out", default=None, help="输出路径（缺省 ~/Ashot/shots）")
    s.add_argument("--clip", action="store_true", help="只进剪贴板不落盘")
    s.add_argument("--open", action="store_true", help="截完用看图器打开")
    s.add_argument("--retention-days", type=int,
                   default=output.RETENTION_DAYS_DEFAULT,
                   help="shots 目录保留天数（运行顺手清理过期）")
    s.add_argument("--keep", action="store_true", help="本次跳过 retention 清理")
    s.set_defaults(func=_cmd_shot)

    s = sub.add_parser("annotate", help="对既有 PNG/JPEG 标注（C 形态）")
    s.add_argument("image", help="PNG/JPEG 路径")
    s.add_argument("ops", nargs="?", default=None, help='ops JSON（如 '
                   '"[{\\"kind\\":\\"rect\\",\\"x\\":10,\\"y\\":10,'
                   '\\"w\\":100,\\"h\\":50}]"）')
    s.add_argument("--ops-file", default=None, help="ops JSON 文件（复杂标注）")
    s.add_argument("--out", default=None, help="输出路径（缺省 *_annotated.png）")
    s.add_argument("--jpg", type=int, default=0,
                   help="标注后转 JPEG（给质量，如 85；缺省仍存 PNG）")
    s.add_argument("--quality", type=int, default=85,
                   help="JPEG 质量（--out 以 .jpg 结尾且未给 --jpg 时用）")
    s.add_argument("--max-side", dest="max_side", type=int, default=0,
                   help="标注后限制最长边（0=不限）")
    s.add_argument("--dpr", type=float, default=0,
                   help="ops 坐标是 CSS 像素时填 devicePixelRatio（如 1.566），"
                        "只缩放坐标，不缩放字号/线宽（v0.5.0）")
    s.add_argument("--template", default=None,
                   help="标注模板 JSON（ops 数组或 {\"ops\": […] }），"
                        "与内联 ops 合并（v0.5.0）")
    s.add_argument("--port", type=int, default=None,
                   help="ops 用 selector 时的 CDP 端口（ref 仅 MCP 可用）")
    s.add_argument("--index", type=int, default=0, help="第几个 page 标签")
    s.add_argument("--ws", default=None, help="page 级 ws url（优先）")
    s.add_argument("--space", choices=["viewport", "document"],
                   default="viewport",
                   help="selector/ref 的坐标系：viewport（缺省）或 document"
                        "（整页截图，自动加 scroll）")
    s.set_defaults(func=_cmd_annotate)

    def _add_size_args(p):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--scale", type=float, default=0,
                       help="倍率（允许放大，如 1.2 / 0.5）")
        g.add_argument("--width", type=int, default=0,
                       help="目标宽（高度等比，允许放大）")
        g.add_argument("--max-side", dest="max_side", type=int, default=0,
                       help="最长边上限（**只缩不放**）")
        p.add_argument("--jpg", type=int, default=0,
                       help="输出 JPEG（给质量，如 85）")
        p.add_argument("--quality", type=int, default=85,
                       help="JPEG 质量（--out 以 .jpg 结尾且未给 --jpg 时用）")

    cp = sub.add_parser("crop", help="裁切既有图片（可顺带缩放/转 JPEG，v0.4.0）")
    cp.add_argument("image", help="源图 PNG/JPEG 路径")
    cp.add_argument("--box", required=True,
                    help="裁切区域 **x,y,w,h**（左上角+宽高；"
                         "**不是** x1,y1,x2,y2）")
    cp.add_argument("--dpr", type=float, default=0,
                    help="box 给的是 CSS 像素时填 devicePixelRatio"
                         "（如 1.566），内部乘完再裁")
    cp.add_argument("--out", default=None, help="输出路径（缺省 *_cropped.png）")
    _add_size_args(cp)
    cp.set_defaults(func=_cmd_crop)

    rs = sub.add_parser("resize", help="缩放既有图片（可转 JPEG，v0.4.0）")
    rs.add_argument("image", nargs="?", default=None, help="源图 PNG/JPEG 路径")
    rs.add_argument("--out", default=None, help="输出路径（缺省 *_resized.png）")
    rs.add_argument("--dir", default=None,
                    help="批处理：目录（只收 .png/.jpg/.jpeg，v0.5.0）")
    rs.add_argument("--out-dir", dest="out_dir", default=None,
                    help="批处理输出目录（缺省 <dir>_resized）")
    _add_size_args(rs)
    rs.set_defaults(func=_cmd_resize)

    co = sub.add_parser("compose",
                        help="一条命令出图：截屏/读图→裁→缩→标注→存盘（v0.4.0）")
    co.add_argument("--src", default="", help="已有图片（与 --area 二选一）")
    co.add_argument("--area", nargs="+", metavar="N",
                    help="屏幕区域 L T W H（空格或逗号分隔；与 --src 二选一）")
    co.add_argument("--box", default="", help="裁切 **x,y,w,h**")
    co.add_argument("--dpr", type=float, default=0,
                    help="--box 是 CSS 像素时填 dpr")
    co.add_argument("--rect", action="append", default=[],
                    help="标注框 x,y,w,h（可多次）")
    co.add_argument("--arrow", action="append", default=[],
                    help="箭头 x1,y1,x2,y2（可多次）")
    co.add_argument("--text", action="append", default=[],
                    help='文字 "x,y:内容"（可多次，各自内容；'
                         '不带冒号时用 --label）')
    co.add_argument("--label", default="",
                    help="--text 没写内容时的共用文字")
    co.add_argument("--color", default="#FF3B30", help="标注颜色 #RRGGBB")
    co.add_argument("--line-width", dest="line_width", type=int, default=6,
                    help="线宽")
    co.add_argument("--font-size", dest="font_size", type=int, default=32,
                    help="字号（像素）")
    co.add_argument("--out", default=None, help="输出路径（缺省派生名）")
    _add_size_args(co)
    co.set_defaults(func=_cmd_compose)

    s = sub.add_parser("screens", help="列出显示器")
    s.set_defaults(func=_cmd_screens)

    f = sub.add_parser("fonts", help="列出已装字体族（text 的 font 先查后用）")
    f.add_argument("filter", nargs="?", default=None,
                   help="不区分大小写子串过滤，如 kai / yahei")
    f.add_argument("--refresh", action="store_true",
                   help="强制重新枚举（常驻进程装了新字体时用，v0.2.6）")
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
    cs.add_argument("--no-stitch", dest="no_stitch", action="store_true",
                    help="超长页（>16384px）不滚动拼接，按单张上限如实报错")
    cs.add_argument("--out", default=None, help="输出路径（缺省 ~/Ashot/shots）")
    cs.set_defaults(func=_cmd_cdp_shot)

    def _add_common(p):
        p.add_argument("--port", type=int, default=None,
                       help="调试端口（缺省=discover）")
        p.add_argument("--index", type=int, default=0, help="第几个 page 标签")
        p.add_argument("--ws", default=None,
                       help="直接给 page 级 ws url（优先于 port/index）")

    inf = sub.add_parser("info", help="图片信息（PNG/JPEG 的尺寸/格式/体积，v0.5.0）")
    inf.add_argument("image", help="图片路径")
    inf.set_defaults(func=_cmd_info)

    h = sub.add_parser("hash", help="图像指纹（sha256/dhash/ahash；PNG/JPEG，v0.2.7）")
    h.add_argument("image", help="PNG/JPEG 路径")
    h.add_argument("--algo", default=None,
                   choices=["sha256", "dhash", "ahash"],
                   help="只取某一个值（收据仍含全部指纹）")
    h.set_defaults(func=_cmd_hash)

    df = sub.add_parser("diff", help="两张图差异（YIQ+阈值；PNG/JPEG，v0.2.7）")
    df.add_argument("a", help="图 A")
    df.add_argument("b", help="图 B")
    df.add_argument("--threshold", type=float, default=0.12,
                    help="0~1 颜色距离阈值（越大越宽容，缺省 0.12）")
    df.add_argument("--out", default=None, help="差异图输出路径（可选）")
    df.set_defaults(func=_cmd_diff)

    el = sub.add_parser("element", help="元素视口矩形+可见性（CSS px，v0.2.7）")
    el.add_argument("selector", help="CSS 选择器")
    el.add_argument("--scroll", action="store_true",
                    help="先 scrollIntoView(center) 再量")
    _add_common(el)
    el.set_defaults(func=_cmd_element)

    snp = sub.add_parser("snapshot",
                         help="页面结构快照（ref+box，不靠像素猜坐标，v0.6.0）")
    snp.add_argument("--max-nodes", dest="max_nodes", type=int, default=150)
    _add_common(snp)
    snp.set_defaults(func=_cmd_snapshot)

    fr = sub.add_parser("frames", help="frame 树 + iframe 自身矩形（v0.2.7）")
    _add_common(fr)
    fr.set_defaults(func=_cmd_frames)

    fe = sub.add_parser("frame-element",
                        help="iframe 内元素 → 主页面视口 CSS 矩形（v0.2.7）")
    fe.add_argument("iframe", help='iframe 选择器；嵌套用 JSON 数组 ["#a","#b"]')
    fe.add_argument("selector", help="iframe 内元素选择器")
    _add_common(fe)
    fe.set_defaults(func=_cmd_frame_element)

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
    cc.add_argument("--from-x", dest="from_x", type=int, default=None,
                    help="接近轨迹起点 x（v0.2.6；缺省目标周围随机方位，"
                         "不再恒从左上角出发）")
    cc.add_argument("--from-y", dest="from_y", type=int, default=None,
                    help="接近轨迹起点 y")
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
    cb.add_argument("--from-x", dest="from_x", type=int, default=None,
                    help="接近轨迹起点 x（v0.2.6；缺省随机方位）")
    cb.add_argument("--from-y", dest="from_y", type=int, default=None,
                    help="接近轨迹起点 y")
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

    # 子解析器各自独立，allow_abbrev 不会继承父设置——逐个关掉前缀缩写
    # （v0.2.6 Q22：`--ops` 被 --ops-file 前缀匹配吞掉的根源）
    for _act in getattr(ap._subparsers, "_group_actions", []):
        for _name, _sp in _act.choices.items():
            _sp.allow_abbrev = False

    a = ap.parse_args(argv)
    return a.func(a)


def os_startfile(path):
    """用系统默认看图器打开（v0.2.6 Q23：去掉双层包装与重复定义）。"""
    os.startfile(path)


if __name__ == "__main__":
    sys.exit(main())
