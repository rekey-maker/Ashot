# -*- coding: utf-8 -*-
"""Ashot.mcp —— stdio MCP 脸（零业务，转发 capture/output/annotate）。

范式：alrec_mcp 同款换行分帧 JSON-RPC 2.0；注册宿主 mcp.servers.ashot：
  {"ashot": {"type": "stdio", "command": "python",
             "args": ["<仓库根>/ashot_mcp.py"], "cwd": "<仓库根>"}}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import __version__, annotate, annotate_gdi, capture, output  # noqa: E402

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


def _shot(mode="full", screen=None, out=None, clip=False, keep=False,
          area=None, retention_days=30):
    """桌面截图：mode=full(全虚拟桌面)/screen(单屏,screen=序号)/win(前台窗口)
    /area(区域,area=[l,t,w,h])。返回 PNG 绝对路径；clip=true 只进剪贴板
    不落盘。每次运行顺手清理超 retention_days 的旧图（keep=true 跳过）。"""
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
    return json.dumps({"ok": True, "path": path, "all_black": all_black,
                       "gc": {"removed": n, "freed_mb": round(mb, 1)}},
                      ensure_ascii=False)


def _screens():
    """列出显示器（index/分辨率/偏移/主屏标记）。"""
    return json.dumps({"ok": True, "screens": capture.list_screens()},
                      ensure_ascii=False)


def _annotate(image, ops, out=None):
    """对既有 PNG 标注：ops=JSON 数组，kind ∈ rect/ellipse/arrow/line/
    text(中文可标注，GDI+ 系统字体)/mosaic/blur/step(自动递增编号)/
    number(显式编号 value)/spotlight(聚光灯 dim)/smarterase(智能擦除)。
    矢量抗锯齿渲染（GDI+），失败自动降级纯像素画布——收据 backend 字段
    如实标注（gdi+/pixel）。返回标注后 PNG 绝对路径；out 缺省写
    <原名>_annotated.png——绝不覆盖原图（v0.1.5 P1 根修，与 CLI 对齐）。"""
    with open(str(image), "rb") as fh:
        png = fh.read()
    ops_list = json.loads(ops) if isinstance(ops, str) else ops
    out_bytes, backend = annotate_gdi.annotate_png_vector(png, ops_list or [])
    stem = str(image)
    default_out = (stem.rsplit(".", 1)[0] + "_annotated.png"
                   if "." in os.path.basename(stem)
                   else stem + "_annotated.png")
    path = output.save(out_bytes, out=out or default_out)
    return json.dumps({"ok": True, "path": path, "backend": backend},
                      ensure_ascii=False)


def _tool_named(name, fn):
    _tool(fn)
    entry = TOOLS.pop(fn.__name__)
    entry["name"] = name
    entry["_fn"] = fn
    TOOLS[name] = entry


_tool_named("ashot_shot", _shot)
_tool_named("ashot_screens", _screens)
_tool_named("ashot_annotate", _annotate)

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
                    text = entry["_fn"](**args)
                    resp = {"jsonrpc": "2.0", "id": rid, "result": {
                        "content": [{"type": "text", "text": text}]}}
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
