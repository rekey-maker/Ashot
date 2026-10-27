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


def list_families(filter=None):
    """已装字体族名列表（英文规范名，排序去重）。filter=不区分大小写
    子串过滤，同时命中英文名与本地化名（如 "kai"/"楷体" 都能查到
    KaiTi）；None=全量。名字保证可被 text op 的 font 字段解析
    （同源字库）。"""
    global _CACHE
    if _CACHE is None:
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
    if filter:
        p = str(filter).lower()
        return sorted({en for en, loc in _CACHE
                       if p in en.lower() or p in loc.lower()})
    return sorted({en for en, _ in _CACHE})
