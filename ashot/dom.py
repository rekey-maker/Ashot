# -*- coding: utf-8 -*-
"""Ashot.dom —— 元素矩形与 iframe 坐标映射（v0.2.7，通用 DOM 原语）。

Ashot 不做验证码；这里只回答两个**通用**问题：
  「这个元素在屏幕上的 CSS 矩形在哪、看不看得见」→ element_rect
  「它在一个 iframe 里，换算到主页面坐标是多少」→ frame_element_rect

调研结论（2026-10-29）：
  · Element.checkVisibility() 2024-03 起 Baseline，选项
    opacityProperty/visibilityProperty/contentVisibilityAuto；它**不检查**
    视口外/被遮挡 → 视口交集合自己算，遮挡用 elementFromPoint(中心)。
  · DOM.getBoxModel 返回**主框架视口坐标**的 CSS 像素（实测主页面滚动
    300px 后同一 iframe 的 y 从 500→200），content 四点是去掉 border 的
    内容框 → iframe 内容原点就用它，天然正确。
  · DOM.describeNode 对 iframe 节点返回 frameId，与 Page.getFrameTree
    一致；Page.createIsolatedWorld(frameId) 能在**跨域**（同进程）frame
    里求值 → 跨域 iframe 单层可映射。
  · 跨站 OOPIF 不在主会话的 childFrames 里（需要 Target 会话），本版
    如实报 oopif_unsupported 并给出 iframe 自身矩形，不静默。

契约：所有坐标都是**主页面视口 CSS 像素**（与 cdp-click 的入参一致）；
截图坐标要先乘 to_css，别混用。
"""
import json

from . import cdp

_RECT_BODY = r"""
  const el = doc.querySelector(%s);
  if (!el) return {found: false, error: "selector not found"};
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  let vis = null, visSrc = "checkVisibility";
  if (typeof el.checkVisibility === "function") {
    vis = el.checkVisibility({opacityProperty: true, visibilityProperty: true,
                              contentVisibilityAuto: true});
  } else {
    visSrc = "fallback";
    vis = !!(el.offsetParent || r.width || r.height)
          && cs.visibility !== "hidden"
          && parseFloat(cs.opacity || "1") > 0;
  }
  const cx0 = r.left + r.width / 2, cy0 = r.top + r.height / 2;
  let occluded = false;
  if (r.width > 0 && r.height > 0) {
    const hit = doc.elementFromPoint(cx0, cy0);
    occluded = !!(hit && hit !== el && !el.contains(hit));
  }
  const vw = win.innerWidth, vh = win.innerHeight;
  const ix = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
  const iy = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
  const area = Math.max(1, r.width * r.height);
  return {found: true, tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.value || "").slice(0, 80),
    local_x: r.left, local_y: r.top, w: r.width, h: r.height,
    visible: !!vis, visibility_source: visSrc,
    in_viewport: ix > 0 && iy > 0,
    visible_ratio: Math.round((ix * iy) / area * 10000) / 10000,
    occluded: occluded, pointer_events: cs.pointerEvents,
    dpr: win.devicePixelRatio, scroll_x: win.scrollX, scroll_y: win.scrollY,
    doc_scroll_h: doc.documentElement ? doc.documentElement.scrollHeight : 0};
"""

_SAME_ORIGIN_JS = r"""
(() => {
  let doc = document, win = window, offX = 0, offY = 0;
  const chain = [];
  const frames = %s;
  for (const sel of frames) {
    let f = null;
    try { f = doc.querySelector(sel); } catch (e) { return {found:false, error:"bad iframe selector"}; }
    if (!f) return {found:false, error:"iframe not found: " + sel, chain};
    const fr = f.getBoundingClientRect();
    chain.push({selector: sel, cross_origin: false,
                x: fr.left, y: fr.top, w: fr.width, h: fr.height});
    offX += fr.left + (f.clientLeft || 0);
    offY += fr.top + (f.clientTop || 0);
    let cd = null;
    try { cd = f.contentDocument; } catch (e) { cd = null; }
    if (!cd) return {found:false, cross_origin: true, chain,
                     error:"cross-origin iframe（走 CDP 分支）"};
    doc = cd;
    win = f.contentWindow || win;
  }
  const el = doc.querySelector(%s);
  if (!el) return {found:false, error:"selector not found in frame", chain};
  const r = el.getBoundingClientRect();
  const cs = win.getComputedStyle(el);
  let vis = null, visSrc = "checkVisibility";
  if (typeof el.checkVisibility === "function") {
    vis = el.checkVisibility({opacityProperty: true, visibilityProperty: true,
                              contentVisibilityAuto: true});
  } else {
    visSrc = "fallback";
    vis = !!(el.offsetParent || r.width || r.height)
          && cs.visibility !== "hidden" && parseFloat(cs.opacity || "1") > 0;
  }
  const cx0 = r.left + r.width / 2, cy0 = r.top + r.height / 2;
  let occluded = false;
  if (r.width > 0 && r.height > 0) {
    const hit = doc.elementFromPoint(cx0, cy0);
    occluded = !!(hit && hit !== el && !el.contains(hit));
  }
  const vw = win.innerWidth, vh = win.innerHeight;
  const ix = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
  const iy = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
  const area = Math.max(1, r.width * r.height);
  return {found: true, tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.value || "").slice(0, 80),
    local_x: r.left, local_y: r.top,
    x: r.left + offX, y: r.top + offY,
    cx: cx0 + offX, cy: cy0 + offY, w: r.width, h: r.height,
    visible: !!vis, visibility_source: visSrc,
    in_viewport: ix > 0 && iy > 0,
    visible_ratio: Math.round((ix * iy) / area * 10000) / 10000,
    occluded: occluded, pointer_events: cs.pointerEvents,
    dpr: win.devicePixelRatio, scroll_x: win.scrollX, scroll_y: win.scrollY,
    cross_origin: false, frame_chain: chain};
})()
"""


def _eval_raw(ws, expression, timeout=15, context_id=None, await_promise=False):
    """Runtime.evaluate 原始调用（**不走 cdp.evaluate 的自动 IIFE 包装**——
    我们的表达式本身就是 IIFE，再包一层会把返回值吃掉）。"""
    params = {"expression": expression, "returnByValue": True,
              "awaitPromise": bool(await_promise), "userGesture": True}
    if context_id is not None:
        params["contextId"] = int(context_id)
    res = cdp.call(ws, "Runtime.evaluate", params, timeout)
    exc = res.get("exceptionDetails")
    if exc:
        desc = ((exc.get("exception") or {}).get("description")
                or exc.get("text") or str(exc)[:200])
        raise RuntimeError("页面求值异常：%s" % desc[:300])
    return (res.get("result") or {}).get("value")


def element_rect(ws, selector, scroll=False, timeout=15):
    """元素在**视口**里的 CSS 矩形 + 可见性/视口/遮挡/pointer-events。

    scroll=True：先 scrollIntoView({block:"center"}) 等两帧再量。
    选择器不存在 → RuntimeError（零静默）。
    """
    sel = json.dumps(str(selector))
    if scroll:
        js = ("(%s)()" % ("() => new Promise(res => {"
              " const el = document.querySelector(%s);"
              " if (!el) { res({found:false}); return; }"
              " el.scrollIntoView({block:'center', inline:'center'});"
              " requestAnimationFrame(() => requestAnimationFrame("
              "   () => res({found:true}))); })" % sel))
        _eval_raw(ws, js, timeout, await_promise=True)
    js = ("(() => { const doc = document, win = window;"
          + (_RECT_BODY % sel) + "})()")
    out = _eval_raw(ws, js, timeout)
    if not out or not out.get("found"):
        raise RuntimeError("元素未找到或不可测：%r（%s）"
                           % (selector, (out or {}).get("error", "?")))
    out["x"] = out.pop("local_x")
    out["y"] = out.pop("local_y")
    out["cx"] = out["x"] + out["w"] / 2.0
    out["cy"] = out["y"] + out["h"] / 2.0
    return out


def frame_element_rect(ws, iframe_selectors, selector, timeout=15):
    """iframe 内元素 → 主页面视口 CSS 矩形。

    iframe_selectors：字符串（单层）或字符串列表（同源嵌套）。
    同源：主文档 JS 递归内容文档（一次求值，最快）；
    跨域（同进程）：DOM.describeNode→frameId→createIsolatedWorld 子 frame
    求值 + getBoxModel 内容框原点相加；
    OOPIF（跨站）：如实抛 oopif_unsupported，错误里带 iframe 自身矩形。
    """
    sels = ([iframe_selectors] if isinstance(iframe_selectors, str)
            else list(iframe_selectors))
    if not sels:
        raise ValueError("iframe_selectors 不能为空")
    js = _SAME_ORIGIN_JS % (json.dumps(sels), json.dumps(str(selector)))
    out = _eval_raw(ws, js, timeout)
    if out and out.get("found"):
        return out
    # 同源失败：跨域单层走 CDP（嵌套跨站不在本版范围）
    if len(sels) != 1:
        raise RuntimeError("嵌套跨域 iframe 暂不支持（本版只做单层跨域）：%r"
                           % (out or {}).get("error"))
    try:
        return _cross_origin_rect(ws, sels[0], selector, timeout,
                                  out.get("chain") or [])
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001 —— 转成可读错误，带 iframe 信息
        raise RuntimeError("跨域 iframe 映射失败（%s: %s）；iframe 链：%r"
                           % (type(e).__name__, str(e)[:160],
                              (out or {}).get("chain")))


def _cross_origin_rect(ws, iframe_selector, selector, timeout, chain_hint):
    """跨域同进程：**一个 Session 里做完**（DOM 节点 id 是会话级的——
    分多次 cdp.call 每次新建连接，nodeId 到下一个会话就失效，实测报
    "Could not find node with given id"）。DOM.enable 只开 DOM 域，
    不碰 Runtime.enable（字节系检测红线）。"""
    with cdp.Session(ws, timeout) as s:
        s.command("DOM.enable")
        doc = s.command("DOM.getDocument", {"depth": 0})
        root = (doc.get("root") or {}).get("nodeId")
        if not root:
            raise RuntimeError("DOM.getDocument 无 root")
        q = s.command("DOM.querySelector",
                      {"nodeId": root, "selector": iframe_selector})
        node_id = q.get("nodeId") or 0
        if not node_id:
            raise RuntimeError("主文档找不到 iframe：%r" % iframe_selector)
        desc = s.command("DOM.describeNode", {"nodeId": node_id})
        frame_id = (desc.get("node") or {}).get("frameId")
        box = s.command("DOM.getBoxModel", {"nodeId": node_id})
        content = ((box.get("model") or {}).get("content") or [])
        if len(content) < 8:
            raise RuntimeError("iframe 没有可见内容框（display:none?）")
        ox, oy = content[0], content[1]
        if not frame_id:
            raise RuntimeError("iframe 没有独立 frameId（同源？CDP 分支不适用）")
        try:
            w = s.command("Page.createIsolatedWorld",
                          {"frameId": frame_id, "worldName": "ashot-dom"})
            ctx = w.get("executionContextId")
        except Exception as e:  # noqa: BLE001 —— OOPIF 典型症状
            raise RuntimeError(
                "oopif_unsupported：该 iframe 是跨站进程隔离帧，需要 Target 会话；"
                "iframe 矩形=%r（%s）" % (chain_hint or [ox, oy], str(e)[:120]))
        res = s.command("Runtime.evaluate", {
            "contextId": int(ctx), "returnByValue": True, "userGesture": True,
            "expression": "(() => { const doc = document, win = window;"
                          + (_RECT_BODY % json.dumps(str(selector)))
                          + "})()"})
        exc = res.get("exceptionDetails")
        if exc:
            raise RuntimeError("跨域 frame 求值异常：%s"
                               % str(exc)[:200])
        out = (res.get("result") or {}).get("value")
    if not out or not out.get("found"):
        raise RuntimeError("跨域 frame 内找不到元素：%r" % selector)
    out["x"] = out.pop("local_x") + ox
    out["y"] = out.pop("local_y") + oy
    out["cx"] = out["x"] + out["w"] / 2.0
    out["cy"] = out["y"] + out["h"] / 2.0
    out["cross_origin"] = True
    out["frame_chain"] = [{"selector": iframe_selector, "cross_origin": True,
                           "x": ox, "y": oy}]
    return out


def frames(ws, timeout=15):
    """frame 树（id/url/name/parent/depth），并尽力附上 iframe 自身矩形。"""
    out = []

    def walk(node, depth, parent):
        f = node.get("frame") or {}
        item = {"id": f.get("id"), "url": (f.get("url") or "")[:300],
                "name": f.get("name") or "", "parent_id": parent,
                "depth": depth}
        out.append(item)
        for ch in (node.get("childFrames") or []):
            walk(ch, depth + 1, f.get("id"))

    with cdp.Session(ws, timeout) as s:
        s.command("DOM.enable")
        tree = s.command("Page.getFrameTree")
        walk((tree.get("frameTree") or {}), 0, None)
        # 尽力补 iframe 矩形（同一会话；OOPIF 会失败→留空，不静默编造）
        for item in out:
            if not item["depth"]:
                continue
            try:
                own = s.command("DOM.getFrameOwner", {"frameId": item["id"]})
                b = s.command("DOM.getBoxModel",
                              {"backendNodeId": own.get("backendNodeId")})
                c = ((b.get("model") or {}).get("content") or [])
                if len(c) >= 8:
                    item["rect"] = {"x": c[0], "y": c[1],
                                    "w": c[2] - c[0], "h": c[7] - c[1]}
            except Exception:  # noqa: BLE001 —— 矩形是附加项
                pass
    return out
