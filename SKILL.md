# Ashot 技能 —— agent 友好的桌面截图与标注工具

## 何时用
用户提到：截屏/截图/截个图/看看屏幕/截给我看、对图片标注（画框/箭头/马赛克/
涂码）、屏幕上某处让我看。独立工具（Ashot 仓库，桌面 `Ashot\` 目录，
GitHub `rekey-maker/Ashot`），**与 ALrec/daemon 无关**，离线可用；直播
画面抽帧走 ALrec snap（那是视频流解帧，不是桌面截屏）。

## 铁律
1. **截图是隐私动作，三档使用边界**（2026-10-27 用户裁决：不必非等用户
   明确要求，agent 可按任务需要选择截图）：
   - 用户明确要求 → 直接截；
   - **任务内在需要**（验证窗口收纳/排查黑屏/确认 UI 状态等，截图是完成
     该任务的必要证据）→ agent 可自主截，事后在汇报里说明截了什么、
     为何截；
   - 与当前任务无关的好奇/留档 → 不截。
   总原则：**有任务理由就敢截，截完必须说**；绝不扩大范围（截与任务
   无关的屏幕区域）。
2. 远程会话/服务态可能截出全黑帧——交付前用肉眼（读图）确认非全黑，黑了
   如实说「当前会话截不出」，不假装成功。
3. `--clip` 阅后即焚（只进剪贴板不落盘）适合临时给用户看；需要我回看/
   标注的走落盘。

## CLI（python -m ashot.cli，仓库根执行）
- `shot [full|screen|win|area]`——全虚拟桌面（缺省）/单屏 `--screen N`/
  前台窗口/区域 `--area L T W H`；`--out` 指定路径（缺省
  `~\Ashot\shots\shot_时间戳.png`）；`--clip` 只进剪贴板；`--open` 截完即看；
  `--retention-days N`（缺省 30，运行顺手清过期旧图）；`--keep` 跳过清理。
  **v0.4.0**：`--scale S` / `--max-side N`（只缩不放）/ `--jpg Q`
  截完直接缩放或存 JPEG（缺省文件名跟着变 `shot_*.jpg`）——
  不必再单独跑 `resize`。
- `annotate <png|jpg> '<ops JSON>' [--dpr K] [--template 文件]
  [--port/--index/--ws] [--space viewport|document]`——ops 里可用
  `selector`/`ref`（v0.6.0；**ref 仅 MCP 同连接可用**，CLI 用 selector）——
  对既有图标注（v0.5.0 起 JPEG 直接进），ops kind ∈
  **rect/ellipse/arrow/line/**curve/arc/polyline**/text（v0.1.7 起中文可标注；v0.1.9 起可选
  `font`=字体族名 / `bold`=粗体开关，缺省微软雅黑+粗体，仅矢量路生效，
  未安装字体名 GDI+ 静默回退默认字体——**先 `fonts <子串>` 核名再写
  font**；**v0.2.6 起 text 可带 `w`=布局宽（像素），GDI+ 按真实字体
  度量自动换行**；越界不再静默——收据 `bounds_warn` 给实测超出像素
  （如 "op[0] text 超出画布：右 135px"），自己改坐标或给 `w`）/mosaic/blur/
  step（自动递增编号）/number（显式编号 value）/spotlight（聚光灯 dim）/
  smarterase（智能擦除）**，坐标亦收 "x,y,w,h" 串（coords/area 键）。
  **v0.4.1 新三件**（与箭头同一条矢量原理：Python 采样成点列 →
  GDI+ 抗锯齿描边，不是像素硬边）：
  `curve` x0,y0,c1x,c1y,c2x,c2y,x1,y1（三次贝塞尔；也收
  points=[[x,y]×4] 或 coords 8 个数）/ `arc` x,y,w,h,start,sweep
  （**度**，顺时针，y 向下；sweep 负=逆时针，>360 夹到一圈；
  也可用 end 代替 sweep）/ `polyline` points=[[x,y],...] 或
  coords="x1,y1,x2,y2,..."。三者都进 `bounds_warn`。
  **ops 字段白名单**：x/y/w/h/x1..、color/width、radius、text/size/font/
  bold/w、value/n、style、dim、block、start/sweep/end（及 `*_angle`）、
  points/coords/area、selector/ref/dpr、pad；白名单外字段（`colour`/
  `widht`）直接报错。`pad` 对矩形族向外扩，坐标型与 selector 型都生效，
  **pad<0 报错**。
  **每个 op 独立** `color:"#RRGGBB"` 与 `width`（粗细）——所有描边
  原语（rect/ellipse/line/curve/arc/polyline/arrow）都支持，可给小数
  （2.5），`<=0` 或 `>1000` 报错；矢量路与像素降级路按四舍五入对齐；`arrow` 缺省=
  渐变实心箭头（v0.1.8 重校准：细杆恒定≈width + 1:1 细三角头，头长=
  头宽=3.5×width，短箭头长封顶 0.4×全长；端点定总长，杆=总长−头可
  自由伸缩；`"style":"line"` 回退旧直杆）；`rect` 可选 `radius`（圆角
  描边）。**width 用量**：4K 截图 10~14、1080p 4~6（width=杆像素粗细）。
  **渲染双后端（v0.1.7 矢量 / v0.1.8 收据）**：矢量形状走 GDI+
  （System.Drawing 抗锯齿，真矢量——边缘平滑无马赛克感，文字走微软
  雅黑）；GDI+ 失败自动降级纯像素画布（硬边）。收据 `backend` 只反映
  形状渲染后端（`gdi+`=矢量成功 / `pixel`=降级或纯像素，混合 ops 仍
  gdi+），`pixel_ops`=像素操作数量；**降级时带 `degrade_reason`**
  （v0.2.6——设计内降级 vs 环境坏了可区分）；**像素 ops（mosaic/blur/spotlight/
  smarterase）恒在形状之后叠加，与 ops 数组位置无关**（spotlight 排
  第 1 也会把画在框外的形状压暗）。
  例：
  `annotate shot.png '[{"kind":"rect","x":10,"y":10,"w":200,"h":50,
  "width":8,"color":"#07C160","radius":12},
  {"kind":"arrow","x1":300,"y1":50,"x2":200,"y2":30,"width":10,
  "color":"#FF3B30"},
  {"kind":"text","x":20,"y":80,"text":"这里有问题","size":28,
  "color":"#FFFFFF"}]'`
- `crop <png|jpg> --box x,y,w,h [--scale S|--width W|--max-side N] [--jpg Q]
  [--dpr K]`（v0.4.0）——**对已有图片裁切**（`shot area` 只能截屏时限定
  屏幕区域，裁不了已存在的图）。`--box` 是 **x,y,w,h（左上角+宽高）**，
  **不是** x1,y1,x2,y2；`--dpr` 表示 box 给的是 CSS 像素（DevTools 的
  getBoundingClientRect），内部乘 dpr。越界=夹到边界+`bounds_warn`，
  完全在图外才报错；收据回显 `crop` 与 `crop_px`。
- `resize <png|jpg> [--scale S|--width W|--max-side N] [--jpg Q]`——缩放；
  `max_side` **只缩不放**，`scale`/`width` 允许放大；`--jpg` 直接出 JPEG
  （收据 format/quality/bytes）；`--dir D --out-dir O` 目录批处理
  （v0.5.0；同名不同扩展自动 -2 后缀）。
- `info <png|jpg>`——`{format,w,h,bytes,path}` 一行 JSON（v0.5.0）。
- `compose (--src IMG|--area L T W H) [--box x,y,w,h] [--scale ...]
  [--rect ...] [--arrow ...] [--text "x,y:文字"] [--jpg Q] --out OUT`
  （v0.4.0）——一条命令出图：截屏/读图→裁→缩→标注→存盘。**标注坐标按
  裁缩后的图**（stderr 会写 coord_space）；`--text` 每处独立，多个
  `--text` 不再共用一条 label。
- `fonts [filter] [--refresh]`（v0.1.10/0.2.6）——列出已装字体族（英文
  规范名，过滤不区分大小写）。**"楷体"这类本地名能否命中取决于 OS**：
  部分机器 .NET 的 FontFamily.Name 也只回英文名，此时只有 "kai" 能查到
  KaiTi（数据边界，不是 bug）；`--refresh` 强制重枚举（v0.2.6，装了新
  字体不必重启；MCP 侧 `refresh` 缺省 false，靠 300s TTL 自愈，急用才
  传 true）。族名走 stdout、计数走 stderr。
- `show <image> --title T [--caption C] [--out-dir D] [--width N]`
  （v0.1.12）——图片→数据 URL 内嵌 HTML（用户可见展示，::visualize
  场景 out_dir 传会话可视化目录）；html 路径 stdout、preview 信息
  stderr。
- `cdp-tabs --port P` / `cdp-shot [--port P] [--index N] [--viewport]`
  （v0.2.0；v0.2.5 收据升级）——**CDP 浏览器捕获**：无头/有头通吃、与 AI 宿主无关
  （任何宿主启动的 Chromium 系，含 --remote-debugging 启动的无头
  浏览器）；--port 缺省自动发现（进程枚举→DevToolsActivePort→常见
  端口；**多实例时输入类命令不猜，报错列实例让人挑**）；cdp-shot 缺省
  captureBeyondViewport 全页，收据带 w/h（出图像素）/vw/vh/dpr/
  **to_css**（截图像素 × to_css = 点击 CSS 坐标；获取失败亮
  layout_error 不吞主收据）。**v0.2.6 坐标语义**：全页截图给的是
  **文档坐标**（收据 coord_space=document + scroll_y）——点首屏以下
  要先滚动，点击坐标 = 文档坐标 − scrollY；不想换算就 `--viewport`。
  收据若带 `to_css_estimated:true` 说明 dpr 没取到、`to_css` 是退化估算，
  先 `cdp-view` 核 dpr 再点；收据带 `fullpage_truncated:true` 或 hint 说
  "只截到 N CSS" 时，说明整页没拍全（页太高/只覆盖视口）——首屏以下要
  先滚动**再截一次**。
  超长页自动滚动拼接（先试单张，被 Chrome 拒绝才逐屏拼：收据
  stitched:true + shots:N；`--no-stitch` 关闭并如实报错）；固定定位
  元素每屏重复。
  Chrome 136+ 默认 profile 拒远程调试——浏览器须用非默认
  --user-data-dir 启动。
- **CDP 输入注入**（v0.2.1/0.2.3/0.2.5）：`cdp-key <键> [--modifiers ctrl+shift]
  [--text T]`（回车/Tab/方向键/F1-F12/符号/任意字符/组合快捷键，
  rawKeyDown+char 双发；未知键收据 unresolved_keys 亮牌）、
  `cdp-wheel --dx --dy`（滚轮）、`cdp-click x y [--button] [--no-timing]
  [--verify JS]`（单击，left/right/middle）、`cdp-dblclick x y [--count]`
  （双击/三连击）、`cdp-drag x1 y1 x2 y2 [--steps] [--pace
  fast|normal|captcha] [--total-ms N] [--free] [--verify JS]`（拖拽：
  缺省**受轨道约束**+节奏化+末端过冲回退；**拖滑块用
  `--pace captcha`**≈900~2600ms；`--free` 画图框选走自由弧线）、
  `cdp-type <文本> [--x --y] [--verify JS]`（**填表整段输入**，
  Input.insertText 粘贴式含中文，不逐键击）——
  全部 --port/--index/--ws 同 cdp-shot。注入的是 CDP isTrusted 事件
  （页面无法区分），**只进指定标签页、不占用户物理键鼠**（自动化与
  用户操作天然隔离）；insertText 落点=目标标签页当前焦点元素
  （--x/--y 先点击聚焦）。**verify**：dispatched 只代表事件发出，不代表
  生效——给一段 JS（如 "return document.activeElement.value"），操作后
  求值结果进收据。
- `cdp-eval '<js>'`（v0.2.5）——标签页内执行 JS 并取值（函数体自动包
  IIFE；纯表达式直发）。算坐标、读页面状态确认操作生效、拿 dpr。
  **只发 Runtime.evaluate，绝不发 Runtime.enable**（字节系检测点）。
- `cdp-view`（v0.2.5）——视口信息 vw/vh（CSS 像素）/dpr/整页尺寸。
  **坐标换算铁律**：截图出图是物理像素（=CSS×dpr），直接拿截图坐标
  去点击必然落空；`cdp-shot` 收据的 `to_css`（=1/dpr）× 截图像素 =
  点击用 CSS 坐标。
- **多实例纪律**（v0.2.5/0.2.6）：本机有多个 CDP 浏览器时，输入类命令
  **与 cdp-shot** 都不猜端口——报错并列出各实例页签，**必须显式
  `--port`**；单实例也会把目标身份（端口/进程名/页签标题）打到 stderr。
  `discover` 的进程枚举失败（如 WMI 拒绝访问）会以 ⚠ 明示并退化为端口
  扫描，不静默。
- `screens`——列出显示器（非 Windows 平台如实报「批2」）。

## 通用原语（v0.2.7，非验证码）
- `hash <png> [--algo sha256|dhash|ahash]`——图像指纹；`dhash` 对缩放/
  亮度平移稳定，适合"是不是同一张"。
- `diff <a> <b> [--threshold 0.12] [--out diff.png]`——YIQ 差异：
  `changed_px/ratio/bbox/size_mismatch`；差异图=变化涂红、其余压暗。
  **未做抗锯齿检测**，字体边缘可能有少量假差异（收据 note 会写）。
- `element <selector> [--scroll]`——元素**视口 CSS 矩形**（x/y/w/h/cx/cy）
  + `visible`（checkVisibility）/`in_viewport`/`visible_ratio`/
  `occluded`（中心点 elementFromPoint）/`pointer_events`/dpr/滚动。
  **坐标可直接喂 cdp-click**；截图坐标要先 × to_css，别混用。
- `snapshot`——页面结构快照：`[ref=eN] [box=x,y,w,h]`（视口 CSS），
  refs 映射回 CSS 选择器（v0.6.0；比看截图猜坐标准）。selector/ref 已含
  页面 dpr，**别再传全局 dpr**（坐标型 op 传 dpr 会报错）；ref 只对最近
  一次 snapshot 有效。
- `cdp-view` 的 `scrollables`：内部滚动容器（`scroll_top/scroll_h/client_h`
  + `selector/rect/overflow_*`；只收 overflow:auto|scroll|overlay）；
  `content_h` 只反映 document，别拿它判断能否滚动。
- `frames`——frame 树（id/url/parent/depth）+ 能取到的 iframe 矩形。
- `frame-element <iframe选择器|JSON数组> <选择器>`——iframe 内元素 →
  主页面视口坐标；同源任意深度、跨域同进程、**跨站 OOPIF**（Target
  flatten 会话）都可用，收据带 `cross_origin`/`oopif`；可见比例已与
  「主视口 ∩ iframe 内容框」求交（`clipped_by_frame`），iframe 外不会
  被算成可见。
- 典型用法（不涉及验证码）：`element` 拿按钮中心 → `cdp-click` 点它 →
  `cdp-eval 'return ...'` 验证；`hash` 前后对比判断页面变没变。

## MCP（ashot 域名，宿主注册后可用）

v0.6.1 起 **23 个工具**：`ashot_shot` / `ashot_screens` / `ashot_annotate` /
`ashot_crop` / `ashot_resize` /
`ashot_fonts` / `ashot_show` / `ashot_hash` / `ashot_diff` / `ashot_element` /
`ashot_frames` / `ashot_frame_element` / `ashot_snapshot` / `ashot_cdp_tabs` /
`ashot_cdp_shot` / `ashot_cdp_view` / `ashot_cdp_eval` / `ashot_cdp_key` /
`ashot_cdp_wheel` / `ashot_cdp_click` / `ashot_cdp_drag` /
`ashot_cdp_dblclick` / `ashot_cdp_type`
——覆盖 CLI 主要能力（**`compose`/`info` 仅 CLI**）；cdp 系参数见上文 CLI 段；hash/diff/element/
frames 见「通用原语」段。
`ashot_shot`（mode/screen/out/clip/keep/retention_days/area；收据带
`all_black`——远程会话黑帧自检，true=如实报「当前会话截不出」；
`box_source`=区域来源，win 模式 dwm=可见帧界、rect=回退；`gdi_error`=
主路降级原因）、
`ashot_annotate`（image/ops/out + jpg/quality/max_side；**缺省写
<原名>_annotated.png，绝不覆盖原图**）、
**`ashot_crop`（image/box(x,y,w,h)/dpr?/scale|width|max_side/jpg?）/
`ashot_resize`（image/scale|width|max_side/jpg?）**——收据带回显
`crop`/`crop_px`/`src`/`w`/`h`/`format`/`engine`；越界进 `bounds_warn`、`ashot_fonts`（v0.1.10，filter?——列已装字体族，收据
{ok, count, families}）、**`ashot_show`（v0.1.12，image/title/
out_dir 必填 + caption?/width?——用户可见展示，见上）**；**新增工具
需宿主重连后才出现在工具表**——与 CLI 同能力。**v0.2.6 起
`ashot_shot`/`ashot_annotate`/`ashot_cdp_shot` 的 `preview` 缺省 true**：
收据升级多内容块、附 ≤200KB JPEG 缩图（ImageContent，audience:user；
不想要就传 `preview=false` 省一次缩图进程与上下文）。ZCode 宿主实测（用户纠偏修正）：宿主把图转成**视觉块喂
模型**（agent 可直接看图自检标注，省 Read 大图）但**不渲染给用户**。
**v0.1.12 起用户看图走第五工具 `ashot_show`（image/title/out_dir
必填 + caption?/width?）或 CLI `show`**——数据 URL 内嵌 HTML 落
会话可视化目录，配 ::visualize 引用（唯一被证实的用户可见通道），
两通道分工勿混。**

**部署纪律（2026-10-28 实弹，v0.2.6 加检测）**：改了 Ashot 代码后，
宿主重启未必真换 MCP 进程（进程会赖着旧代码，如 screens 返回 0×0
假象）——杀掉 ashot_mcp.py 进程即可，宿主下次调用自动重拉新版；**进程在宿主侧不可见/不可杀时**（2026-10-29 实测：沙箱里看不到 python 子进程）就在宿主界面把该 MCP **断开→重连**，或重启宿主——工具表是连接时拉的，重连后新工具与新参数才会出现。
**v0.2.6 起每个收据都带 `ver`**：收据里的 ver 与你刚改的版本号不一致，
就说明还是旧进程。开发期更稳的做法：验证逻辑走 CLI（每次新进程），
MCP 只做最终验收。

## 标注形态分工
- **C 形态（已交付）**：JSON ops 批量标注——agent 的主用路（拿到截图后
  自己画框标注再交付用户）；
- **B 形态（v0.2 预留）**：tkinter 交互画布（人手画），调了会诚实报
  Not Implemented。
