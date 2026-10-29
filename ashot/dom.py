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
    text: (el.getAttribute("aria-label") || el.getAttribute("placeholder")
           || ((el.tagName.toLowerCase() === "input"
                && /^(button|submit|reset)$/i.test(el.type || ""))
               ? el.value : "")
           || (["input", "textarea", "select"].indexOf(
                el.tagName.toLowerCase()) >= 0 ? "" : el.innerText)
           || "").slice(0, 80),
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
                x: fr.left, y: fr.top, w: fr.width, h: fr.height,
                content_x: fr.left + (f.clientLeft || 0),
                content_y: fr.top + (f.clientTop || 0),
                content_w: f.clientWidth, content_h: f.clientHeight});
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
    text: (el.getAttribute("aria-label") || el.getAttribute("placeholder")
           || ((el.tagName.toLowerCase() === "input"
                && /^(button|submit|reset)$/i.test(el.type || ""))
               ? el.value : "")
           || (["input", "textarea", "select"].indexOf(
                el.tagName.toLowerCase()) >= 0 ? "" : el.innerText)
           || "").slice(0, 80),
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


def _intersect(a, b):
    """矩形交集 -> (x, y, w, h)（无交集返回 0 宽高）。"""
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[0] + a[2], b[0] + b[2])
    y1 = min(a[1] + a[3], b[1] + b[3])
    return (x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0))


def _clip_to_visible(ws, rec, containers, timeout=15):
    """把 frame 内元素的页面矩形与「主视口 ∩ 各层 iframe 内容框」求交，
    重算 in_viewport/visible_ratio（v0.2.8）——否则 iframe 外的部分被
    算成"可见"，点上去会打到别的元素。"""
    try:
        vp = _eval_raw(ws, "(() => ({vw: innerWidth, vh: innerHeight}))()",
                       timeout) or {}
    except Exception:  # noqa: BLE001
        vp = {}
    vw, vh = float(vp.get("vw") or 0), float(vp.get("vh") or 0)
    if vw <= 0 or vh <= 0:
        return rec
    clip = (0.0, 0.0, vw, vh)
    for c in containers or []:
        cx = c.get("content_x", c.get("x", 0))
        cy = c.get("content_y", c.get("y", 0))
        cw = c.get("content_w", c.get("w", 0))
        ch = c.get("content_h", c.get("h", 0))
        clip = _intersect(clip, (float(cx), float(cy), float(cw), float(ch)))
    ix, iy, iw, ih = _intersect((float(rec["x"]), float(rec["y"]),
                                 float(rec["w"]), float(rec["h"])), clip)
    area = max(1.0, float(rec["w"]) * float(rec["h"]))
    rec["visible_ratio"] = round(iw * ih / area, 4)
    rec["in_viewport"] = iw > 0 and ih > 0
    rec["clipped_by_frame"] = (iw * ih) < area - 0.5
    return rec


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
        return _clip_to_visible(ws, out, out.get("frame_chain") or [], timeout)
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


def _attach_oopif(s, frame_id):
    """跨站 iframe（OOPIF）：target id 实测等于 frameId；attach 成 flatten
    会话后命令带 sessionId 直达该进程。找不到/attach 失败返回 None。"""
    try:
        tg = s.command("Target.getTargets")
    except Exception:  # noqa: BLE001
        return None
    infos = tg.get("targetInfos") or []
    tid = None
    for t in infos:
        if t.get("type") == "iframe" and t.get("targetId") == frame_id:
            tid = t["targetId"]
            break
    if not tid:
        cands = [t for t in infos if t.get("type") == "iframe"]
        if len(cands) == 1:   # 只有一个 iframe target 时允许兜底
            tid = cands[0]["targetId"]
    if not tid:
        return None
    try:
        r = s.command("Target.attachToTarget",
                      {"targetId": tid, "flatten": True})
        return r.get("sessionId")
    except Exception:  # noqa: BLE001
        return None


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
        expr = ("(() => { const doc = document, win = window;"
                + (_RECT_BODY % json.dumps(str(selector))) + "})()")
        oopif = False
        try:
            w = s.command("Page.createIsolatedWorld",
                          {"frameId": frame_id, "worldName": "ashot-dom"})
            ctx = w.get("executionContextId")
            res = s.command("Runtime.evaluate", {
                "contextId": int(ctx), "returnByValue": True,
                "userGesture": True, "expression": expr})
        except Exception as e:  # noqa: BLE001 —— 跨站 OOPIF：frame 不在本进程
            sid = _attach_oopif(s, frame_id)
            if not sid:
                raise RuntimeError(
                    "oopif_unsupported：该 iframe 是跨站进程隔离帧，且 target "
                    "attach 失败；iframe 矩形=%r（%s）"
                    % (chain_hint or [ox, oy], str(e)[:120]))
            try:
                res = s.command("Runtime.evaluate", {
                    "returnByValue": True, "userGesture": True,
                    "expression": expr}, session_id=sid)
                oopif = True
            finally:
                try:
                    s.command("Target.detachFromTarget", {"sessionId": sid})
                except Exception:  # noqa: BLE001
                    pass
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
    if oopif:
        out["oopif"] = True
    chain = [{"selector": iframe_selector, "cross_origin": True,
              "x": ox, "y": oy, "w": content[2] - content[0],
              "h": content[7] - content[1],
              "content_x": ox, "content_y": oy,
              "content_w": content[2] - content[0],
              "content_h": content[7] - content[1]}]
    out["frame_chain"] = chain
    return _clip_to_visible(ws, out, chain, timeout)


_SNAPSHOT_JS = r"""
(() => {
  const MAX = Math.max(1, Math.min(500, %d));
  const MAXD = 12;
  const refs = {};
  let emitted = 0, n = 0, truncated = false;
  const clean = s => (s || "").trim().replace(/\s+/g, " ").slice(0, 80);
  const vis = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) return false;
    if (typeof el.checkVisibility === "function") {
      if (!el.checkVisibility({opacityProperty: true, visibilityProperty: true,
                               contentVisibilityAuto: true})) return false;
    } else {
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none"
          || parseFloat(cs.opacity || "1") === 0) return false;
    }
    return true;
  };
  const txt = el => {
    const tag = el.tagName.toLowerCase();
    const t = (el.getAttribute("type") || "").toLowerCase();
    const aria = el.getAttribute("aria-label") || el.getAttribute("alt")
      || el.getAttribute("placeholder") || el.getAttribute("title");
    if (aria) return clean(aria);
    if (tag === "input" && (t === "button" || t === "submit" || t === "reset"))
      return clean(el.value);
    if (tag === "input" || tag === "textarea" || tag === "select") return "";
    return clean(el.innerText);
  };
  const role = el => el.getAttribute("role") || el.tagName.toLowerCase();
  const interesting = el => {
    const t = el.tagName.toLowerCase();
    if (/^(a|button|input|select|textarea|summary|option|label)$/.test(t)) return true;
    if (el.getAttribute("role") || el.hasAttribute("onclick")
        || el.getAttribute("contenteditable") === "true") return true;
    return false;
  };
  const nth = cur => {
    let sel = cur.tagName.toLowerCase();
    const par = cur.parentElement;
    if (par) {
      const same = [...par.children].filter(c => c.tagName === cur.tagName);
      sel += ":nth-of-type(" + (same.indexOf(cur) + 1) + ")";
    }
    return sel;
  };
  const cssPath = el => {   // 全链 nth-of-type：正常 DOM 下唯一（不截断、不靠 id）
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      parts.unshift(nth(cur));
      if (cur === document.body) break;
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };
  const walk = (el, depth) => {
    if (depth > MAXD) { truncated = true; return null; }
    if (emitted >= MAX) { truncated = true; return null; }
    emitted += 1;
    const kids = [];
    for (const c of el.children) {
      if (emitted >= MAX) { truncated = true; break; }
      const k = walk(c, depth + 1);
      if (k) kids.push(k);
    }
    const name = txt(el);
    const show = interesting(el) || (kids.length === 0 && name);
    if (!show && !kids.length) return null;
    const node = {role: role(el), name: name, kids: kids, ref: null, box: null};
    if (show && vis(el)) {
      const r = el.getBoundingClientRect();
      const ref = "e" + (++n);
      node.ref = ref;
      node.box = [Math.round(r.left), Math.round(r.top),
                  Math.round(r.width), Math.round(r.height)];
      refs[ref] = {selector: cssPath(el), tag: el.tagName.toLowerCase(),
                   text: name, rect: node.box};
    }
    if (!node.ref && !kids.length) return null;
    return node;
  };
  const root = walk(document.body, 0);
  return {tree: root, refs: refs, count: n, truncated: truncated,
          url: location.href, title: document.title,
          dpr: window.devicePixelRatio,
          scroll: [window.scrollX, window.scrollY]};
})()
"""


def snapshot(ws, max_nodes=150, timeout=15):
    """页面结构快照（v0.6.0）：Playwright MCP 同思路——结构化树 + ref，
    不靠像素猜坐标。每个可见节点带 `[ref=eN] [box=x,y,w,h]`（视口 CSS
    像素）；refs 映射回**全链 nth-of-type 选择器**（正常 DOM 下唯一）。

    零依赖：纯 Runtime.evaluate，不碰 Accessibility 域，也不抓图。
    v0.6.1（审查）：节点预算独立于 ref 数（结构节点也计入），超了标
    `truncated`；不读 input/textarea 的 value（密码/隐私），只认
    aria-label/placeholder/alt/title；离屏/遮挡不算可见。
    """
    try:
        cap = int(max_nodes)
    except (TypeError, ValueError):
        raise ValueError("max_nodes 需要整数：%r" % (max_nodes,))
    cap = max(1, min(500, cap))
    js = _SNAPSHOT_JS % cap
    out = _eval_raw(ws, js, timeout)
    if not out:
        raise RuntimeError("页面快照为空")
    lines = []

    def fmt(node, depth):
        if not node:
            return
        indent = "  " * depth
        head = "%s- %s" % (indent, node.get("role") or "?")
        if node.get("name"):
            head += ' "%s"' % node["name"].replace('"', "'")
        if node.get("ref"):
            head += " [ref=%s]" % node["ref"]
        if node.get("box"):
            b = node["box"]
            head += " [box=%d,%d,%d,%d]" % tuple(b)
        lines.append(head)
        for k in node.get("kids") or []:
            fmt(k, depth + 1)

    fmt(out.get("tree"), 0)
    tree = "\n".join(lines)
    truncated = bool(out.get("truncated"))
    if len(tree) > 200000:          # 极端页面兜底：别把上下文撑爆
        tree = tree[:200000] + "\n…（截断）"
        truncated = True
    return {"tree": tree, "refs": out.get("refs") or {},
            "count": int(out.get("count") or 0),
            "truncated": truncated,
            "url": out.get("url"), "title": out.get("title"),
            "dpr": out.get("dpr"), "scroll": out.get("scroll")}


def apply_selectors(ws, ops, refs=None, timeout=15, space="viewport"):
    """把 ops 里的 `selector`/`ref` 解析成像素坐标（v0.6.0）。

    - selector：CSS 选择器，实时取 element_rect（准，不靠猜）；
    - ref：snapshot 返回的 eN，经 refs 映射回 selector 再实时取；
    - 矩形族（rect/ellipse/mosaic/blur/spotlight/smarterase）填
      x/y/w/h（CSS×dpr=物理像素）；text 填左上角；
      箭头/直线请直接用坐标（两端元素语义没定，不猜）；
    - `pad`（可选）：向外扩的物理像素数（矩形族）；
    - `space`：`viewport`（默认，视口截图）或 `document`（整页截图，
      自动加 scroll×dpr 偏移）。
    v0.6.1（审查）：解析过的 op 标 `__resolved__`，全局 dpr 不再二次乘。
    """
    if space not in ("viewport", "document"):
        raise ValueError("space 只能是 viewport/document：%r" % (space,))
    out = []
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("op 需要对象：%r" % (op,))
        sel = op.get("selector")
        ref = op.get("ref")
        if ref:
            if refs is None:
                raise ValueError(
                    "ref 仅 MCP 同连接可用（CLI 无快照缓存）；"
                    "CLI 请用 selector 或坐标，或改用 MCP")
            info = (refs or {}).get(str(ref))
            if not info:
                raise ValueError("ref 已过期或不存在（请重新 snapshot）：%r"
                                 % (ref,))
            sel = info.get("selector")
        if not sel:
            out.append(op)
            continue
        rect = element_rect(ws, sel, timeout=timeout)
        k = float(op.get("dpr") or rect.get("dpr") or 1.0)
        ox = oy = 0.0
        if space == "document":
            ox = float(rect.get("scroll_x") or 0) * k
            oy = float(rect.get("scroll_y") or 0) * k
        kind = op.get("kind")
        o = dict(op)
        o.pop("selector", None)
        o.pop("ref", None)
        o.pop("dpr", None)
        if kind in ("rect", "ellipse", "mosaic", "blur", "spotlight",
                    "smarterase"):
            pad = float(o.pop("pad", 0) or 0)
            o["x"] = rect["x"] * k - pad + ox
            o["y"] = rect["y"] * k - pad + oy
            o["w"] = rect["w"] * k + pad * 2
            o["h"] = rect["h"] * k + pad * 2
        elif kind == "text":
            o["x"] = rect["x"] * k + ox
            o["y"] = rect["y"] * k + oy
        else:
            raise ValueError("selector/ref 只支持矩形族与 text；"
                             "%r 请直接用坐标" % (kind,))
        o["__resolved__"] = True
        out.append(o)
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
