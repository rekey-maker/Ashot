# 更新日志（Changelog）

所有显著变更记录于此。格式参考 Keep a Changelog，版本号遵循 SemVer。

## [0.6.1] - 2026-10-29

### 审查修复（v0.6.0 两路子 agent 只读审查）
- **P0 cssPath 不唯一/被截断**：旧实现超过 6 层直接 break、不用 body 锚点，
  深层重复结构下 `querySelector` 会命中另一个面板的同类元素（静默标错）。
  改为**全链 `nth-of-type`（锚到 body）**；真机深链双面板实测每个 ref 的
  选择器 `querySelectorAll(...).length == 1`。
- **P1 密码明文进快照**：`txt()` 旧实现先取 `el.value`，无 aria-label 的
  password 框会把明文写进 tree/refs。现在 input/textarea/select 一律不读
  value（按钮类除外），只认 aria-label/placeholder/alt/title；
  `element_rect` 的 text 同步收紧。真机 `value="hunter2"` → 快照 text 为空。
- **P1 selector + dpr 双重缩放**：`apply_selectors` 已乘页面 dpr，全局
  `dpr`/`scale_ops` 又乘一次（1.5→2.25）。解析过的 op 标 `__resolved__`，
  `scale_ops` 跳过；并移除 op 里的 dpr 键。
- **P1 整页截图与视口坐标混用**：新增 `space="viewport"|"document"`
  （CLI `--space`），document 自动加 `scroll×dpr`；真机滚动 500 后
  b2 视口 y=-412、document y=88。
- **CLI 的 ref 是死路**：CLI 无跨进程快照缓存，现在明确报
  「ref 仅 MCP 同连接可用」；CLI 文档/帮助改为 selector 或坐标。
- **snapshot 体积**：节点预算独立于 ref 数（结构节点也计数），超限标
  `truncated`；`max_nodes` 夹在 1~500；输出 >200k 字符兜底截断。
- **ref 过期**：`_LAST_REFS` 存 url/scroll，annotate 时比对 `location.href`，
  导航后报「ref 已过期」。
- 文档：README 工具清单补 `ashot_snapshot`、计数/版本修正；SKILL 工具数
  23、ref 仅 MCP。

### 测试
- **176 项全绿**（新增 5：resolved 不二次 dpr、document 偏移、CLI ref 拒绝、
  snapshot truncated、超高图 to_source）。

## [0.6.0] - 2026-10-29

### 新增（MCP 精确定位，对齐 Playwright MCP 的 ref 思路）
- **`ashot_snapshot` / CLI `snapshot`**：页面结构快照——结构化树 + `[ref=eN]`
  + `[box=x,y,w,h]`（视口 CSS 像素），ref 映射回 CSS 选择器。纯
  `Runtime.evaluate`，零依赖、不抓图、不碰 Accessibility 域。
- **`annotate` 的 ops 支持 `selector` / `ref`**：矩形族与 text 直接按元素
  定位（CSS×dpr=截图物理像素），`pad` 可外扩；不再靠模型从缩略图猜坐标。
  CLI 加 `--port/--index/--ws`，MCP `ashot_annotate` 同名参数。
- **预览收据带 `src` / `to_source`**：模型看预览图后可用 `to_source`
  把预览坐标换算回源图（此前只有 width/height，换算靠猜）。

### 调研依据（2026-10-29）
- **Playwright MCP**：用 accessibility snapshot 的 `ref` 指代元素，点击/输入
  都接收 ref，明确"比截图更准"；其 README 也承认 CLI+Skills 对编码 agent
  更省 token。本版采用同样的"结构化元素"路线（Ashot 用 DOM 快照）。
- **OmniParser**（微软，MIT）：纯视觉检测 UI 元素；需要模型权重/推理依赖，
  与 Ashot 零依赖红线冲突，仅作纯视觉场景参考。
- **Set-of-Mark**：在元素上叠加编号，提升视觉模型的定位准确率；适合无 DOM
  的桌面/Canvas，列入后续（`ashot_marks`）。
- **Chrome DevTools MCP / browser-use**：前者全量 DevTools；后者 DOM 索引 +
  视觉混合。均说明"DOM 结构 + 元素 id"是精度与成本的最优解。

### 测试
- **171 项全绿**（新增 3：快照树/refs、selector/ref 解析与 pad、预览
  `to_source`）；真机（Edge）验证：`snapshot` 输出
  `button "提交" [ref=e1] [box=120,80,100,40]`，`annotate` 用
  `selector:"#btn"` 画框 bbox=(119,79)-(221,121)。

## [0.5.1] - 2026-10-29

### 审查修复（v0.5.0 两路子 agent 只读审查）
- **P1 dpr 对字符串坐标 / `area` 别名静默不缩放**：`scale_ops` 现在处理
  数字字符串与 `area`/`coords` 逗号串；`coords` 输出小数串，`annotate._nums`
  与 `vector._nums` 改 float 解析（旧 `int("15.66")` 直接崩）。
- **P1 `info` 对非 PNG/JPEG 静默返回 0×0 且 exit 0**：改为明确报错、退出码 1。
- **P1 MCP `ashot_annotate.dpr` 被声明成 integer**：改 `0.0` → `number`，
  工具描述补 dpr 语义（只缩放坐标，字号/线宽不变；text 的 `w` 也会缩放）。
- **`annotate` 无 ops/template 静默输出原图副本**：改为报错。
- **`--template` 对象缺 `ops` 键静默变空模板**：改为报错；模板在前、内联
  在后（设计文档写明）。
- **`resize --dir` 重跑留陈图**：只对同批去重，重跑覆盖旧产物；`--dir` 与
  `--out` 互斥、单图 `--out-dir` 报错；非法尺寸进批前校验一次。
- **`--clip` 提示打到 stdout**：改 stderr（stdout 只留路径）。
- 文档：README 版本/命令数/测试数（118/30/19）与 0.4.0 旧行、MCP 表补
  eval/view；CLI `--help` 的「只吃 PNG」；SKILL「完全同能力」；设计索引排序。

### 测试
- **168 项全绿**（新增/加强：dpr 像素 bbox 实测、area/字符串坐标缩放、
  info 非图报错、模板数组/对象/坏格式、无 ops 报错、批量失败不中断、
  重跑覆盖、同名不同宽高比）。

## [0.5.0] - 2026-10-29

### 新增（补 imgtool 对比后剩下的便利性缺口）
- **JPEG 输入**：`annotate`/`hash`/`diff`/`compose --src` 现在都吃 PNG **和**
  JPEG——用已有 GDI+ 转码路（`ashot/imageio.py`）解成 PNG 再进纯 Python
  解码器；不再出现「自己 `--jpg` 产的文件自己读不了」。
- **`annotate --dpr`**：ops 坐标按 devicePixelRatio 缩放（CSS→物理像素），
  与 `element` 返回的 CSS 矩形直接闭环；只缩放坐标，不缩放字号/线宽。
- **`annotate --template`**：模板 JSON（ops 数组或 `{"ops": […]}`）与内联
  ops 合并，常用标注可复用。
- **`info` 命令**：PNG/JPEG 的 `{format,w,h,bytes,path}`（JSON）。
- **`resize --dir/--out-dir`**：目录批处理（只收 .png/.jpg/.jpeg），单张
  失败不拖垮整批；同名不同扩展自动加 `-2` 后缀，不互相覆盖。
- **MCP**：`ashot_annotate` 增加 `dpr`。

### 修复
- **transform 的 JPEG 冒充 PNG**（审查发现）：`apply(jpeg, fmt="png")` 在无
  裁切/缩放时走「原样返回」快路径，会把 JPEG 字节当 PNG 交付（扩展名
  .png、内容 JPEG）。现在快路径要求源本身是 PNG。
- 批处理同名冲突：`a.png` 与 `a.jpg` 都输出 `a.png` 会互相覆盖，改为
  `a-2.png`。

### 测试
- 新增 7 项：JPEG→PNG 归一化、passthrough 修复、`scale_ops`、CLI
  annotate JPEG+dpr、CLI hash JPEG、CLI info、CLI resize 批处理。
  全套 **167 项**通过。

## [0.4.2] - 2026-10-29

### 开源
- 新增 **MIT LICENSE**（© 2026 rekey-maker）：可自由使用、修改、分发、
  商用，保留版权与许可声明即可。
- README 增加「许可证」段并在版本行标注 MIT 开源；版本 0.4.2。
- 说明：本版**无代码变更**（功能同 0.4.1，160 项测试），只为开源许可
  与发布补一版。

## [0.4.1] - 2026-10-29

### 新增（矢量曲线/弧线/折线）
- **`curve`**（三次贝塞尔，`x0,y0,c1x,c1y,c2x,c2y,x1,y1`）、**`arc`**
  （椭圆弧 `x,y,w,h,start,sweep`，度、顺时针）、**`polyline`**
  （`points` 或 `coords`）。与箭头同一条原理：**几何在 Python 采样成
  点列 → GDI+ 抗锯齿描边**（不是像素硬边），像素降级路复用同一套采样。
- 新模块 `ashot/geometry.py`（纯数学，可单测）：贝塞尔按控制多边形长度
  自适应采样（16~128 段）、弧线按 ~2°/段（8~180 段）。
- 三种写法都认：显式键 / `points=[[x,y],…]` / `coords="x1,y1,…"`；
  曲线与弧线同样进 `bounds_warn`（bbox 由采样点算）。
- 采样密度依据：Microsoft Learn《Graphics.DrawBezier / DrawArc》——
  GDI+ 内部同样把曲线展平成折线；DrawArc 的角度制/顺时针/start+sweep
  与我们的参数方程一致。

### 线宽（width）收口
- 小数线宽两路对齐：像素降级路旧实现 `int()` 截断（1.9 → 1px，矢量
  3px；3.6 → 3px vs 5px），改为四舍五入，实测 0.8/1.9/2.5/3.6/6.4/20
  六档两路差 ≤1px。
- 非法线宽报错：`width <= 0`（旧实现像素路静默零输出）或 `>1000`
  （像素路按 width//2 循环，过大等于 DoS）一律 ValueError。
- 新增 2 项测试：七种描边原语都透传 width（箭头为 fill，粗细看多边形
  跨度）；小数宽度两路一致 + 非法值拒绝。

### 审查修复（子 agent 只读审查，2026-10-29）
- **P1**：有限但超范围的坐标（如 1e308）会在采样里派生 inf → JSON `Infinity` → PS 失败降级 → `int(round(inf))` 抛 OverflowError。现在 `geometry._finite` 统一限制 `|v| ≤ 1e7`，`bezier_points`/`arc_points` 入口自校验（含 NaN sweep 不再被 min/max 静默夹成 360°）。
- **P2**：像素降级路先做 Cohen–Sutherland 线段裁剪（`clip_segment`），画布外的远点不再白跑百万步 Bresenham。
- **测试补强**（原三条是假绿）：弧 720° 夹取改用默认步数（181 点、首尾重合）；抗锯齿测试改为「弧顶出墨 + 弦中点必须背景」（能区分曲线与弦）；新增 `test_both_paths_share_sampling`（monkeypatch 计数，锁死两路共用同一套采样）。
- 审查另报的「降级路 stroke 无 bbox → 越界静默」经复测**不成立**：`_shape_boxes` 本就按采样点算 stroke 的 bbox，降级路照样产出 `bounds_warn`（已加实测）。

### 测试
- 新增 `tests/test_shapes.py` 19 项（端点/对称/方向/夹取/三种写法/
  抗锯齿中间色/像素路同图/越界告警/CLI 端到端）。全套 **160 项**通过。

## [0.4.0] - 2026-10-29

### 新增（裁切 / 缩放 / JPEG 交付，补 `图片标注工具/` 的缺口）
- **`ashot/transform.py`**：裁切 + 缩放 + 编码一条流水线（`apply()`），
  纯函数 `normalize_crop`/`plan_size`/`png_size`/`default_out` 可单测。
- **`ashot/_gdi_image.ps1`**：系统 .NET GDI+ 执行（裁 → HighQualityBicubic
  缩放 → PNG/JPEG），纯 ASCII 纪律；**不引入 PIL**，失败如实报错不静默降级。
- **CLI**：`crop <png> --box x,y,w,h [--scale|--width|--max-side] [--dpr K]
  [--jpg Q]`、`resize`、`compose`（截屏/读图→裁→缩→标注→存盘）；
  `annotate` 增加 `--jpg/--quality/--max-side`。
- **`shot` 截完直接缩放/压图**：`shot --scale/--max-side/--jpg`，
  MCP `ashot_shot(scale,max_side,jpg,quality)`——不必再调一次 resize；
  缺省文件名跟着格式变（`--jpg` 落 `shot_*.jpg`），retention 清理
  同时收 `.png/.jpg/.jpeg`。
- **MCP**：`ashot_crop`/`ashot_resize`（**22 工具**）；`ashot_annotate`
  增加 `jpg/quality/max_side`。
- **`output.image_size()`**：PNG IHDR + JPEG SOF 嗅探；`preview_jpeg`
  改用它，JPEG 输出也能进缩图梯次。

### 契约
- `box` = **源图像素** `x,y,w,h`（不是 x1,y1,x2,y2）；`dpr>0` = box 是
  CSS 像素；**先裁后缩**；收据回显 `crop`/`crop_px`/`coord_space`。
- 越界 = 夹到边界 + `bounds_warn`（不静默裁掉内容）；完全图外才报错；
  `scale/width/max_side` 三选一，`max_side` 只缩不放。

### 审查修复（子 agent 只读审查，2026-10-29）
- **P0**：`apply()` 先 `mkstemp` 占了输出路径，导致「PS 没写出文件」
  判据恒真 → PS 静默失败会交付 0 字节文件。改为占位后 `unlink`，
  并加「非空 + 魔数（PNG/JPEG）匹配」双校验，不符即 RuntimeError。
- **P1**：引擎上报的 w/h 缺失或与请求不一致 → 直接失败（旧实现短路
  漏检，只有 w 无 h 还会 TypeError）；输入从「只认 PNG」放宽到
  **PNG/JPEG**（GDI+ 本来就能读，旧实现让 jpg 再裁一刀报「PNG 坏了」）；
  `ashot_shot` 的 docstring 误混入 annotate 的 v0.4.0 段落（会让模型
  按描述传不存在的参数）；CLI `annotate`/`shot` 的 informational 行
  从 stdout 挪到 stderr（stdout 只留路径的契约）。
- **P2**：`dpr` 无 crop 时报错（不再静默忽略）、尺寸舍入改四舍五入、
  `out_path` 支持「不存在但带尾分隔符」的目录、`_parse_box` 的 JSON
  分支校验 4 项、conftest 用 session 根目录并注明「mkdtemp 在本机
  不可写」的实测理由。

### 测试
- 新增 `tests/test_transform.py` 30 项 + `tests/conftest.py`（把 tmp_path
  从 0o700 换成常规权限目录——本机沙箱下 0o700 目录不可写，旧办法
  `--basetemp` 治不了）。全套 **141 项**通过。
- 真机：4K 桌面截图 → 裁 600×700（345ms）/ 1.5× 放大代码（435ms）/
  resize+JPEG 228KB / compose 980×950 JPEG 126KB（1046ms）。

## [0.3.0] - 2026-10-29

### 发布（文档与版本里程碑）
- 版本号对齐能力里程碑：0.2.7/0.2.8 引入的「通用视觉与 DOM 原语」
  （图像指纹/差异、元素矩形+可见性、iframe 映射含 OOPIF）视为一次
  能力扩展，统一到 0.3.0。
- README 重写：安装与要求、能力清单（20 工具）、CLI 示例、平台与边界
  表（明确 Mac 批2 / Win 批3 / 验证码不做）、目录结构、版本与文档入口。
- 新增 **docs/design/README.md** 设计文档索引（正稿/扩展/增补/审查
  的关系与实现状态），避免后来者按文件名猜。
- `.gitignore` 补 `.pt*/`（本机 pytest ACL 残留目录）。

### 说明
- 功能与 v0.2.8 完全一致；本版只动文档与版本号，不改代码行为。
- 测试 111 项全绿。

## [0.2.8] - 2026-10-29

### 新增 / 修复（v0.2.7 原语的三个欠账）
- **跨站 OOPIF iframe 映射**：`Page.createIsolatedWorld` 对跨站 frame 报
  "No frame for given id found"（实测）——改用
  `Target.getTargets` 找 type=iframe 且 targetId==frameId 的 target →
  `Target.attachToTarget(flatten)` → 命令带 `sessionId` 直达该进程求值
  （`Session.command` 新增 session_id）。实测 example.com iframe：body
  (100,80,400,756) 被 iframe 裁到 visible_ratio=0.397、p (132,171) 命中，
  收据带 `oopif:true`。
- **frame 内元素可见比例修正**：之前 `visible_ratio` 只按子 frame 视口算，
  iframe 外的部分会被算成"可见"。现在与「主视口 ∩ 每层 iframe 内容框」
  求交，新增 `clipped_by_frame`；iframe 外的点击会先被这一步拦下。
- **拼接隐藏 fixed/sticky**：吸顶栏逐屏重复的老毛病——拼接前
  `visibility:hidden`（保留布局），拍完还原；收据带 `fixed_hidden:N`。

### 测试
- 111 项全绿（新增 3：OOPIF attach 映射、可见比例裁剪、fixed 隐藏/还原）。

## [0.2.7] - 2026-10-29

### 新增（三个通用原语；**不是验证码模块**）
- **图像指纹与差异**（`ashot/vision.py`）：`sha256`（精确）+ `dhash`/`ahash`
  （64-bit 感知哈希，imagehash 同思路、纯整数实现）+ `hamming`；`diff`
  用 pixelmatch 的 **YIQ 颜色距离 + threshold**，返回 changed_px/ratio/
  bbox/size_mismatch，可输出差异图（变化涂红、其余压暗）。用途：截图
  去重、页面变化监控、UI 回归，以及调用方自己拼"图变了就重来"。
  **未做 pixelmatch 式抗锯齿检测**（纯 Python 成本高），收据 note 明示。
- **元素矩形 + 可见性**（`ashot/dom.py`）：`element_rect(selector)` 返回
  视口 CSS 矩形/中心点、`visible`（Element.checkVisibility，2024-03
  Baseline；旧浏览器回退）、`in_viewport`/`visible_ratio`、`occluded`
  （elementFromPoint 中心）、`pointer_events`、`dpr`、滚动位置；
  `scroll=True` 先 scrollIntoView 再量。坐标可直接喂 cdp-click。
- **iframe 坐标映射**：`frame_element_rect(iframe, selector)` 同源任意
  深度走 JS 递归（一次求值）；跨域同进程走
  `DOM.describeNode(frameId) → Page.createIsolatedWorld → 子 frame 求值
  + DOM.getBoxModel 内容框原点`（实测 600+25,300+15 → 625,315 正确）；
  跨站 OOPIF 如实报 `oopif_unsupported`（需要 Target 会话，本版不做）。
  `frames()` 列 frame 树并尽力附 iframe 矩形。
- CLI：`hash` / `diff` / `element` / `frames` / `frame-element`；
  MCP：`ashot_hash` / `ashot_diff` / `ashot_element` / `ashot_frames` /
  `ashot_frame_element`（**20 个工具**，需宿主重连）。

### 实弹（Playwright 拉起的 Edge 156）
- `element_rect("#btn")` → (120,80,100,40)，按中心 (170,100) 点击 →
  页面 `__clicks` 变 1（**真点中**）；
- 盖一层透明 div → `occluded:true` 而 `visible` 仍 true（语义分离正确）；
- 同源 iframe：#inner → (320,210)（300+20/200+10）；跨域 data: iframe
  的 #x → (625,315)（600+25/300+15）；`frames()` 两个 iframe 矩形正确；
- `scroll=True`：1500px 处的按钮滚到视口 y=286（scroll_y=1214）。

### 修复（实现期踩到）
- **DOM 节点 id 是会话级的**：分多次 `cdp.call`（每次新连接）做
  getDocument→querySelector 会报 "Could not find node with given id"；
  跨域映射与 frames 改为**单个 Session 内完成**（`DOM.enable` 只开 DOM
  域，不碰 Runtime.enable 红线）。

### 测试
- 108 项全绿（新增 10 项：指纹稳定性、diff 精度/尺寸不匹配/差异图、
  element 字段与 scroll、跨域映射、OOPIF 报错、frames 扁平化、CLI）。

## [0.2.6] - 2026-10-29

### 修复（按《问题清单与逐条核实-2026-10-29》Q01-Q23 逐条落地）
- **text 出界（Q15，用户实感）**：不换行/不裁切/不报错三件套一起修。
  text op 新增 `w`（布局矩形宽）→ `_gdi_render.ps1` 走
  `DrawString(RectangleF)` 由 GDI+ 按真实字体度量**原生自动换行**；
  ps1 用 MeasureString 实测每个 text/dot 的 bbox 回传，Python 与画布
  比对后写 `bounds_warn`（如 `op[0] text 超出画布：右 135px`）——
  告警优于裁切（裁切会悄悄丢内容）。像素降级路同步认 `w`（点阵贪心折行）
- **截图多一跳（Q16）**：`ashot_shot`/`ashot_annotate`/`ashot_cdp_shot`
  的 `preview` **缺省翻成 true**（README/SKILL 已改），缩图预算
  500KB→**200KB**；`preview:false` 保留旧单字符串收据
- **窗口截图带阴影（Q17）**：`--win` 改用
  `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` 取可见帧界
  （本机实测 446×331 → **424×320**，每侧少 11px 不可见边），失败回退
  GetWindowRect 并标 `box_source`；`hwnd=0`（锁屏/服务态）不再拿 0 去
  GetWindowRect，改抛可读错误
- **改码后 MCP 进程不更新（Q18）**：所有工具收据由 `_serve` 单一出口
  盖 `ver` 字段（文件版本号对了但进程是旧的，一眼识破）
- **DISCOVER 单实例误伤 + 14 秒（Q04/Q20）**：进程枚举改为**检查返回码
  与 stderr**（Win11 上 Get-CimInstance 可能 Access denied，旧实现静默
  吞掉、退化成纯端口扫描）；端口探活改**并发 + 0.6s 超时**（实测
  14.3s → **0.94s**）；`discover` 新增 `details/confidence/warnings`；
  单实例也不再静默——收据带 `target`（端口/进程名/页签 title+url），
  多实例连 `cdp-shot` 一起拒绝猜（原只有输入类拒绝）
- **降级原因不可辨（Q08）**：矢量路失败原因写进 `degrade_reason`
  + `backend_fallback`（旧实现只见 `backend=pixel`，设计内降级与环境
  坏了同形）
- **GDI 原始错误丢失（Q09）**：`capture.shot` 兜底成功时也带
  `gdi_error`；双腿全废时把两条原因一起抛出
- **CLI annotate 写错位置（Q07）**：`default_out()` 单源（先看 basename
  有没有点），父目录带点（`…/my.dir/shot`）不再把产物写到上一级
- **剪贴板 os.system（Q10）**：`os.system` → `subprocess.run`（引号拼接、
  stderr 可见性、PS 侧 ErrorActionPreference 三处一起修）
- **字库缓存永久（Q11）**：`fonts.list_families(refresh=)` + `clear_cache()`
  + 300s TTL；CLI `fonts --refresh`，MCP `refresh` 参数缺省 true
- **点击轨迹恒从左上角出发（Q12）**：`_start_point()` 缺省在目标周围
  140~420px 随机方位起步（seed 可复现），`from_x/from_y` / CLI
  `--from-x/--from-y` 可显式指定
- **fullpage 坐标语义（Q06）**：全页截图收据新增
  `coord_space=document` + `scroll_y`，hint 明说"点首屏以下要先滚、点击
  坐标=文档坐标−scrollY"（旧的 `min()` 数值 bug v0.2.5 已修，残的是语义）
- **schema 全 string + 布尔五连写（Q13）**：`_tool` 按默认值推
  boolean/integer/number；布尔解析统一到 `ashot/_coerce.as_bool`
  （mcp/cli/vector 三处共用，消灭 12 处字面量）
- **eval 的 None/undefined 同形（Q14）**：收据补 `value_type`；重复
  `import base64 as _b64` 去掉
- **像素路只吃 RGBA（Q21）**：`_decode_png` 支持 8-bit 灰度/RGB/调色板/
  灰度+α/RGBA 五类（16-bit 与隔行仍如实拒绝，报错给可操作提示）
- **CLI 信息残缺（Q22/Q23）**：`cdp-shot` 补齐 to_css/coord_space/scroll_y
  输出；`allow_abbrev=False`（`--ops` 不再被 `--ops-file` 前缀吞掉）；
  `os_startfile` 去重复定义
- **字体本地名承诺（Q19）**：本机实测 .NET 的 FontFamily.Name 也只回
  英文名，`fonts 楷体` 必然为空——测试改为**按实际数据判定**（存在
  本地别名就必须双命中），设计文档 §7.9.2 承诺收紧为"OS 提供本地名时"；
  HEAD 的唯一红测试清零

### 新增
- `_gdi_render.ps1` 末行输出 `{ok, boxes:[{i,x,y,w,h}]}`（实测 bbox，
  text/dot 都用 MeasureString）
- `ashot/_coerce.py`（as_bool / as_int 单源）
- 修复锁测试 28 项：dispatch 拷贝契约、discover 降级亮牌、pick_port
  多实例拒绝、coord_space、default_out、degrade_reason、gdi_error、
  hwnd=0、轨迹起点、换行+越界告警、RGB/调色板解码、value_type、
  收据盖章、CLI 前缀缩写、CLI cdp-shot 坐标输出

### 变更（行为/契约）
- `preview` 三处缺省 true（**会多一次缩图子进程，约 0.3s**；不想要就传
  `preview=false`）
- `drag_events` 的 `jitter` 在受约束模式下仍只影响轴向微抖（amp=min），
  MCP/CLI 两脸一致
- 单实例 discover 也会把 `target` 写进收据；多实例时 `cdp-shot` 从
  "静默取 [0]" 改为拒绝（与输入类同规）

### 测试
- 98 项全绿（新增 28 项修复锁），`_gdi_render.ps1` 保持纯 ASCII；
  关键锁做了变异测试（改回旧实现即变红）

### 独立审查后的追加修复（子 agent 审计：0 致命 / 1 严重 / 11 建议）
- **S1（严重）`cdp.shot` 的 coord_space 误判**：旧判据 `sz[1] > vh*dpr+1`
  在 `dpr` 求值失败（真实路径）时把视口截图标成"文档坐标"，`to_css`
  同时错一倍，等于给 agent 递错误点击指引。改判整页内容高
  （`content_h > vh+1`）；`fullpage=True` 但内容没超视口=viewport；
  拿不到 content_h=unknown；dpr 缺失时标 `to_css_estimated` 并在 hint
  里让先 `cdp-view`
- 错误收据也盖 `ver`（原只在成功路径盖章——最需要识破旧进程时失效）
- `cdp_eval` 不再把 `null`/数组误报成"不可序列化"
- MCP schema 的坐标/端口/计数类参数按语义声明 integer（`from_x/from_y`
  默认 None 时旧推理会落成 string）；CLI `cdp-dblclick` 补
  `--from-x/--from-y`（与 MCP 对齐）
- `_LAST_TARGET` 改"先 clear 再 update"（异常路径不再残留上一个目标，
  也消除 clear/rebind 两种写法分叉）
- `Capture._win_box` 的 Win32 原型在导入期定死（`GetWindowRect`/
  `DwmGetWindowAttribute` 原先无 argtypes，HWND ≥ 2^31 有截断风险）
- `_probe_ports` 用 `as_completed` 收结果（不被最慢端口按序阻塞）
- MCP `fonts` 的 `refresh` 缺省改回 false（TTL 300s 已满足 Q11，
  缺省 true 会把缓存架空、每次多跑一次 PowerShell）
- 清理死代码：`mcp._describe_ports`/`mcp._resolve_cdp` 两个无调用方的
  包装、`fonts._CACHE` 重复定义
- 弱锁补强：Q12 直接断言"不同 seed 方位角不同"（固定偏移 mutant 原可
  存活）；Q21 补 Sub(filter=1) 的 RGB/调色板图（bpp=4 mutant 原可存活）

### 二轮审查（同日再查：1 实测 bug + 4 健壮性）
- **S2（实测）全页坐标单位错**：`Page.getLayoutMetrics` 的 `contentSize`
  是**已废弃的设备像素字段**（实测 Edg156：contentSize=2544×1632 vs
  cssContentSize=1272×816，dpr=2）。旧实现拿它当 CSS 用 → 整页高被高估
  dpr 倍、`coord_space` 把视口图报成"整页文档图"。改用 `cssContentSize`/
  `cssLayoutViewport`（无 css* 的旧协议按 dpr 折算并标 `content_source`）；
  坐标空间判据改为**图像实际覆盖的 CSS 高**优先；页高超过截图上限或只
  截到视口时收据亮 `fullpage_truncated`，hint 写清"只截到 N CSS"
  （联网+Playwright 实测：Chrome 本身**没有**夹全页截图，941×3000 CSS
  的页在 dpr=2 下正常出 1882×6000——此前的"被夹"是单位误读）
- 像素降级路的越界告警补齐（`_estimate_boxes` 按点阵字宽估算；
  上一版只有 GDI+ 路有 bounds_warn）
- `pick_port` 对最小 discover 字典（只有 ports/hint）不再 KeyError
- 剪贴板失败信息按 OEM/GBK 解码（原按 UTF-8 解 → 中文乱码）
- 非 8-bit PNG 的报错文案覆盖低位深调色板（原只说 16-bit）
- **超长页预览限高**（维基 49446px 实弹）：`preview` 原先只按宽度缩，
  长页"缩图"仍有 **2.8MB**（fit=False 却照样进上下文）。改为同时约束
  高度（缺省 4000px，等比缩、不放大），同页缩图降到 **122KB / 60×3977
  / fit=true**；info 增加 height
- **超长页滚动拼接**（用户点破：CDP 本来就能控滚动）：单张
  `captureBeyondViewport` 的高度上限**因环境而异**（实测同一份代码：
  Playwright 拉起的 Edge 一次拍 60000px 只要 0.46s，另一实例 17000px
  就报 "Unable to capture screenshot"）。因此策略是**先试单张、失败
  才拼**：`_stitch_fullpage` 按视口滚动（JS scrollTop，失效退鼠标滚轮）
  逐屏拍、按**实际 scrollY×dpr** 贴到画布、拍完还原用户滚动位置；
  `--no-stitch` / `stitch=false` 关闭兜底，收据带 `stitched/shots`；
  拼接画布另有像素上限，超了如实 `fullpage_truncated`。固定定位元素
  会在每段重复（已入档）


## [0.2.5] - 2026-10-28

### 修复（对抗审查实锤 3 致命 / 6 严重，全部闭环；动机=滑块验证码场景可用化）
- **拖拽纵向漂移（致命）**：弓形偏移按距离比例放大（水平拖 520px 纵向
  漂 50.5px），拖滑块必脱轨。`drag_events` 缺省改走**受约束轨迹**
  （垂直偏移单标量抽样、严格 ≤ max_perp=2.5px、与距离无关），
  `constrained=False` / CLI `--free` 保留自由弧线（画图/框选用）
- **dispatch 每事件重连 ws（致命）**：实测 17ms/事件全是握手开销，
  速度曲线只在空间成立、时间上绝对匀速（比真人更可疑）。新增
  `Session` 一次握手整批派发 + 事件级 `_delay_ms` 真实节奏
- **mcp.py 缺 `import time`（致命）**：MCP 脸 click/drag 一调用即
  NameError，且崩点在事件已发出之后
- **to_css 用 min() 差一个数量级（致命级误导）**：全页截图下
  min(vw/w, vh/h)=0.102 vs 正确 0.5。屏幕像素→CSS 像素是各向同性
  缩放，改用 1/dpr
- 垂直抖动双抽样导致幅值上界 √2×max_perp（改单标量）；MCP/CLI 的
  max_perp 语义分叉；total_ms=0 未真全速（连停顿一起归零）；
  CLI drag `--verify` 哑开关；click 静默变慢无逃生门（`--no-timing`）；
  dispatch 就地 pop 破坏调用方重试——全修

### 新增
- **节奏三档可调**（用户需求「速度可调、验证码类慢点」）：
  `fast` 150~600ms / `normal` 320~1400ms / **`captcha` 900~2600ms**
  （末端过冲回退 3~6px 更明显）；`total_ms` 显式优先，0=真全速；
  `--no-timing` / `timing=false` 一键关节奏
- **`ashot_cdp_eval`**（第 14 工具）：JS 求值——函数体自动包 IIFE
  （Runtime.evaluate 不认裸 `return`，静默 undefined 实弹踩过）；
  **绝不发 Runtime.enable**（字节系检测点红线不变）
- **`ashot_cdp_view`**（第 15 工具）：vw/vh/dpr/整页尺寸——坐标换算依据
- **`ashot_cdp_shot` 收据升级**：w/h（PNG 真实像素）+ vw/vh/dpr +
  **to_css**（截图像素 × to_css = 点击 CSS 坐标）；获取失败亮
  `layout_error` 不吞主收据
- **verify 参数**（drag/click/type）：dispatched N 只说明发出、不说明
  生效——可选一段 JS 操作后求值进收据
- 末端过冲回退（人类调整动作，幅度由档位给）；drag 步数下限 10→18
  （旧值短距离比人快一倍）

### 变更（行为/契约）
- **多实例安全边界**：discover 命中多个调试端口时输入类动作**报错**
  （列出各实例首个页签供挑选），不再静默取 [0]（曾把另一工具的 9225
  当成目标）；只读 `cdp-tabs` 允许一次列多实例（groups 分组）
- 等待被 3s 上限夹断时收据亮 `clipped_ms`（不静默）

### 实弹验证（Edge 1272×816 dpr2，真浏览器）
- 420px captcha 档拖拽：40 事件 2.15s（计划 2052ms），页面实收 38 点
  **纵向跨度 4.0px**（修复前同距离漂 50px），终点精确落点
- 测试 70 项全绿（新增：约束契约锁、长距离漂移不放大、节奏三档单调、
  total_ms=0 全速、WS 桩回显 id + 去掩码、schema 新参数）

设计文档：`docs/design/功能设计-v0.2.5-滑块拖拽约束与节奏-2026-10-28.md`
（含 v0.2.0 §4.2.3「无真实延时/时序拟真属于未来 batch」的覆盖注记）

## [0.2.4] - 2026-10-28

### 新增（批1 追加：人类化鼠标轨迹，用户需求「不要瞬移，带抖动模拟人类但比人快」）
- **`human_move_events`**：三次贝塞尔（控制点垂直随机弓偏 10%~25%）
  + smoothstep 缓动（慢起-快中-慢收）+ 逐点微抖动（±2px × sin(πt)
  fade，中段最抖两端收敛）+ **首尾精确落点**（点击必须准）；步数按
  距离自适应 8~28（拖拽 10~40）；**比人快**——无真实延时；`seed`
  可复现
- **接入**：cdp-drag（按住态轨迹）/cdp-click/cdp-dblclick（接近轨迹
  到位再按下）缺省 human=True；`--teleport` / `human=False` 逃生门
  退回旧行为；MCP 同名三工具加 `human`/`seed` 参数
- **实弹形态验证**（headless Edge mousemove 回读）：起终点精确、
  中段最大偏离直线 14.9px、前段点距 1→5→9→12→15 递增（缓动）——
  反检测三特征齐活
- **诚实边界入档**（设计文档 §4.2.3）：形态像人≠时序像人（无人类级
  延时）；轨迹随机≠不可检测（高级风控可统计辨识）——不夸大
- 业界配方来源：pyautogui 贝塞尔 SO 经典答/human_mouse/RTILA/IJIRT
  论文；测试 69→70（seed 确定性/首尾精确/步数自适应/teleport 旧行为/
  schema human+seed 参数）

## [0.2.3] - 2026-10-28

### 新增（批1 追加：双击/多击 + 填表整段输入，用户需求）
- **`cdp-dblclick x y [--button] [--count N]`**：clickCount 递增序列
  （浏览器据此合成 dblclick；count=3 三连击）；MCP 第 12 工具
  `ashot_cdp_dblclick`
- **`cdp-type <文本> [--x --y]`**：Input.insertText 粘贴式填表（不逐
  键击、不触发每键 keydown，含多行/中文）；x/y 可选先点击聚焦；MCP
  第 13 工具 `ashot_cdp_type`
- **隔离语义入档**：CDP 事件只进指定标签页、不占用户物理键鼠——
  自动化与用户操作天然不冲突
- **buttons 位掩码修正**（子 agent 审计 P2-1，顺带治好 v0.2.0 起的
  click/drag 旧病）：按下掩码按 button 查表（left=1/right=2/
  middle=4，Playwright 同款）——中键/右键按下时页面 e.buttons 不再
  矛盾
- 修复 insertText 路由（实弹抓到：它不是 dispatchKeyEvent 的事件
  类型，是独立命令 Input.insertText；删 VK229 前置占位）；CLI
  cdp-type --x/--y 成对守卫（审计 P2-2）；审计 P2-3 补路由锁测试
  （insertText 走独立命令 + dblclick clickCount 递增，monkeypatch
  零网络）
- 实弹 headless Edge：insertText 含中文整段进 input（value="hello
  填表"）；测试 67→69

## [0.2.2] - 2026-10-28

### 修复（键盘覆盖补全批，用户问「所有键盘按键都支持了？」→诚实答未全→补上）
- **键表补全**：F1-F12、符号键（semicolon/equal/comma/minus/period/
  slash/backquote/brackets/backslash/quote，VK≠ord 的 ord 错表修正）、
  insert/printscreen/numlock/capslock/scrolllock/pause/contextmenu、
  小键盘全键（numpad0-9/运算符/enter）；**移位级符号** `:?!@#$%^&*()_
  +<>"{}|~` 直查（VK=底层键位非 ord）
- **key 名规范化**（子 agent 审计 P1-1，headless Edge 实机实锤）：表
  内键的 `key` 字段出 UI Events 规范名（小写别名传入→`"Enter"`/`"F5"`
  出）——旧版页面侧 `e.key` 为空串，按键监听收不到
- **符号别名 key=符号本身**（审计 P1-2）：`;` 的 key 是 ";" 不是
  "Semicolon"（Puppeteer 同款）
- **未知键名亮牌契约**：透传事件带 `unresolved` 标记，dispatch 剥除
  并汇总——CLI stderr 警告 + MCP 收据 `unresolved_keys`（审计 P1-3
  死代码假锁换真 dispatch monkeypatch 测试：删 pop 即红）
- 删除死函数 key_combo_events；测试 65→67（键表全覆盖/f5 VK/符号
  别名/移位符/未知键标记/线上无非法字段）

## [0.2.1] - 2026-10-28

### 新增（批1 追加：CDP 输入事件注入，用户需求：滚轮/回车/组合键/拖拽）
- **按键/组合键** `cdp-key`：可见字符 `rawKeyDown`+`char` 双发（只发
  rawKeyDown 不产生输入、只发 char 不触发快捷键）、控制键 keyDown+
  keyUp、**组合键 modifiers 位掩码**（Alt1/Ctrl2/Meta4/Shift8，如
  `--modifiers ctrl+shift`）+ 按住/回弹序；`--text` 覆盖注入文本
- **滚轮** `cdp-wheel`（dx/dy）、**单击** `cdp-click`（x/y/button）、
  **拖拽** `cdp-drag`（按下→插值移动→释放事件序列）
- MCP 第 8-11 工具 `ashot_cdp_key/cdp_wheel/cdp_click/cdp_drag`
  （需宿主重连）
- 修复 dispatch 路由 bug：char 事件 type 不以 key 开头被误路由到
  dispatchMouseEvent（实弹抓到）
- 实弹验证（headless Edge 交互页）：键击产生真实输入（DOM value=ab
  + input 事件触发）、Enter 键监听命中、滚轮 scrollY=800、拖拽/组合
  键派发成功
- 设计文档 §4.2.2；测试 62→65（键序列/拖拽序列纯函数锁、WS 桩派发
  往返、schema 十一工具）

## [0.2.0] - 2026-10-28

### 新增（v0.2.0 批1：CDP 浏览器捕获，跨平台）
- **CDP 浏览器截图**：纯标准库 CDP 客户端（裸 WebSocket：握手/客户端
  帧强制掩码/长度三态/**收侧分片重组**/ping-pong/close 回礼/半包
  recv/帧上限/只连 127.0.0.1）——`cdp-tabs` / `cdp-shot` CLI 子命令
  + MCP 第六七工具 `ashot_cdp_tabs` / `ashot_cdp_shot`（需宿主重连）。
  **无头/有头通吃、与 AI 宿主无关**（Workbuddy/Codex/DeepSeek 等启动
  的 Chromium 系浏览器均可抓）；`captureBeyondViewport` 全页截图
  （Chrome 90+）
- **浏览器自动发现**（四级）：进程命令行提取 --remote-debugging-port/
  --user-data-dir → DevToolsActivePort → 扫 9222-9229 → 如实报；
  Chrome 136+ 默认 profile 拒远程调试——收据 `default_profile_denied`
  亮牌，用非默认 --user-data-dir
- **Mac 前置（审计 P1-1）**：capture.py 顶层 windll 加平台守卫——
  Mac 上 import 链全通，cdp 命令 Mac 可用（桌面捕获路 Mac 上如实报
  「批2 规划中」）；`screens` 非 Win 如实报不裸崩（审计 P2-2）

### 设计
- 设计文档 v0.2.0 扩展篇（跨平台+CDP+窗口捕获三批规划）+ 子 agent
  两轮审计修订（规划稿 P1×3/P2×8；批1 代码 P1×1/P2×2 修复：WS buf
  线穿、探活异常面、screens 错误纪律）

### 测试
- 57→62：WS 桩分片重组（ping 穿插）/ 合包共存+单帧应答 / 发侧长度
  三态掩码 / DevToolsActivePort 三态 / discover 结构 / schema 七工具

## [0.1.12] - 2026-10-28

### 新增
- **show 用户可见展示**（自 tmp/show.py 升格入库，用户裁决「弄到程序
  里对接上」）：新模块 `ashot/show.py` 的 `build_html(image, title,
  out_dir, caption?, width?)`——缩图/编码**复用 preview_jpeg 单源**，
  base64 内嵌极简 HTML 落 `<out_dir>/<title>.html`；title 规范化为
  `[a-z0-9-]`（空则如实报错）、caption 缺省=文件名（html.escape）、
  out_dir 自动创建且由调用方给（::visualize 场景=会话可视化目录，
  Ashot 不持有会话状态）
- **CLI** `show <image> --title T [--caption C] [--out-dir D]
  [--width N]`（html 路径 stdout、preview 信息 stderr）+ **MCP 第五
  工具 `ashot_show`**（out_dir 必填；需宿主重连出现）

### 背景
- MCP ImageContent 宿主实测修正定稿：ZCode 转视觉块喂模型、**不渲染
  给用户**（§7.10.3）——用户看图通道由此命令化

### 测试
- 52→55：build_html 落盘与数据 URL、标题规范化报错、CLI 子进程接线、
  mcp schema 五工具集

## [0.1.11] - 2026-10-28

### 新增
- **preview 图片收据**（MCP ImageContent 实验）：`ashot_shot` /
  `ashot_annotate` 可选 `preview=true`——收据升级多内容块（文本收据 +
  1200px JPEG 缩图 ImageContent，`audience:["user"]` 注解）。缩图走
  系统 .NET（渲染器同引擎，零依赖不破），梯次
  (1200,85)→(1200,70)→(900,75)→(600,60) 降档直至 ≤500KB，不放大，
  梯尽仍超限如实 `fit=False`。缺省 false=现状，完全向后兼容。
  **宿主渲染行为待实测**（设计文档 §7.10.3 实验协议）：规范原生支持
  但各宿主参差（Claude Desktop 渲染 / Cursor 等掉图）
- `_serve` 分发支持多内容块（handler 返回 list=预成形块，str=旧单文本）

### 测试
- 49→52：preview 兼容锁（false=单字符串）/ 结构锁（两块、mimeType、
  JPEG 魔数、audience）/ 缩图规格（不放大、1200px fit、极小上限
  fit=False）/ mcp schema 含 preview

## [0.1.10] - 2026-10-28

### 新增
- **字库查询**：CLI `fonts [filter]` 子命令 + MCP 第四工具
  `ashot_fonts(filter?)`（收据 `{ok, count, families}`）。数据源与
  渲染器**同源**（.NET InstalledFontCollection）——查出的族名保证
  text op 的 font 可解析（未装名静默回退的反馈回路就此闭合）
- **locale 实测注记**：`FontFamily.Name` 是 OS UI locale 敏感的
  （zh-CN 上楷体/KaiTi、微软雅黑/Microsoft YaHei 双名并存）——枚举
  **双名**（1033 英文规范名 + 本地 Name），输出英文规范名（跨机稳定），
  过滤双语命中（"kai"/"楷体" 都能查到 KaiTi）；MCP 进程内缓存；
  **新 MCP 工具需宿主重连后才出现在工具表**

### 测试
- 47→49：字库列表/双名过滤/CLI 子进程接线；mcp schema 锁更新（四工具）

### 修复（审查收口批）
- text `bold` 字符串形态保真：`"bold":"false"` / `"0"` 等不再被
  `bool()` 当真值渲染粗体
- step/number 徽章字体单源化（ps1 不再硬编码微软雅黑字面量）
- CLI stdout/stderr 显式 utf-8（管道重定向下非 GBK 族名不截断）
- 字库测试显式 `cwd=ROOT`（任意 cwd 跑 pytest 不假红）+ 族名去重/
  无 BOM 锁

## [0.1.9] - 2026-10-28

### 新增
- **text 字体设置**：op 级 `font`（字体族名，缺省微软雅黑——此前写死）
  与 `bold`（缺省 `true` 保持现状）。GDI+ 按系统已装字体解析（零依赖
  红线不破）；**未安装字体名静默回退默认字体**（如实入档，冒烟锁不崩
  出墨）；中英混排 CJK 由 GDI+ 自动字体回退接住；仅矢量路生效，像素
  降级路 8×16 点阵不认（向后兼容，字段被忽略）。设计文档 §7.8

### 测试
- 44→47：font/bold compile 锁、双字体渲染冒烟（含未知字体回退路径）、
  像素路向后兼容

## [0.1.8] - 2026-10-28

### 变更
- **箭头几何重校准**（用户实弹验收「太粗不合理」→ 业界一手调研 →
  「绿色」对比稿拍板）：头长=头宽=3.5×width（1:1 细长三角，旧
  5×w 长 / 7.2×w 宽短胖头废除）、杆恒定≈width（旧接头处 4×width
  膨胀废除）、尾 0.35×width 幂 0.75 温和渐变、**短箭头长封顶
  0.4×全长**；矢量版（vector.py）与像素版（annotate.py）同步改。
  参照系：Flameshot arrowtool（杆恒定+细长三角头+短箭 clamp）、
  matplotlib ArrowStyle（头宽≤头长）。width 用量建议：4K 截图 10~14
- **收据契约修正（A 方案）**：混合 ops（矢量形状+像素操作）时
  backend 不再谎报 pixel——backend 只反映形状渲染后端（GDI+ 成功即
  `gdi+`），收据新增 **`pixel_ops`** 字段（像素操作数量，恒在），
  MCP/CLI 收据同步；降级/纯像素仍如实报 `pixel`

### 新增
- 设计文档 §7.7：业界调研实锤、新几何规格、杆长语义（端点定总长、
  头只随 width、杆=总长−头）、像素 ops 恒最后叠加的时序注记

## [0.1.7] - 2026-10-28

### 新增
- **标注双后端**：矢量形状（rect/ellipse/line/arrow/step/number/text）走
  GDI+ System.Drawing 抗锯齿光栅化（几何计算留在 Python `vector.py` 编译
  器，可单测；渲染脚本 `_gdi_render.ps1` 忠实执行）；GDI+ 失败自动降级
  纯像素画布——收据 `backend` 字段如实标注 `gdi+` / `pixel`
- `text` 原语支持**中文**（DrawString 微软雅黑渲染，解除 8x16 点阵仅
  ASCII 的限制）

### 修复
- 箭头/椭圆/圆角描边边缘的锯齿感（马赛克样硬边）——矢量抗锯齿根修
- PowerShell 5.1 读无 BOM `.ps1` 按 ANSI/GBK 解码，UTF-8 中文注释字节
  错位吞行尾把 `param()` 行并进注释（参数全空、矢量路静默降级）——渲染
  脚本改纯 ASCII

## [0.1.6] - 2026-10-28

### 变更
- `arrow` 缺省升级为**渐变实心箭头**：尾细头胖（圆盘扫掠幂 0.6 快速增粗）
  + 实心三角头（同侧法填充），微信截图风格；`width` 变头部粗细基准；
  `style:"line"` 回退旧式恒粗直杆箭头

### 新增
- `rect` 可选 `radius` 圆角描边（四直段 + 四 90° 圆弧），缺省 0 行为不变

### 修复
- 测试底色判定色序错误（BGRA/RGBA 混淆致全图恒计数、三处断言恒真）——
  修正为真回归

## [0.1.5] - 2026-10-28

### 修复
- **GDI 位图句柄泄漏**：`CreateCompatibleBitmap` 句柄从未 `DeleteObject`，
  长驻 MCP 进程每截一张漏 1 个 GDI 对象、约万张触满配额后主路永久报废；
  补删除并新增 `GetGuiResources` 计数守恒测试
- **GDI 主路自 v0.1.0 起从未跑通**的两层根因：① BitBlt/CreateCompatibleDC
  等 GDI 族函数挂错 user32（无导出，每次 AttributeError 静默降级
  PowerShell 兜底）；② BITMAPINFOHEADER 手撸偏移把 biPlanes/biBitCount
  挤进同一个 int（biBitCount=0、biCompression=32 非法）→ GetDIBits 恒 0。
  改挂 gdi32 + 正经 ctypes Structure + 先摘位图再 GetDIBits（MSDN 硬规则）
  + BI_RGB 32bpp alpha 未定义强制 0xFF（透传会产出全透明 PNG）
- MCP `ashot_annotate` 缺省**静默覆盖原图** → 缺省写 `<原名>_annotated.png`
  （与 CLI 对齐），原件不再被销毁
- 合法 JSON 非对象帧（数组/数字）曾以 AttributeError 杀死 MCP 服务进程 →
  回 `-32600` 继续服务
- 隔行（interlaced）PNG 曾被按逐行扫描线硬解出静默花图 → 如实拒绝
- `save` 传目录时曾无视传入目录悄悄落到缺省目录 → 真落该目录；缺省文件
  名纯秒级时间戳同秒连截互覆 → 进程内单调序号防撞
- PowerShell 兜底撇号转义错误 + 临时文件异常路径泄漏（try/finally）；
  smarterase/spotlight 区域完全在图外时 IndexError 或静默错采 → 干净
  ValueError；gc `retention_days=0` 时钟粒度误删刚存图 → 120 秒新图豁免；
  负数屏序号静默回绕 → 显式报错

### 变更
- shot 收据新增 `all_black` 黑帧自检字段（远程会话/服务态如实亮牌）
- MCP 死代码清理（ThreadPoolExecutor/msvcrt/双 schema）、stdout/stderr
  显式锁 utf-8（防 GBK locale 下异常文本炸服务）

## [0.1.4] - 2026-10-28

### 修复
- `list_screens` EnumDisplayMonitors 实装修复（此前漏调 API 本体、自调用
  回调，MCP 实弹抓出 0×0 空屏）；显式 WINFUNCTYPE 原型 + argtypes

## [0.1.3] - 2026-10-28

### 修复
- 标注 dispatch 二轮审查 P1×2：`line` 原语曾漏出 xyxy 组（原语全灭）；
  `text` 曾带实心圆盘残留背景——均收口并加回归测试

## [0.1.2] - 2026-10-28

### 修复
- step/number 编号渲染顺序 bug（起步 0、先渲染后递增）
- arrow/line 的 xyxy 取键根修（曾按字符迭代读成 x/y/x2/y2）
- `coords`/`area` 逗号串坐标形态实装（文档曾承诺未实现）

## [0.1.1] - 2026-10-27

### 新增
- 四件新标注原语（ShareX 官方源码拆解引进）：`step`（同次调用自动递增
  编号）/ `number`（显式编号）/ `spotlight`（聚光灯：目标区保持、四周
  压暗）/ `smarterase`（边缘均值色填充）

## [0.1.0] - 2026-10-27

### 首版
- 桌面截图：GDI BitBlt 主路 + PowerShell CopyFromScreen 兜底自动降级；
  full/screen/win/area 四模式；进程级 DPI 感知；多屏枚举；全黑帧检测
- 标注七件原语：rect/ellipse/arrow/line/text/mosaic/blur；纯标准库 RGBA
  画布 + 手写 PNG 编解码（零第三方依赖）
- 交付：落盘 / 剪贴板阅后即焚 / 30 天 retention 搭运行顺手清理
- 双入口：CLI（shot/annotate/screens）+ MCP stdio 三工具
  （ashot_shot/ashot_annotate/ashot_screens）

[0.1.7]: https://github.com/rekey-maker/Ashot/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/rekey-maker/Ashot/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/rekey-maker/Ashot/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/rekey-maker/Ashot/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/rekey-maker/Ashot/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/rekey-maker/Ashot/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/rekey-maker/Ashot/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/rekey-maker/Ashot/releases/tag/v0.1.0
