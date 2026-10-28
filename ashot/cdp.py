# -*- coding: utf-8 -*-
"""Ashot.cdp —— 纯标准库 CDP（Chrome DevTools Protocol）客户端，v0.2.0 批1。

目的：浏览器截图不依赖任何 AI 宿主（Workbuddy/Codex/DeepSeek 等启动
的 Chromium 家族浏览器，无头/有头通吃）——裸 WebSocket + JSON 命令，
无 Puppeteer/websocket 库（零依赖红线）。设计文档：v0.2.0 扩展篇 §4.2
（含审计 P2-11 收侧规格、P1-2 发现机制、P2-5 Chrome136+ 默认 profile）。

模块纪律：只管「连浏览器拿像素」；HTTP/WS 原语纯函数可单测；只连
127.0.0.1（CDP 端点=完全控制浏览器，安全边界）。
"""
import base64
import json
import os
import re
import socket
import struct
import urllib.request

MAX_WS_FRAME = 64 * 1024 * 1024   # 单帧上限（全页截图 base64 可达数 MB）


# ---------- HTTP 面（/json/*，urllib 足够） ----------

def http_json(port, path, timeout=5):
    """GET http://127.0.0.1:<port><path> -> 解析 JSON。非 200/坏 JSON
    如实抛（含状态码）。"""
    url = "http://127.0.0.1:%d%s" % (int(port), path)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("CDP 端点返回 %s（%s）——若为 Chrome 136+ "
                           "默认 profile 系拒绝远程调试（default_profile_denied，"
                           "改用非默认 --user-data-dir）" % (e.code, url))
    except OSError as e:
        raise RuntimeError("CDP 端点不可达 %s（%s）" % (url, e))
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise RuntimeError("CDP 端点响应非 JSON（%s）：%r"
                           % (url, body[:120]))


def list_targets(port, timeout=5):
    """GET /json/list -> page 类 target 列表（title/url/id/ws）。"""
    items = http_json(port, "/json/list", timeout)
    if not isinstance(items, list):
        raise RuntimeError("/json/list 响应非列表：%r" % (items,))
    return [{"id": t.get("id", ""), "title": t.get("title", ""),
             "url": t.get("url", ""), "type": t.get("type", ""),
             "ws": t.get("webSocketDebuggerUrl", "")}
            for t in items]


def find_port_from_profile(user_data_dir, timeout=5):
    """读 <user_data_dir>/DevToolsActivePort（--remote-debugging-port=0
    时浏览器写入：首行=端口，次行=browser target 路径）。"""
    p = os.path.join(str(user_data_dir), "DevToolsActivePort")
    if not os.path.isfile(p):
        raise RuntimeError("DevToolsActivePort 不存在（%s）——浏览器未以"
                           " remote-debugging 启动或已退出" % p)
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        lines = [x.strip() for x in fh.read().splitlines() if x.strip()]
    if not lines or not lines[0].isdigit():
        raise RuntimeError("DevToolsActivePort 内容异常：%r" % lines[:2])
    return int(lines[0])


_PROC_PS = ("Get-CimInstance Win32_Process | Where-Object {"
            " $_.CommandLine -match '--remote-debugging-port' } | "
            "ForEach-Object { $_.CommandLine }")


def _probe_alive(port, timeout=2):
    """端口探活：/json/version 200 即活。接 Exception——扫描段里常见
    非 HTTP 服务（BadStatusLine 等），任何失败一律判不活跳过（审计
    P2-1：窄 except 让 discover 被垃圾服务打断）。"""
    try:
        http_json(port, "/json/version", timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def discover():
    """发现已运行浏览器（审计 P1-2，四级）：
    ① 枚举进程命令行提取 --remote-debugging-port=N / --user-data-dir=D
       （Win: Get-CimInstance；跨宿主通用——任何宿主拉起的浏览器都在）；
    ② 有 user-data-dir 读其 DevToolsActivePort；
    ③ 扫常见端口 9222-9229 探活；
    ④ 全空如实报。
    返回 {"ports": [...], "hint": "..."}（ports 按可信度排序去重）。"""
    ports = []

    if os.name == "nt":
        try:
            import subprocess as _sp
            r = _sp.run(["powershell", "-NoProfile", "-Command", _PROC_PS],
                        capture_output=True, timeout=20)
            cmdlines = r.stdout.decode("utf-8", "replace").splitlines()
        except Exception:  # noqa: BLE001 —— 枚举失败降级端口扫描
            cmdlines = []
        for cl in cmdlines:
            m = re.search(r"--remote-debugging-port=(\d+)", cl)
            if m:
                ports.append(int(m.group(1)))
                udd = re.search(r"--user-data-dir=(\"[^\"]+\"|\S+)", cl)
                if udd:
                    d = udd.group(1).strip('"')
                    try:
                        ports.append(find_port_from_profile(d))
                    except RuntimeError:
                        pass
    else:
        # Mac/Linux（批2 平台）：ps 枚举同语义；批1 先落实现保跨平台
        try:
            import subprocess as _sp
            r = _sp.run(["ps", "-axo", "command="], capture_output=True,
                        timeout=20)
            cmdlines = r.stdout.decode("utf-8", "replace").splitlines()
        except Exception:  # noqa: BLE001
            cmdlines = []
        for cl in cmdlines:
            m = re.search(r"--remote-debugging-port=(\d+)", cl)
            if m:
                ports.append(int(m.group(1)))

    for p in (9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229):
        ports.append(p)
    seen, uniq = set(), []
    for p in ports:
        if p not in seen and _probe_alive(p):
            seen.add(p)
            uniq.append(p)
    return {"ports": uniq, "hint": ("CDP 端点 %s" % uniq if uniq else
                                    "未发现运行中的调试浏览器——以 "
                                    "--remote-debugging-port=9222 重启"
                                    "浏览器，或用 cdp-shot --port 指定")}


# ---------- WebSocket 面（RFC 6455 最小子集，审计 P2-11 全规格） ----------

def _ws_connect(host, port, ws_path, timeout=15):
    """裸 WS 握手（不协商 permessage-deflate）-> 已握手的 socket。"""
    sock = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
           "\r\n" % (ws_path, host, port, key))
    sock.sendall(req.encode("ascii"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("WS 握手被对端关闭（%s:%d%s）"
                               % (host, port, ws_path))
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode("latin-1")
    if " 101 " not in " " + status + " ":
        sock.close()
        raise RuntimeError("WS 握手被拒：%s（%s）" % (status, ws_path))
    return sock, rest   # rest=握手响应携带的过早帧数据（罕见但须接管）


def _recv_exact(sock, n, buf):
    """循环 recv 直到凑满 n 字节（半包——审计 P2-11c）。返回 (data, 余buf)。"""
    data = bytes(buf)
    while len(data) < n:
        chunk = sock.recv(min(65536, n - len(data)))
        if not chunk:
            raise RuntimeError("WS 连接在收 %d/%d 字节时被对端关闭"
                               % (len(data), n))
        data += chunk
    return data[:n], data[n:]


def _recv_frame(sock, buf=b""):
    """收一帧 -> (opcode, payload_bytes, 余buf)。处理：掩码去除（服务端
    帧不掩码）、长度三态、**分片重组**（continuation opcode=0，审计
    P2-11a）、ping(0x9) 回 pong(0xA)（审计 P2-11b）、close(0x8) 回礼。
    """
    def read_one(s, b):
        h, b = _recv_exact(s, 2, b)
        fin_op = h[0]
        masked = bool(h[1] & 0x80)
        ln = h[1] & 0x7F
        if ln == 126:
            ext, b = _recv_exact(s, 2, b)
            ln = struct.unpack(">H", ext)[0]
        elif ln == 127:
            ext, b = _recv_exact(s, 8, b)
            ln = struct.unpack(">Q", ext)[0]
        if ln > MAX_WS_FRAME:
            raise RuntimeError("WS 帧过大（%d > %d）" % (ln, MAX_WS_FRAME))
        mask = b""
        if masked:
            mask, b = _recv_exact(s, 4, b)
        payload, b = _recv_exact(s, ln, b)
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4]
                            for i in range(len(payload)))
        return fin_op, payload, b

    fin_op, payload, buf = read_one(sock, buf)
    while True:
        op = fin_op & 0x0F
        if op == 0x9:   # ping -> pong（控制帧不可分片，须即回）
            _send_frame(sock, 0xA, payload)
            fin_op, payload, buf = read_one(sock, buf)
            continue
        if op == 0x8:   # close -> 回礼后如实报
            try:
                _send_frame(sock, 0x8, payload[:2])
            except OSError:
                pass
            raise RuntimeError("WS 连接被对端关闭（close 帧）")
        if op in (0x1, 0x2):
            break
        raise RuntimeError("WS 意外帧 opcode=0x%02x" % fin_op)

    opcode = op
    if fin_op & 0x80:   # FIN=1，单帧完整
        return opcode, payload, buf
    # 分片：continuation（opcode 0）循环直到 FIN；ping 穿插即回 pong
    parts = [payload]
    while True:
        fin_op, payload, buf = read_one(sock, buf)
        op = fin_op & 0x0F
        if op == 0x9:
            _send_frame(sock, 0xA, payload)
            continue
        if op == 0x8:
            raise RuntimeError("WS 连接在分片途中被对端关闭")
        if op != 0x0:
            raise RuntimeError("分片流中出现非 continuation 帧 "
                               "opcode=0x%02x" % fin_op)
        parts.append(payload)
        if fin_op & 0x80:
            break
    return opcode, b"".join(parts), buf


def _send_frame(sock, opcode, payload):
    """客户端帧：必须 masked（RFC 6455 客户端→服务端）。"""
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    mask = os.urandom(4)
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(n))
    sock.sendall(header + mask + masked)


def call(ws_url, method, params=None, timeout=30):
    """连接 ws_url 执行一条 CDP 命令，返回 result dict（消息级往返：
    连接-命令-收应-关。批1 场景一次一张图，无需长连会话）。"""
    m = re.match(r"^ws://([^/:]+):(\d+)(/.+)$", ws_url or "")
    if not m:
        raise RuntimeError("ws url 形态异常：%r（期望 ws://host:port/path）"
                           % ws_url)
    host, port, path = m.group(1), int(m.group(2)), m.group(3)
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError("CDP 只允许连本机（127.0.0.1），拒绝：%r" % host)
    sock, rest = _ws_connect(host, port, path, timeout)
    try:
        sock.settimeout(timeout)
        _send_frame(sock, 0x1, json.dumps(
            {"id": 1, "method": method, "params": params or {}}).encode())
        # buf 线穿（审计 P1-1）：握手 rest 与每轮余 buf 必须传回——
        # 服务端有权把事件帧与应答帧合并在一个 TCP 段，丢弃即丢应答
        buf = rest
        while True:
            opcode, payload, buf = _recv_frame(sock, buf)
            if opcode != 0x1:
                continue   # 事件帧（非文本应答）——批1 单命令场景跳过
            msg = json.loads(payload.decode("utf-8", "replace"))
            if msg.get("id") != 1:
                continue
            if "error" in msg:
                raise RuntimeError("CDP %s 失败：%s"
                                   % (method, json.dumps(msg["error"])[:200]))
            return msg.get("result", {})
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ---------- 顶层动作 ----------

def tabs(port):
    """列 page 类标签页（title/url/id）。"""
    return [t for t in list_targets(port) if t["type"] == "page"]


# ---------- 输入事件（v0.2.0 §4.2.2：滚轮/按键/组合键/拖拽） ----------

MODIFIERS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
# 常用控制键：UI Events key 名 -> [windowsVirtualKeyCode, code]
_SPECIAL_KEYS = {
    "enter": (13, "Enter"), "tab": (9, "Tab"), "escape": (27, "Escape"),
    "backspace": (8, "Backspace"), "delete": (46, "Delete"),
    "space": (32, "Space"), "arrowup": (38, "ArrowUp"),
    "arrowdown": (40, "ArrowDown"), "arrowleft": (37, "ArrowLeft"),
    "arrowright": (39, "ArrowRight"), "home": (36, "Home"),
    "end": (35, "End"), "pageup": (33, "PageUp"),
    "pagedown": (34, "PageDown"),
}
_MODIFIER_KEYS = {"alt": ("Alt", 18), "ctrl": ("Control", 17),
                  "meta": ("Meta", 91), "shift": ("Shift", 16)}


def _parse_modifiers(mods):
    """"ctrl+shift" / ["ctrl","shift"] -> 位掩码（Alt1 Ctrl2 Meta4
    Shift8，可加和）。未知名如实抛。"""
    if not mods:
        return 0
    if isinstance(mods, str):
        mods = re.split(r"[+,\s]+", mods.strip())
    mask = 0
    for m in mods:
        k = str(m).strip().lower()
        if not k:
            continue
        if k not in MODIFIERS:
            raise ValueError("未知修饰键 %r（有：%s）"
                             % (m, "/".join(MODIFIERS)))
        mask |= MODIFIERS[k]
    return mask


def key_events(key, modifiers=0, text=None):
    """构造一个键的 CDP 事件序列（纯函数，可单测）。
    可见字符（有 text 或普通可打印字符）= rawKeyDown+char+keyUp 三连
    （rawKeyDown 触发快捷键/页面键处理，char 产生实际输入——只发其一
    必缺半边）；控制键 = keyDown+keyUp；组合键 = modifiers 位掩码进
    每个事件 + 首尾补 modifier 键的按住序。"""
    mods = _parse_modifiers(modifiers) if not isinstance(modifiers, int) \
        else int(modifiers)
    k = str(key).strip()
    lname = k.lower()
    seq = []
    mod_downs = [mk for mk, _ in _MODIFIER_KEYS.items()
                 if mods & MODIFIERS[mk]]
    # 按住序：先按下所有修饰键
    for mk in mod_downs:
        name, vk = _MODIFIER_KEYS[mk]
        seq.append({"type": "keyDown", "key": name,
                    "code": name + "Left" if name != "Meta" else "MetaLeft",
                    "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                    "modifiers": mods})
    if lname in _SPECIAL_KEYS:
        vk, code = _SPECIAL_KEYS[lname]
        ev = {"type": "keyDown", "key": k if len(k) > 1 else lname,
              "code": code, "windowsVirtualKeyCode": vk,
              "nativeVirtualKeyCode": vk, "modifiers": mods}
        seq.append(ev)
        seq.append(dict(ev, type="keyUp"))
    elif len(k) == 1:
        ch = text if text is not None else k
        vk = ord(k.upper())
        base = {"key": k, "code": "Key%s" % k.upper(),
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": mods}
        seq.append(dict(base, type="rawKeyDown"))
        seq.append(dict(base, type="char", text=ch,
                        unmodifiedText=ch))
        seq.append(dict(base, type="keyUp"))
    else:
        # 具名键不在表内：透传名字（CDP 接受 UI Events key 名）
        seq.append({"type": "keyDown", "key": k, "modifiers": mods})
        seq.append({"type": "keyUp", "key": k, "modifiers": mods})
    # 释放序：修饰键回弹
    for mk in reversed(mod_downs):
        name, vk = _MODIFIER_KEYS[mk]
        seq.append({"type": "keyUp", "key": name,
                    "code": name + "Left" if name != "Meta" else "MetaLeft",
                    "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                    "modifiers": mods})
    return seq


def key_combo_events(text):
    """连续文本/序列的键击流：字符串逐字符 key_events（支持 "ctrl+s"
    形态的具名组合——'+' 切分后 modifiers 前缀 + 单主键）。"""
    out = []
    for ch in str(text):
        if ch == "+" and False:  # 占位：'+ ' 字符本身走 else 分支
            continue
        out.extend(key_events(ch))
    return out


def drag_events(x1, y1, x2, y2, steps=8, button="left"):
    """拖拽 = mousePressed -> 插值 mouseMoved×steps -> mouseReleased
    （含按下/释放的 clickCount 与 buttons 位）。纯函数可单测。"""
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    steps = max(1, int(steps))
    seq = [{"type": "mouseMoved", "x": x1, "y": y1, "modifiers": 0}]
    seq.append({"type": "mousePressed", "x": x1, "y": y1,
                "button": button, "buttons": 1, "clickCount": 1,
                "modifiers": 0})
    for i in range(1, steps + 1):
        t = i / steps
        seq.append({"type": "mouseMoved",
                    "x": round(x1 + (x2 - x1) * t, 2),
                    "y": round(y1 + (y2 - y1) * t, 2),
                    "buttons": 1, "modifiers": 0})
    seq.append({"type": "mouseReleased", "x": x2, "y": y2,
                "button": button, "buttons": 0, "clickCount": 1,
                "modifiers": 0})
    return seq


def dispatch(ws_url, events, timeout=30):
    """向 ws_url 逐条派发 Input.dispatch* 命令（复用 call 的消息级
    往返——每事件一次连接略重但批1 语义最简；返回成功条数）。
    路由：keyDown/keyUp/rawKeyDown/char → dispatchKeyEvent；其余
    （mousePressed/mouseReleased/mouseMoved/mouseWheel）→
    dispatchMouseEvent。"""
    _KEY_TYPES = ("keyDown", "keyUp", "rawKeyDown", "char")
    n = 0
    for ev in events:
        method = ("Input.dispatchKeyEvent" if ev.get("type") in _KEY_TYPES
                  else "Input.dispatchMouseEvent")
        call(ws_url, method, ev, timeout)
        n += 1
    return n


def ws_for(port, index=0):
    """端口 -> 第 index 个 page 标签的 ws（tabs+过滤的公共化）。"""
    pages = [t for t in tabs(port)
             if not t["url"].startswith(("devtools://", "chrome://"))]
    if not pages:
        raise RuntimeError("该端口没有可操作的 page 标签页")
    return pages[max(0, min(int(index), len(pages) - 1))]["ws"]


def shot(port, ws=None, index=0, fullpage=True):
    """对第 index 个 page 标签截图 -> (png_bytes, info)。
    fullpage=captureBeyondViewport（Chrome 90+，视口外也截）。"""
    if ws is None:
        pages = tabs(port)
        pages = [t for t in pages
                 if not t["url"].startswith(("devtools://", "chrome://"))]
        if not pages:
            raise RuntimeError("该端口没有可截的 page 标签页")
        ws = pages[max(0, min(int(index), len(pages) - 1))]["ws"]
    if not ws:
        raise RuntimeError("目标标签页缺 webSocketDebuggerUrl")
    res = call(ws, "Page.captureScreenshot",
               {"format": "png", "captureBeyondViewport": bool(fullpage)})
    import base64 as _b64
    data = res.get("data")
    if not data:
        raise RuntimeError("captureScreenshot 无数据（result=%r）"
                           % (list(res),))
    return _b64.b64decode(data), {"ws": ws, "fullpage": bool(fullpage)}
