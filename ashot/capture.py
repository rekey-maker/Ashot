# -*- coding: utf-8 -*-
"""Ashot.capture —— 桌面截图（纯系统调用，零 daemon/网络依赖）。

暴露：shot(mode, screen=None, area=None, dpi_aware=True) -> (pill-free PIL 剩余)
实现为返回 (width, height, bytes_bgra)，交给 output 模块编码 PNG——
本模块只负责「抓像素」，不负责「存文件」（模块纪律：截图归截图）。

双腿策略：主路 ctypes GDI（单进程、无窗口闪烁）；PowerShell 兜底
（2026-10-27 实弹已验证 1920×1080）。主路任何异常自动降级兜底。

已知边界（照抄 DSH 实弹经验）：远程会话/服务态可能截出全黑帧——
is_all_black() 供上层检测并提示。
"""
import ctypes
import os
import subprocess
import sys
import time

U32 = ctypes.windll.user32
K32 = ctypes.windll.kernel32


def _dpi_aware():
    """进程级 DPI 感知（必须在首次 GetDC 前）：否则 125%/150% 缩放的
    机器上 GetSystemMetrics 返回缩放后尺寸、BitBlt 拉伸糊图。幂等。"""
    try:
        U32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 —— 老 Windows 无此 API 不致命
        pass


def list_screens():
    """枚举物理屏 -> [{"index", "left", "top", "w", "h", "primary"}]。"""
    _dpi_aware()
    screens = []

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    CB = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(RECT), ctypes.c_void_p)

    def on_monitor(_h, _dc, rect, _data):
        mi = MONITORINFO()
        mi.cb = ctypes.sizeof(MONITORINFO)
        U32.GetMonitorInfoW(_h, ctypes.byref(mi))
        r = mi.rcMonitor
        screens.append({"left": r.l, "top": r.t, "w": r.r - r.l,
                        "h": r.b - r.t,
                        "primary": bool(r.l == 0 and r.t == 0)})
        return 1

    cb = CB(on_monitor)   # v0.1.4：显式 argtypes 原型（windll 无原型时
    # 函数指针按 int 传=ArgumentError；v0.1.3 更漏调 API 本体）
    EnumDisp = U32.EnumDisplayMonitors
    EnumDisp.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CB, ctypes.c_void_p]
    EnumDisp.restype = ctypes.c_int
    EnumDisp(0, 0, cb, 0)
    for i, sc in enumerate(screens):
        sc["index"] = i
    return screens


def _shot_gdi(box):
    """主路：GDI BitBlt 抓 box=(l, t, w, h) -> (w, h, BGRA bytes)。"""
    _dpi_aware()
    l, t, w, h = box
    src = U32.GetDC(0)
    mem = U32.CreateCompatibleDC(src)
    bmi = ctypes.c_buffer(40)
    ctypes.windll.kernel32.RtlZeroMemory(bmi, 40)
    ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint32))[0] = 40  # biSize
    ints = ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))
    ints[1] = w
    ints[2] = -h                      # 负高=top-down
    ints[3] = 1                       # biPlanes
    ints[4] = 32                      # biBitCount
    BI_RGB = 0
    ints[5] = BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    old = U32.SelectObject(mem, U32.CreateCompatibleBitmap(src, w, h))
    ok = U32.BitBlt(mem, 0, 0, w, h, src, l, t, 0x00CC0020)   # SRCCOPY
    got = U32.GetDIBits(mem, U32.GetCurrentObject(mem, 7), 0, h,
                        buf, bmi, 0)  # 7=OBJ_BITMAP, DIB_RGB_COLORS
    U32.SelectObject(mem, old)
    U32.DeleteDC(mem)
    U32.ReleaseDC(0, src)
    if not ok or not got:
        raise OSError("GDI 抓屏失败（BitBlt/GetDIBits 返回 0）")
    return w, h, buf.raw


def _shot_ps(box):
    """兜底：PowerShell .NET CopyFromScreen（2026-10-27 实弹验证款）。"""
    _dpi_aware()
    l, t, w, h = box
    out = os.path.join(os.environ.get("TEMP", "."), "ashot_%d.png" % time.time_ns())
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b = New-Object System.Drawing.Bitmap %d, %d;"
        "$g = [System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen(%d, %d, 0, 0, $b.Size);"
        "$b.Save('%s');" % (w, h, l, t, out.replace("\\", "\\\\"))
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, timeout=60)
    with open(out, "rb") as fh:
        png = fh.read()
    os.unlink(out)
    return ("png", png)


def _virtual_box():
    _dpi_aware()
    return (U32.GetSystemMetrics(76), U32.GetSystemMetrics(77),
            U32.GetSystemMetrics(78), U32.GetSystemMetrics(79))  # SM_XV/YV/CV


def _screen_box(index):
    screens = list_screens()
    if not screens:
        raise RuntimeError("枚举不到任何显示器")
    if index >= len(screens):
        raise IndexError("只有 %d 块屏，没有第 %d 块" % (len(screens), index + 1))
    sc = screens[index]
    return (sc["left"], sc["top"], sc["w"], sc["h"])


def _win_box():
    _dpi_aware()
    hwnd = U32.GetForegroundWindow()
    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    rc = RECT()
    U32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.l, rc.t, rc.r - rc.l, rc.b - rc.t)


def shot(mode="full", screen=None, area=None):
    """截图唯一入口。

    mode: full=全虚拟桌面 | screen=单屏（screen=序号） |
          win=前台窗口 | area=区域（area=(l, t, w, h)）
    返回 dict：
      主路成功 -> {"kind": "raw", "w", "h", "bgra"}（交 output 编码 PNG）
      兜底成功 -> {"kind": "png", "png"}（已是 PNG 字节）
    """
    if mode == "full":
        box = _virtual_box()
    elif mode == "screen":
        box = _screen_box(int(screen or 0))
    elif mode == "win":
        box = _win_box()
    elif mode == "area":
        if not area or len(area) != 4:
            raise ValueError("area 需要 (left, top, width, height)")
        box = tuple(int(x) for x in area)
    else:
        raise ValueError("未知 mode：%r" % mode)
    if box[2] <= 0 or box[3] <= 0:
        raise ValueError("截图区域宽高必须为正：%r" % (box,))
    try:
        w, h, bgra = _shot_gdi(box)
        return {"kind": "raw", "w": w, "h": h, "bgra": bgra}
    except Exception:  # noqa: BLE001 —— 主路失败自动降级 PowerShell 兜底
        kind, payload = _shot_ps(box)
        return {"kind": kind, "png": payload}


def is_all_black(bgra, w, h, stride=4):
    """全黑帧检测（远程会话/服务态特征）：步进采样 256 点。"""
    step = max(1, (w * h) // 256) * stride
    data = bgra
    for i in range(0, min(len(data) - 1, step * 256), step):
        if data[i] or data[i + 1] or data[i + 2]:
            return False
    return True
