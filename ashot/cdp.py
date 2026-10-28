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
import math
import os
import random
import re
import socket
import struct
import time
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


class Session(object):
    """单连接多命令会话（v0.2.5）。

    为什么要有它（2026-10-28 实测）：旧的 `call()` 是"一命令一连接"，
    派发 30 个鼠标事件就握手 30 次。实测 17ms/事件——**全是重连开销**，
    真实节奏完全由网络决定，缓动速度只体现在空间采样密度上，时间上
    每个点间隔均匀得像机器。行为检测若看速度变化，这种均匀比真人更
    可疑。改成一次握手、逐条收发，才能把"故意给每步睡多久"变成可控
    参数（见 dispatch 的 `_delay_ms`）。
    """

    def __init__(self, ws_url, timeout=30):
        m = re.match(r"^ws://([^/:]+):(\d+)(/.+)$", ws_url or "")
        if not m:
            raise RuntimeError("ws url 形态异常：%r（期望 "
                               "ws://host:port/path）" % ws_url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        if host not in ("127.0.0.1", "localhost"):
            raise RuntimeError("CDP 只允许连本机（127.0.0.1），拒绝：%r" % host)
        self.sock, self._buf = _ws_connect(host, port, path, timeout)
        self.sock.settimeout(timeout)
        self._id = 0
        self.timeout = timeout

    def command(self, method, params=None):
        """发一条命令并等它自己的应答（id 递增，事件帧跳过）。"""
        self._id += 1
        mid = self._id
        _send_frame(self.sock, 0x1, json.dumps(
            {"id": mid, "method": method, "params": params or {}}).encode())
        # buf 线穿（审计 P1-1）：握手 rest 与每轮余 buf 必须传回——
        # 服务端有权把事件帧与应答帧合并在一个 TCP 段，丢弃即丢应答
        while True:
            opcode, payload, self._buf = _recv_frame(self.sock, self._buf)
            if opcode != 0x1:
                continue          # 事件帧（不含 id），跳过
            msg = json.loads(payload.decode("utf-8", "replace"))
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise RuntimeError("CDP %s 失败：%s"
                                   % (method, json.dumps(msg["error"])[:200]))
            return msg.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def call(ws_url, method, params=None, timeout=30):
    """连接 ws_url 执行一条 CDP 命令，返回 result dict（连接-命令-收应-关）。
    单命令场景用它；成批派发请用 Session（省掉每事件一次握手）。"""
    with Session(ws_url, timeout) as s:
        return s.command(method, params)


# ---------- 顶层动作 ----------

def tabs(port):
    """列 page 类标签页（title/url/id）。"""
    return [t for t in list_targets(port) if t["type"] == "page"]


# ---------- 输入事件（v0.2.0 §4.2.2：滚轮/按键/组合键/拖拽） ----------

MODIFIERS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
# 控制键：小写别名 -> (UI Events 规范 key 名, VK, code)——key 名是
# Chromium DomKey 精确匹配用的（审计 P1-1：传小写别名页面 e.key=空串）
_SPECIAL_KEYS = {
    "enter": ("Enter", 13, "Enter"), "tab": ("Tab", 9, "Tab"),
    "escape": ("Escape", 27, "Escape"),
    "backspace": ("Backspace", 8, "Backspace"),
    "delete": ("Delete", 46, "Delete"), "space": (" ", 32, "Space"),
    "arrowup": ("ArrowUp", 38, "ArrowUp"),
    "arrowdown": ("ArrowDown", 40, "ArrowDown"),
    "arrowleft": ("ArrowLeft", 37, "ArrowLeft"),
    "arrowright": ("ArrowRight", 39, "ArrowRight"),
    "home": ("Home", 36, "Home"), "end": ("End", 35, "End"),
    "pageup": ("PageUp", 33, "PageUp"), "pagedown": ("PageDown", 34,
                                                     "PageDown"),
    "f1": ("F1", 112, "F1"), "f2": ("F2", 113, "F2"),
    "f3": ("F3", 114, "F3"), "f4": ("F4", 115, "F4"),
    "f5": ("F5", 116, "F5"), "f6": ("F6", 117, "F6"),
    "f7": ("F7", 118, "F7"), "f8": ("F8", 119, "F8"),
    "f9": ("F9", 120, "F9"), "f10": ("F10", 121, "F10"),
    "f11": ("F11", 122, "F11"), "f12": ("F12", 123, "F12"),
    "semicolon": (";", 186, "Semicolon"), "equal": ("=", 187, "Equal"),
    "comma": (",", 188, "Comma"), "minus": ("-", 189, "Minus"),
    "period": (".", 190, "Period"), "slash": ("/", 191, "Slash"),
    "backquote": ("`", 192, "Backquote"),
    "bracketleft": ("[", 219, "BracketLeft"),
    "backslash": ("\\", 220, "Backslash"),
    "bracketright": ("]", 221, "BracketRight"),
    "quote": ("'", 222, "Quote"),
    "insert": ("Insert", 45, "Insert"),
    "printscreen": ("PrintScreen", 44, "PrintScreen"),
    "numlock": ("NumLock", 144, "NumLock"),
    "capslock": ("CapsLock", 20, "CapsLock"),
    "scrolllock": ("ScrollLock", 145, "ScrollLock"),
    "pause": ("Pause", 19, "Pause"),
    "contextmenu": ("ContextMenu", 93, "ContextMenu"),
    "numpad0": ("0", 96, "Numpad0"), "numpad1": ("1", 97, "Numpad1"),
    "numpad2": ("2", 98, "Numpad2"), "numpad3": ("3", 99, "Numpad3"),
    "numpad4": ("4", 100, "Numpad4"), "numpad5": ("5", 101, "Numpad5"),
    "numpad6": ("6", 102, "Numpad6"), "numpad7": ("7", 103, "Numpad7"),
    "numpad8": ("8", 104, "Numpad8"), "numpad9": ("9", 105, "Numpad9"),
    "numpadadd": ("+", 107, "NumpadAdd"),
    "numpadsubtract": ("-", 109, "NumpadSubtract"),
    "numpadmultiply": ("*", 106, "NumpadMultiply"),
    "numpaddivide": ("/", 111, "NumpadDivide"),
    "numpaddecimal": (".", 110, "NumpadDecimal"),
    "numpadenter": ("Enter", 13, "NumpadEnter"),
}
# 移位级符号（Shift+键位产生）：字符 -> (底层具名键别名, VK, code)
# ——key=字符本身（UI Events 规范），P2-1 补全
_SHIFT_SYMS = {
    ":": ("semicolon", 186, "Semicolon"), "+": ("equal", 187, "Equal"),
    "<": ("comma", 188, "Comma"), "_": ("minus", 189, "Minus"),
    ">": ("period", 190, "Period"), "?": ("slash", 191, "Slash"),
    "~": ("backquote", 192, "Backquote"),
    "!": ("digit1", 49, "Digit1"), "@": ("digit2", 50, "Digit2"),
    "#": ("digit3", 51, "Digit3"), "$": ("digit4", 52, "Digit4"),
    "%": ("digit5", 53, "Digit5"), "^": ("digit6", 54, "Digit6"),
    "&": ("digit7", 55, "Digit7"), "*": ("digit8", 56, "Digit8"),
    "(": ("digit9", 57, "Digit9"), ")": ("digit0", 58, "Digit0"),
    '"': ("quote", 222, "Quote"),
    "{": ("bracketleft", 219, "BracketLeft"),
    "}": ("bracketright", 221, "BracketRight"),
    "|": ("backslash", 220, "Backslash"),
}
# 符号字符 -> 具名键（让 ";" 这类直接可传，不必记 semicolon）
_SYM_ALIAS = {";": "semicolon", "=": "equal", ",": "comma", "-": "minus",
              ".": "period", "/": "slash", "`": "backquote",
              "[": "bracketleft", "\\": "backslash",
              "]": "bracketright", "'": "quote"}
_SYM_ALIAS.update({c: v[0] for c, v in _SHIFT_SYMS.items()})
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
        key_name, vk, code = _SPECIAL_KEYS[lname]
        ev = {"type": "keyDown", "key": key_name, "code": code,
              "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
              "modifiers": mods}
        seq.append(ev)
        seq.append(dict(ev, type="keyUp"))
    elif len(k) == 1 and k in _SYM_ALIAS:
        # 符号字符别名（";"/":"→ 查表）：key=符号本身（UI Events 规范，
        # 审计 P1-2：code 名不是 key 名），VK 走查表非 ord
        name = _SYM_ALIAS[k]
        ent = _SHIFT_SYMS.get(k)
        if ent:
            _, vk, code = ent   # 移位级符号：直查 (别名, VK, code)
        else:
            _, vk, code = _SPECIAL_KEYS[name]
        base = {"key": k, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": mods}
        seq.append(dict(base, type="keyDown"))
        seq.append(dict(base, type="char", text=k, unmodifiedText=k))
        seq.append(dict(base, type="keyUp"))
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
        # 具名键不在表内：透传名字（CDP 接受 UI Events key 名），但
        # 收据层亮牌——无 VK 码部分页面收不到（v0.2.2 如实亮牌纪律）
        seq.append({"type": "keyDown", "key": k, "modifiers": mods,
                    "unresolved": True})
        seq.append({"type": "keyUp", "key": k, "modifiers": mods,
                    "unresolved": True})
    # 释放序：修饰键回弹
    for mk in reversed(mod_downs):
        name, vk = _MODIFIER_KEYS[mk]
        seq.append({"type": "keyUp", "key": name,
                    "code": name + "Left" if name != "Meta" else "MetaLeft",
                    "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                    "modifiers": mods})
    # unresolved 标记保留在事件上（调用方/合并序列可检查）——由
    # dispatch() 负责剥除并汇总进收据（v0.2.2 亮牌契约）
    return seq


_BUTTON_MASK = {"left": 1, "right": 2, "middle": 4}   # 审计 P2-1：按下
# 键位掩码（Playwright toButtonsMask 同款）——旧版硬编码 1 让中键/右键
# 按下时 e.buttons 矛盾


def _press_mask(button):
    return _BUTTON_MASK.get(str(button), 1)


# ---------- 人类化移动轨迹（v0.2.4，设计文档 §4.2.3） ----------

def _trajectory(x1, y1, x2, y2, steps=0, jitter=2.0, seed=None,
                constrained=False, max_perp=2.5):
    """轨迹核心：返回 [(te, x, y)]，te 是缓动后的进度（0→1）。

    constrained=False（自由移动）：三次贝塞尔 + 随机弓形偏移，制造弧线。
    constrained=True（**受约束拖拽**，v0.2.5）：主轴线性插值，垂直方向
    偏移被压在 ±max_perp 内，只保留微抖。

    为什么必须分两档（2026-10-28 实测）：弓形偏移是按距离比例算的
    （dist 的 10%~25%），自由移动时它是"像人"的特征；但**拖动滑块时
    物体被约束在轨道上**，同样的弓形会让 520px 的水平拖拽纵向漂 50px
    ——滑块直接脱轨。旧版 drag 复用了自由移动轨迹，这是硬伤。
    """
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    dist = math.hypot(x2 - x1, y2 - y1)
    if steps <= 0:
        steps = max(8, min(28, int(dist / 25)))
    rnd = random.Random(seed)
    if dist < 1:
        return [(1.0, x2, y2)]
    ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
    # 垂直分量单位向量（屏幕坐标顺时针旋转 90°）
    px, py = -uy, ux
    if constrained:
        # 受控：无弓形，垂直只留 max_perp 内的抖动
        ctl = None
    else:
        bow = dist * rnd.uniform(0.10, 0.25) * rnd.choice((-1, 1))
        c1 = (x1 + ux * dist * 0.33 - uy * bow,
              y1 + uy * dist * 0.33 + ux * bow)
        c2 = (x1 + ux * dist * 0.66 + uy * bow * 0.6,
              y1 + uy * dist * 0.66 - ux * bow * 0.6)
        ctl = (c1, c2)
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        # 缓动：ease-in-out（慢起快中慢收）
        te = t * t * (3 - 2 * t)
        if constrained:
            bx = x1 + (x2 - x1) * te
            by = y1 + (y2 - y1) * te
        else:
            u, v = te, 1 - te
            bx = (x1 * v * v * v + ctl[0][0] * 3 * u * v * v
                  + ctl[1][0] * 3 * u * u * v + x2 * u * u * u)
            by = (y1 * v * v * v + ctl[0][1] * 3 * u * v * v
                  + ctl[1][1] * 3 * u * u * v + y2 * u * u * u)
        # 抖动：中段大、两端收敛为 0（首尾必须精确落点）
        if i < steps:
            fade = math.sin(math.pi * te)   # 0→1→0
            if constrained:
                # 垂直：只抽**一个标量**再乘单位垂向量，偏移严格垂直于
                # 主轴且幅值 ≤ max_perp。若对 x/y 各抽一次，偏移方向会
                # 跑偏、幅值上界变成 √2×max_perp（v0.2.5 修正）。
                amp = min(jitter, max_perp)
                perp = rnd.uniform(-max_perp, max_perp) * fade
                bx += px * perp
                by += py * perp
                # 主轴：只沿运动方向微抖，不影响落点精度
                along = rnd.uniform(-amp * 0.4, amp * 0.4) * fade
                bx += ux * along
                by += uy * along
            else:
                bx += rnd.uniform(-jitter, jitter) * fade
                by += rnd.uniform(-jitter, jitter) * fade
        out.append((te, round(bx, 2), round(by, 2)))
    return out


def human_move_events(x1, y1, x2, y2, steps=0, jitter=2.0, seed=None,
                      max_perp=None):
    """人类化鼠标轨迹：三次贝塞尔（随机控制点）+ 缓动速度曲线
    （慢起-快中-慢收）+ 逐点微抖动（业界反检测共识配方）。

    steps=0 时按距离自适应（约 8~28 步）；jitter=每点随机偏移幅值
    （CSS 像素，0 关闭）；seed 可复现（测试用）。首尾精确落点
    （x2,y2 无抖动——点击必须准）。纯函数可单测。

    max_perp 给了就走**受约束**模式（垂直偏移上限，拖滑块用），
    不给=自由弧线。"""
    pts = _trajectory(x1, y1, x2, y2, steps=steps, jitter=jitter, seed=seed,
                      constrained=max_perp is not None,
                      max_perp=max_perp if max_perp is not None else 2.5)
    return [(x, y) for _te, x, y in pts]


def _spread_delays(tes, total_ms):
    """把总时长按**缓动进度差分**分配到每一步（v0.2.5）。

    为什么按 Δte 而不是按距离：速度曲线是设计出来的（慢-快-慢），
    距离大的那步本来就该"走得久一点"才符合这个速度；按距离平均分配
    等于把速度曲线拉成匀速，白设计了。Δte 才是真正的时间比例。
    """
    if not tes or total_ms <= 0:
        return [0] * len(tes)
    prev = 0.0
    d = []
    for te in tes:
        d.append(max(0.0, te - prev))
        prev = te
    s = sum(d) or 1.0
    return [total_ms * x / s for x in d]


def move_along(ws_url, x1, y1, x2, y2, steps=0, jitter=2.0, seed=None,
               buttons=0, timeout=30, max_perp=None):
    """沿人类化轨迹派发 mouseMoved 序列。返回 (派发数, 终点)。"""
    pts = human_move_events(x1, y1, x2, y2, steps=steps, jitter=jitter,
                            seed=seed, max_perp=max_perp)
    with Session(ws_url, timeout) as s:
        for x, y in pts:
            s.command("Input.dispatchMouseEvent",
                      {"type": "mouseMoved", "x": x, "y": y,
                       "buttons": int(buttons), "modifiers": 0})
    return len(pts), pts[-1]


def _approach_events(x, y, button, seed=None, approach_ms=None):
    """靠近目标的事件序列（带节奏延时，v0.2.5）。

    旧版 click 的接近轨迹是"瞬间铺完"的——空间上是曲线，时间上等于
    瞬移。真人从 A 点移到 B 点要 100~300ms，这里补上。approach_ms=0
    关闭延时（最省时间）。"""
    traj = _trajectory(0, 0, x, y, seed=seed)
    if approach_ms is None:
        approach_ms = max(120.0, min(320.0, 90.0 + math.hypot(x, y) * 0.35))
    delays = _spread_delays([t for t, _x, _y in traj], float(approach_ms))
    return [{"type": "mouseMoved", "x": px, "y": py, "modifiers": 0,
             "_delay_ms": delays[i]}
            for i, (_t, px, py) in enumerate(traj)]


def click_events(x, y, button="left", human=True, seed=None,
                 approach_ms=None):
    """单击：human=True 先沿人类化轨迹移动到位再按下（v0.2.4）；
    否则单步 moved（旧行为）。approach_ms 控制靠近耗时（0=不等）。"""
    seq = []
    if human:
        seq.extend(_approach_events(x, y, button, seed=seed,
                                    approach_ms=approach_ms))
    else:
        seq.append({"type": "mouseMoved", "x": x, "y": y, "modifiers": 0})
    seq.append({"type": "mousePressed", "x": x, "y": y,
                "button": button, "buttons": _press_mask(button),
                "clickCount": 1, "modifiers": 0,
                "_delay_ms": 20.0})
    seq.append({"type": "mouseReleased", "x": x, "y": y,
                "button": button, "buttons": 0, "clickCount": 1,
                "modifiers": 0,
                "_delay_ms": 45.0})
    return seq


def dblclick_events(x, y, button="left", count=2, human=True, seed=None,
                    approach_ms=None):
    """双击/多击：human=True 先人类化轨迹到位（v0.2.4）；False=单步
    moved 旧行为。clickCount 递增序列（浏览器据此合成 dblclick）。"""
    seq = []
    if human:
        seq.extend(_approach_events(x, y, button, seed=seed,
                                    approach_ms=approach_ms))
    else:
        seq.append({"type": "mouseMoved", "x": x, "y": y, "modifiers": 0})
    seq.append({"type": "mousePressed", "x": x, "y": y,
                "button": button, "buttons": _press_mask(button),
                "clickCount": 1, "modifiers": 0})
    seq.append({"type": "mouseReleased", "x": x, "y": y,
                "button": button, "buttons": 0, "clickCount": 1,
                "modifiers": 0})
    for i in range(2, max(2, int(count)) + 1):
        seq.append({"type": "mousePressed", "x": x, "y": y,
                    "button": button, "buttons": _press_mask(button),
                    "clickCount": i, "modifiers": 0,
                    "_delay_ms": 40.0})   # 双击间距（真人 60~120ms 含处理）
        seq.append({"type": "mouseReleased", "x": x, "y": y,
                    "button": button, "buttons": 0, "clickCount": i,
                    "modifiers": 0,
                    "_delay_ms": 25.0})
    return seq


# 节奏档位（v0.2.5）：拖拽**总时长** = clamp(base + dist×per, lo, hi)，
# 另配末端过冲幅度 over 与停顿 settle。真人拖滑块普遍 400~1200ms；
# 验证码场景要再慢一档（过顺滑反而像脚本），故 captcha 档总时长
# 900~2600ms 且末端有可见的"拖过头再拉回来"。
# 全部可调——不想等就 pace=fast 或显式给 total_ms。
PACES = {
    "fast": {"base": 120.0, "per": 0.45, "lo": 150.0, "hi": 600.0,
             "over": (0.0, 0.0), "settle": (15.0, 30.0)},
    "normal": {"base": 260.0, "per": 1.10, "lo": 320.0, "hi": 1400.0,
               "over": (1.0, 3.0), "settle": (30.0, 70.0)},
    "captcha": {"base": 700.0, "per": 2.40, "lo": 900.0, "hi": 2600.0,
                "over": (3.0, 6.0), "settle": (60.0, 130.0)},
}


def pace_total_ms(dist, pace="normal"):
    """按档位估拖拽总时长（纯函数，可单测）。未知档位退化 normal。"""
    p = PACES.get(str(pace).lower(), PACES["normal"])
    return max(p["lo"], min(p["hi"], p["base"] + float(dist) * p["per"]))


def drag_events(x1, y1, x2, y2, steps=0, button="left", human=True,
                jitter=2.0, seed=None, constrained=True, max_perp=2.5,
                total_ms=None, pace="normal"):
    """拖拽：按下 → 移动 → 末端过冲回退 → 松手。

    constrained=True（**缺省**，v0.2.5）：受约束轨迹——垂直偏移压在
    ±max_perp 内，主轴照常走完。**拖滑块/拖进度条/拖分栏必须用这个**。
    constrained=False：自由拖拽（画图、框选），保留贝塞尔弧线。
    human=False：直线插值（旧行为，最省事但最像机器）。

    节奏可三档调（用户 2026-10-28 要求：速度可调、验证码类慢点）：
      · fast    ≈ 120 + dist×0.45 ms（150~600ms）
      · normal  ≈ 260 + dist×1.10 ms（320~1400ms）
      · captcha ≈ 700 + dist×2.40 ms（900~2600ms，末端过冲更明显）
    显式 total_ms **优先**；total_ms=0 = 不睡（全速派发，旧行为）。
    """
    x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    press = _press_mask(button)
    dist = math.hypot(x2 - x1, y2 - y1)
    rnd = random.Random(seed)
    p = PACES.get(str(pace).lower(), PACES["normal"])
    seq = [{"type": "mouseMoved", "x": x1, "y": y1, "modifiers": 0}]
    seq.append({"type": "mousePressed", "x": x1, "y": y1,
                "button": button, "buttons": press, "clickCount": 1,
                "modifiers": 0})
    if human:
        if not steps or steps <= 0:
            # 旧版 max(10, dist/20) 短距离太稀疏（100px 只 13 个事件、
            # 185ms，比真人快一倍）——下限提到 18 步
            steps = (max(18, min(48, int(dist / 12))) if constrained
                     else max(20, min(56, int(dist / 10))))
        traj = _trajectory(x1, y1, x2, y2, steps=steps, jitter=jitter,
                           seed=seed, constrained=constrained,
                           max_perp=max_perp)
        if total_ms is None:
            total_ms = pace_total_ms(dist, pace) * rnd.uniform(0.88, 1.1)
        # total_ms=0（或 timing=false）= 全速派发：**连按下停顿和末端
        # settle 一起归零**，否则"不等"的承诺是假的
        zero = (float(total_ms) <= 0)
        delays = _spread_delays([t for t, _x, _y in traj], total_ms)
        seq[-1]["_delay_ms"] = 0.0 if zero else rnd.uniform(40, 90)
        for i, (te, x, y) in enumerate(traj):
            seq.append({"type": "mouseMoved", "x": x, "y": y,
                        "buttons": press, "modifiers": 0,
                        "_delay_ms": delays[i]})
        # 末端过冲 + 回退（人类调整动作；幅度由档位给）
        if not zero and dist > 20 and p["over"][1] > 0:
            ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
            ov = rnd.uniform(*p["over"])
            seq.append({"type": "mouseMoved", "buttons": press,
                        "x": round(x2 + ux * ov, 2),
                        "y": round(y2 + uy * ov, 2), "modifiers": 0,
                        "_delay_ms": rnd.uniform(*p["settle"])})
            seq.append({"type": "mouseMoved", "buttons": press,
                        "x": x2, "y": y2, "modifiers": 0,
                        "_delay_ms": rnd.uniform(*p["settle"])})
        else:
            # 松手前的停顿
            seq[-1]["_delay_ms"] = seq[-1].get("_delay_ms", 0) + \
                (0.0 if zero else rnd.uniform(*p["settle"]))
    else:
        steps = max(1, int(steps or 8))
        for i in range(1, steps + 1):
            t = i / steps
            seq.append({"type": "mouseMoved",
                        "x": round(x1 + (x2 - x1) * t, 2),
                        "y": round(y1 + (y2 - y1) * t, 2),
                        "buttons": press, "modifiers": 0})
    seq.append({"type": "mouseReleased", "x": x2, "y": y2,
                "button": button, "buttons": 0, "clickCount": 1,
                "modifiers": 0})
    return seq


def insert_text_events(text):
    """填表整段输入（**独立命令 Input.insertText**——粘贴式，不逐键击、
    不触发每键 keydown，与用户键鼠天然隔离）。v0.2.3 实弹修正：曾经
    前置 rawKeyDown(VK229) 占位事件，实弹证实非必需且 insertText 不是
    dispatchKeyEvent 的事件类型。返回单事件序列。"""
    return [{"type": "insertText", "text": str(text)}]


def dispatch(ws_url, events, timeout=30, realtime=True, stats=None):
    """向 ws_url 逐条派发 Input.dispatch* / Input.insertText 命令。

    v0.2.5：**一次握手派发整批**（旧版每事件重连，实测 17ms/事件全是
    握手开销）。事件上若带 `_delay_ms`（drag/click 的节奏提示），
    realtime=True 时在派发该事件前睡相应毫秒——这样速度曲线在**时间**
    上成立，而不只是空间采样密度。realtime=False 关掉延时（测试/极速）。

    stats=一个 dict（可选）：写入 planned_ms（计划总等待）/ slept_ms
    （实际睡了多久）/ clipped_ms（被上限夹掉的部分）。**别静默夹断**——
    调用方需要知道节奏有没有被改动。

    路由：keyDown/keyUp/rawKeyDown/char → dispatchKeyEvent；insertText
    → **独立命令 Input.insertText**（v0.2.3 实弹修正：它不是
    dispatchKeyEvent 的事件类型）；其余（mousePressed/mouseReleased/
    mouseMoved/mouseWheel）→ dispatchMouseEvent。
    返回 (成功条数, unresolved keys)。"""
    _KEY_TYPES = ("keyDown", "keyUp", "rawKeyDown", "char")
    n = 0
    unresolved = []
    planned = 0.0
    slept = 0.0
    clipped = 0.0
    with Session(ws_url, timeout) as s:
        for raw in events:
            # 拷贝后再剥元信息：**就地 pop 会吃掉调用方的数据**，同一
            # seq 重试时 _delay_ms/unresolved 全没了（节奏丢失、亮牌失效）
            ev = dict(raw)
            if ev.pop("unresolved", False) and \
                    ev.get("key") not in unresolved:
                unresolved.append(ev.get("key"))
            d = float(ev.pop("_delay_ms", 0) or 0)
            if realtime and d > 0:
                planned += d
                if d > 3000.0:
                    clipped += d - 3000.0
                    d = 3000.0
                time.sleep(d / 1000.0)
                slept += d
            t = ev.get("type")
            if t == "insertText":
                s.command("Input.insertText", {"text": ev.get("text", "")})
            elif t in _KEY_TYPES:
                s.command("Input.dispatchKeyEvent", ev)
            else:
                s.command("Input.dispatchMouseEvent", ev)
            n += 1
    if isinstance(stats, dict):
        stats["planned_ms"] = round(planned, 1)
        stats["slept_ms"] = round(slept, 1)
        stats["clipped_ms"] = round(clipped, 1)
    return n, unresolved


def ws_for(port, index=0):
    """端口 -> 第 index 个 page 标签的 ws（tabs+过滤的公共化）。"""
    pages = [t for t in tabs(port)
             if not t["url"].startswith(("devtools://", "chrome://"))]
    if not pages:
        raise RuntimeError("该端口没有可操作的 page 标签页")
    return pages[max(0, min(int(index), len(pages) - 1))]["ws"]


def png_size(data):
    """PNG 字节 -> (宽, 高)；非 PNG/太短返回 None。纯标准库读 IHDR
    （第 16~24 字节），不引入 PIL（零依赖红线）。"""
    try:
        if not data or len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", bytes(data[16:24]))
        return int(w), int(h)
    except Exception:  # noqa: BLE001 —— 尺寸是收据的附加项，不该炸主流程
        return None


def evaluate(ws, js, timeout=30, await_promise=False, return_by_value=True):
    """在标签页里执行一段 JS，返回 result 字典（v0.2.5）。

    **安全红线：只发 Runtime.evaluate，绝不发 Runtime.enable。**
    后者是字节系（acrawler）的明确检测点——一发即杀浏览器实例，
    2026-10-28 在 awsearch 上反复验证过。裸 evaluate 是安全的。

    js 形态：**函数体（内部 return）自动包 IIFE**；纯表达式直发。
    为什么 auto-wrap（实弹教训）：Runtime.evaluate 的 expression 不认
    裸 `return`——直接发"return 6*7"静默返回 undefined，画布注入这类
    多语句函数体整体失效且无报错。含 return / 多语句就包
    `(function(){ ... })()`，与 awsearch eval_js 同款约定。

    异常会以 exceptionDetails 形式如实返回（调用方决定怎么报），不静默。
    """
    body = str(js)
    if "return" in body or ";" in body or "\n" in body:
        body = "(function(){ %s })()" % body
    res = call(ws, "Runtime.evaluate", {
        "expression": body,
        "returnByValue": bool(return_by_value),
        "awaitPromise": bool(await_promise),
        "userGesture": True,
    }, timeout)
    return res


def layout(ws, timeout=15):
    """标签页布局信息 -> (视口 dict, dpr)。
    Page.getLayoutMetrics（cssLayoutViewport = CSS 像素）+ devicePixelRatio。
    用途：把**截图像素坐标**换算成**点击用的 CSS 坐标**——截图出图尺寸
    与视口 CSS 尺寸常不相等（全页截图/高 dpr/宿主缩放都会放大），
    目测截图坐标去点击必然落空（2026-10-28 实弹：1272×816 视口出图
    2544×1632，按截图点\"点赞\"打在了视频画面上）。"""
    m = call(ws, "Page.getLayoutMetrics", {}, timeout)
    vp = m.get("cssLayoutViewport") or {}
    out = {
        "vw": int(vp.get("clientWidth") or 0),
        "vh": int(vp.get("clientHeight") or 0),
        "content_w": (m.get("contentSize") or {}).get("width"),
        "content_h": (m.get("contentSize") or {}).get("height"),
        "visual": m.get("cssVisualViewport") or {},
    }
    dpr = None
    try:
        r = call(ws, "Runtime.evaluate",
                 {"expression": "window.devicePixelRatio",
                  "returnByValue": True}, timeout)
        dpr = (r.get("result") or {}).get("value")
    except Exception:  # noqa: BLE001 —— dpr 是可选附加项
        pass
    return out, dpr


def shot(port, ws=None, index=0, fullpage=True):
    """对第 index 个 page 标签截图 -> (png_bytes, info)。
    fullpage=captureBeyondViewport（Chrome 90+，视口外也截）。
    info 含 w/h（PNG 真实像素）与 vw/vh/dpr/to_css——**截图坐标 ×
    to_css = 点击用的 CSS 坐标**（详见 layout() 的说明）。"""
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
    png = _b64.b64decode(data)
    info = {"ws": ws, "fullpage": bool(fullpage)}
    sz = png_size(png)
    if sz:
        info["w"], info["h"] = sz[0], sz[1]
    try:
        lay, dpr = layout(ws)
        info["vw"], info["vh"] = lay["vw"], lay["vh"]
        if dpr:
            info["dpr"] = dpr
        if sz and lay["vw"] and lay["vh"]:
            # **不能用 min(vw/w, vh/h)**——全页截图时 vh 是视口高而
            # 图高是整页（content_h×dpr），两者相除会小一个数量级，按它
            # 换算必然点空（v0.2.5 修正，第一版就踩了这个坑）。
            if dpr:
                to_css = 1.0 / float(dpr)
            else:
                # 拿不到 dpr 时退化：假设非全页截图，图宽 = 视口宽
                to_css = lay["vw"] / float(sz[0])
            info["to_css"] = round(to_css, 4)
            info["hint"] = ("截图像素 × to_css = 点击用的 CSS 坐标；"
                            "点空多半是没换算")
    except Exception as e:  # noqa: BLE001 —— 布局信息是附加项，失败不吞主收据
        # 但**必须留下痕迹**：收据缺 vw/vh/to_css 时调用方要能看出是"拿
        # 不到"而不是"本来就没有"，否则会拿 w/h 当 CSS 坐标去点（必空）
        info["layout_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        info["hint"] = ("视口信息获取失败（页签忙/已关/CDP 异常），"
                        "to_css 缺失——不要直接用 w/h 当点击坐标")
    return png, info
