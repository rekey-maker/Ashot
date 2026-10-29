# -*- coding: utf-8 -*-
"""可选的真浏览器 E2E（v0.6.4）。

默认跳过；显式开：
    $env:ASHOT_E2E=1; python -m pytest tests/test_browser_e2e.py -q

不依赖 Playwright/Pillow：用本机 Edge/Chrome + 自家 cdp 客户端起一个
临时 profile，验证那些单元测试锁不住的浏览器行为（原生 range、快照
唯一性/密码掩码、scrollables、selector 标注）。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ashot import annotate, cdp, dom, output  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENABLED = os.environ.get("ASHOT_E2E") == "1"
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

pytestmark = pytest.mark.skipif(
    not ENABLED, reason="设置 ASHOT_E2E=1 才跑真浏览器 E2E")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def browser():
    exe = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if not exe:
        pytest.skip("本机没有 Edge/Chrome")
    port = _free_port()
    prof = tempfile.mkdtemp(prefix="ashot-e2e-", dir=os.path.join(ROOT, "tmp"))
    proc = subprocess.Popen(
        [exe, "--remote-debugging-port=%d" % port,
         "--user-data-dir=" + prof, "--no-first-run",
         "--no-default-browser-check", "--headless=new",
         "--window-size=1200,800", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        version = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/version" % port,
                        timeout=1) as r:
                    version = json.loads(r.read())
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.15)
        if not version:
            pytest.skip("浏览器调试端口没起来")
        yield {"port": port, "ws": version["webSocketDebuggerUrl"]}
    finally:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except Exception:  # noqa: BLE001
            proc.terminate()


def _page(browser, html):
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
    tid = cdp.call(browser["ws"], "Target.createTarget", {"url": url}, 15)["targetId"]
    try:
        for _ in range(60):
            for t in cdp.tabs(browser["port"]):
                if tid in t["ws"]:
                    time.sleep(0.25)
                    return t["ws"], tid
            time.sleep(0.1)
        raise RuntimeError("新标签页没出现")
    except Exception:
        cdp.call(browser["ws"], "Target.closeTarget", {"targetId": tid}, 5)
        raise


def _close(browser, tid):
    try:
        cdp.call(browser["ws"], "Target.closeTarget", {"targetId": tid}, 5)
    except Exception:  # noqa: BLE001
        pass


def test_native_range_drag(browser):
    ws, tid = _page(browser, "<body style='margin:0'><input id='r' type='range'"
                          " min='0' max='100' value='8' style='position:absolute;"
                          "left:100px;top:80px;width:300px;height:30px'></body>")
    try:
        r = dom.element_rect(ws, "#r")
        x0 = r["x"] + 0.08 * r["w"]
        x1 = r["x"] + 0.80 * r["w"]
        y = r["y"] + r["h"] / 2
        cdp.dispatch(ws, cdp.drag_events(x0, y, x1, y, steps=16, human=False),
                     realtime=False)
        time.sleep(0.2)
        val = cdp.call(ws, "Runtime.evaluate",
                       {"expression": "document.getElementById('r').value",
                        "returnByValue": True}, 5)["result"]["value"]
        assert int(val) >= 70, "原生 range 没被拖动：value=%r" % (val,)
    finally:
        _close(browser, tid)


def test_snapshot_unique_and_password_masked(browser):
    panel = ("<div><main><section><div><ul>"
             + "".join("<li><a id='%s'>%s</a></li>" % (x, x)
                       for x in ("a1", "a2"))
             + "</ul></div></section></main></div>")
    html = ("<body style='margin:0'><div>" + panel + "</div><div>" + panel
            + "</div><input id='pw' type='password' value='hunter2'>"
            + "</body>")
    ws, tid = _page(browser, html)
    try:
        rec = dom.snapshot(ws, max_nodes=200)
        for ref, info in rec["refs"].items():
            n = cdp.call(ws, "Runtime.evaluate",
                         {"expression": "document.querySelectorAll(%s).length"
                          % json.dumps(info["selector"]),
                          "returnByValue": True}, 5)["result"]["value"]
            assert n == 1, "选择器不唯一：%s -> %s" % (ref, info["selector"])
        pw = [v["text"] for v in rec["refs"].values() if v["tag"] == "input"]
        assert pw == [""], "密码不能进快照：%r" % (pw,)
    finally:
        _close(browser, tid)


def test_scrollables_overflow_filter(browser):
    html = ("<body style='margin:0'>"
            "<div id='h' style='height:50px;overflow:hidden'>"
            "<div style='height:500px'>h</div></div>"
            "<div id='s' style='height:100px;overflow:auto'>"
            "<div style='height:1000px'>s</div></div>"
            "<div id='v' style='height:50px;overflow:visible'>"
            "<div style='height:500px'>v</div></div></body>")
    ws, tid = _page(browser, html)
    try:
        rec = cdp.scrollables(ws)
        assert [x["id"] for x in rec] == ["s"], rec
        assert rec[0]["scroll_h"] == 1000 and rec[0]["client_h"] == 100
        assert rec[0]["selector"] and rec[0]["rect"]
    finally:
        _close(browser, tid)


def test_selector_annotation_hits_element(browser):
    html = ("<body style='margin:0'><button id='b' style='position:absolute;"
            "left:120px;top:80px;width:100px;height:40px'>B</button></body>")
    ws, tid = _page(browser, html)
    try:
        shot = cdp.shot(browser["port"], ws=ws, fullpage=False)
        png = shot[0] if isinstance(shot, tuple) else shot
        ops = dom.apply_selectors(ws, [{"kind": "rect", "selector": "#b",
                                        "width": 3, "color": "#FF0000"}])
        out = annotate.annotate_png(png, ops)
        w, h, px = annotate._decode_png(out)
        xs, ys = [], []
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 4
                if px[i] > 200 and px[i + 1] < 80 and px[i + 2] < 80:
                    xs.append(x); ys.append(y)
        assert xs and ys
        assert abs(min(xs) - 120) <= 3 and abs(min(ys) - 80) <= 3, (min(xs), min(ys))
    finally:
        _close(browser, tid)
