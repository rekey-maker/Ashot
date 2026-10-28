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

if sys.platform == "win32":
    U32 = ctypes.windll.user32
    G32 = ctypes.windll.gdi32   # BitBlt/CreateCompatibleDC 等 GDI 族在
    # gdi32——v0.1.5 实锤：曾全部挂 user32（无该导出）→ 主路自 v0.1.0
    # 起每次必抛 AttributeError 静默降级 PS 兜底，GDI 路从未真正跑过
else:   # v0.2.0 导入守卫（审计 P1-1）：非 Windows 上本模块仅提供
    # 兜底路/枚举的 platform 分流，windll 不存在——顶层访问会让
    # cli/mcp 连 cdp 等跨平台命令都起不来
    U32 = G32 = None


def _dpi_aware():
    """进程级 DPI 感知（必须在首次 GetDC 前）：否则 125%/150% 缩放的
    机器上 GetSystemMetrics 返回缩放后尺寸、BitBlt 拉伸糊图。幂等。"""
    try:
        U32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 —— 老 Windows 无此 API 不致命
        pass


def list_screens():
    """枚举物理屏 -> [{"index", "left", "top", "w", "h", "primary"}]。"""
    if sys.platform != "win32":
        # v0.2.0（审计 P2-2）：非 Win 如实报，不裸 AttributeError
        raise RuntimeError("显示器枚举暂不支持平台 %r（Mac 属批2）"
                           % sys.platform)
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

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    src = U32.GetDC(0)
    mem = G32.CreateCompatibleDC(src)
    hbm = G32.CreateCompatibleBitmap(src, w, h)
    old = G32.SelectObject(mem, hbm)
    ok = G32.BitBlt(mem, 0, 0, w, h, src, l, t, 0x00CC0020)   # SRCCOPY。
    # 刻意不加 CAPTUREBLT(0x40000000)：加上分层窗口可入图，但每次调用
    # 都会引发光标闪烁——高频截图工具的取舍，声明于此
    bmi = BITMAPINFOHEADER()   # 手撸偏移版曾把 biPlanes/biBitCount 挤进同
    # 一个 int（biBitCount=0、biCompression=32 非法）→ GetDIBits 恒 0：
    # GDI 主路带病两层（挂错 DLL + bmi 头坏），v0.1.5 探针实锤
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h          # 负高 = top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0      # BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    G32.SelectObject(mem, old)   # GetDIBits 硬规则：位图不得选在 DC 里
    got = G32.GetDIBits(mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)
    G32.DeleteObject(hbm)   # v0.1.5 P1：位图句柄必须删——长驻 MCP 进程
    # 每截一张漏 1 个 GDI 对象，约万张触满配额后主路永久报废
    G32.DeleteDC(mem)
    U32.ReleaseDC(0, src)
    if not ok or not got:
        raise OSError("GDI 抓屏失败（BitBlt=%s GetDIBits=%s）" % (ok, got))
    raw = bytearray(buf.raw)
    raw[3::4] = b"\xff" * (w * h)   # BI_RGB 32bpp 的 alpha 字节未定义（实测
    # 常为 0）——透传会编码出全透明 PNG，桌面抓屏一律按不透明处理
    return w, h, bytes(raw)


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
        # PowerShell 单引号串不处理反斜杠转义，唯一要转义的是撇号本身
        "$b.Save('%s');" % (w, h, l, t, out.replace("'", "''"))
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, capture_output=True, timeout=60)
        with open(out, "rb") as fh:
            png = fh.read()
    finally:
        try:
            os.unlink(out)   # 阅读失败/PS 失败都不残留临时文件
        except OSError:
            pass
    return ("png", png)


def _virtual_box():
    _dpi_aware()
    return (U32.GetSystemMetrics(76), U32.GetSystemMetrics(77),
            U32.GetSystemMetrics(78), U32.GetSystemMetrics(79))  # SM_XV/YV/CV


def _screen_box(index):
    screens = list_screens()
    if not screens:
        raise RuntimeError("枚举不到任何显示器")
    if index < 0:
        raise IndexError("屏序号从 0 起，不接受负数：%d" % index)
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
    if sys.platform != "win32":
        # v0.2.0：桌面捕获路 Windows 专属——非 Win 平台如实报（Mac
        # 捕获路 capture_mac 属批2；cdp 等跨平台命令不受此影响）
        raise RuntimeError(
            "桌面截图暂不支持平台 %r（Mac 捕获路规划中，见设计文档 v0.2.0 批2）"
            % sys.platform)
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
