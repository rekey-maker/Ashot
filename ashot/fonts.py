# -*- coding: utf-8 -*-
"""Ashot.fonts —— 已装字体族查询（v0.1.10）。

数据源同源原则：.NET InstalledFontCollection（PowerShell 枚举）——
与渲染器 _gdi_render.ps1 同引擎（System.Drawing），查出的族名保证
GDI+ 可解析；注册表/GDI 枚举会混入渲染器用不了的字体项，不作数。

locale 注记（实测 zh-CN）：FontFamily.Name 是 OS UI locale 敏感的
（楷体/KaiTi、微软雅黑/Microsoft YaHei）——故每族枚举双名（1033 英文
规范名 + 本地 Name），**输出英文名**（跨机稳定），过滤双语命中；
GetName(1033) 失败的族回退本地名。设计文档 §7.9。"""
import subprocess
import time

_PS = "\n".join([
    "$ErrorActionPreference = 'Stop'",
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
    "Add-Type -AssemblyName System.Drawing",
    "$c = New-Object System.Drawing.Text.InstalledFontCollection",
    "$c.Families | ForEach-Object {",
    "  $en = ''",
    "  try { $en = $_.GetName(1033) } catch { $en = '' }",
    "  if ($en) { '{0}{1}{2}' -f $en, [char]9, $_.Name } else { '{0}{1}{2}' -f $_.Name, [char]9, $_.Name }",
    "}",
])

_CACHE = None   # [(en_name, local_name)]，去重排序
_CACHE_AT = 0.0
_CACHE_TTL = 300.0   # 秒（v0.2.6 Q11：旧实现进程级永久——常驻 MCP 里
# 装/删字体永远看不见；5 分钟自动过期 + clear_cache() 手动失效）


def clear_cache():
    """手工失效字库缓存（CLI `fonts --refresh` / MCP refresh=true）。"""
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


def list_families(filter=None, refresh=False):
    """已装字体族名列表（英文规范名，排序去重）。filter=不区分大小写
    子串过滤，同时命中英文名与本地化名（如 "kai"/"楷体" 都能查到
    KaiTi——**前提是 OS 提供了本地名**：实测部分机器 .NET 的
    FontFamily.Name 也返回英文名，此时本地名过滤无命中，属数据边界
    非过滤器缺陷，见 §7.9.2 注记）；None=全量。refresh=True 强制
    重新枚举（绕缓存）。名字保证可被 text op 的 font 字段解析
    （同源字库）。"""
    global _CACHE, _CACHE_AT
    stale = (_CACHE is None or refresh or
             (time.time() - _CACHE_AT) > _CACHE_TTL)
    if stale:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", _PS],
            capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(
                "字体枚举失败（rc=%s）：%s" % (
                    r.returncode,
                    r.stderr.decode("utf-8", "replace").strip()[:200]))
        pairs = []
        for ln in r.stdout.decode("utf-8", "replace").splitlines():
            if not ln.strip():
                continue
            en, _, loc = ln.partition("\t")
            pairs.append((en.strip() or loc.strip(), loc.strip()))
        _CACHE = sorted(set(pairs))
        _CACHE_AT = time.time()
    if filter:
        p = str(filter).lower()
        return sorted({en for en, loc in _CACHE
                       if p in en.lower() or p in loc.lower()})
    return sorted({en for en, _ in _CACHE})
