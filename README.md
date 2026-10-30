# Ashot —— agent 友好的桌面截图与标注工具

零第三方依赖的 Windows 桌面截图 + 标注工具（Python 标准库 + 系统自带
GDI+）。为 AI agent 设计：CLI 与 MCP 双入口，JSON ops 批量标注，矢量
抗锯齿渲染，收据如实亮牌。当前版本 **v0.7.0**，MCP 23 个工具、25 个 CLI 子命令，**MIT 开源**。

> **画图定位精度（实测 2026-10-29）**：桌面 rect 与浏览器 selector/ref
> 画框的坐标误差都是 **0px**；可见的 ±2px 是描边线宽的一半。详见文末
> 「画图与定位精度」。

## 安装与要求

- Python **3.9+**（实测 3.12）；**零第三方依赖**，无需 `pip install`
- 桌面截图仅 **Windows 10/11**；CDP 浏览器捕获/操作跨平台（Mac 桌面路属批2）
- 仓库根直接运行：`python -m ashot.cli --help` / `python ashot_mcp.py`

## 能力

- **截图**：全桌面 / 单屏 / 前台窗口 / 任意区域；GDI 主路 + PowerShell
  兜底自动降级（失败原因 `gdi_error` 如实带出）；前台窗口走 **DWM 可见
  帧界**（v0.2.6，不再把阴影/不可见 resize 边截进来）；进程级 DPI 感知；
  多屏枚举；全黑帧检测（远程会话自检）；**截完可直接
  `--scale/--max-side/--jpg`**（v0.4.0，不必再单独跑一次 resize）
- **标注**（v0.1.7 起矢量形状走 GDI+ 抗锯齿，失败自动降级纯像素画布，
  收据 `backend` 字段如实标注）：
  `rect`（可选圆角）/ `ellipse` / `line` / **`curve`（三次贝塞尔）/
  `arc`（椭圆弧，起止角）/ `polyline`（折线）**——v0.4.1 新增，与
  箭头同一条原理（Python 采样成点列 → GDI+ 抗锯齿描边）/ `arrow`（缺省渐变实心箭头，
  细杆恒定 + 1:1 细三角头，短箭头长封顶）/ `text`（中文；v0.1.9 起可选
  `font`/`bold`，缺省微软雅黑粗体；v0.2.6 起可带 `w` 由 GDI+ 原生
  换行，越界进 `bounds_warn` 而不是悄悄被裁）/ `mosaic` / `blur` /
  `step`（同次调用自动递增编号）/ `number` / `spotlight`（聚光灯压暗）/
  `smarterase`（边缘均值色填充）
  - 每个 op 独立 `color`（#RRGGBB）与 `width`（粗细，**所有描边原语**都
    支持，可给小数如 2.5；`<=0` 或 `>1000` 报错）。箭头/曲线的 width
    语义：箭头=头部粗细基准，曲线=笔宽
  - 像素操作（mosaic/blur/spotlight/smarterase）走纯标准库像素画布
- **输入/坐标便利**（v0.5.0）：`annotate`/`hash`/`diff`/`compose`
  现在都吃 **JPEG**（GDI+ 转码，零依赖）；`annotate --dpr` 把 CSS 坐标
  换算成物理像素（与 `element` 闭环）；`info` 看尺寸；`resize --dir`
  目录批处理；`annotate --template` 复用标注模板
- **裁切 / 缩放 / JPEG 交付**（v0.4.0，补 imgtool 的缺口）：对**已有
  图片**裁切（`crop --box x,y,w,h`）、缩放（`resize --scale/--width/
  --max-side`，max_side 只缩不放）、直接出 JPEG（`--jpg 85`）；
  `compose` 一条命令走完「截屏/读图→裁→缩→标注→存盘」。引擎=系统
  .NET System.Drawing（与矢量渲染同款，**不装 PIL**）；越界夹到边界
  并写 `bounds_warn`，收据回显 `crop`/`crop_px`（box 写反一眼可见）
- **浏览器捕获**（v0.2.0）：纯标准库 CDP 客户端——`cdp-tabs`/
  `cdp-shot` 抓任何 Chromium 系浏览器的标签页（**无头/有头通吃，与
  AI 宿主无关**），captureBeyondViewport 全页，自动发现调试端口；
  **超长页自动滚动拼接**（v0.2.6：先试单张，被拒才逐屏拼；收据
  `stitched/shots`，`--no-stitch` 关闭；v0.2.8 拼接前隐藏 fixed/sticky，
  收据 `fixed_hidden`）
- **浏览器操作**（v0.2.1-0.2.5）：点击/双击/拖拽/滚轮/全键盘/组合
  快捷键/整段填表（insertText 含中文）；**人类化鼠标轨迹**（三次
  贝塞尔+缓动+微抖动，节奏三档可调（fast/normal/**captcha** 900~2600ms，
  过滑块验证码用 captcha 档；`--total-ms` 显式优先），拖拽缺省**受轨道
  约束**（垂直偏移 ≤2.5px，520px 也不再漂 50px），`--free` 回自由弧线、
  `--teleport` 退回瞬移）——事件只进指定标签页，与用户键鼠天然隔离
- **后台标签页安全**（v0.7.0）：截图/点击前查 `visibilityState`，
  hidden 自动 `bringToFront`，收据亮 `activated`/`frame_stale_risk`；
  `--no-activate` 可拒绝（宁报错不交假图）；click/drag 带
  `dispatch_ms`/`per_event_ms`/`slow_ack`；`snapshot(root=…)` 只扫子树
- **定位精度**（v0.6.4 实测）：桌面/浏览器画框坐标误差 **0px**，
  selector/ref 与元素矩形完全对齐（±2px 只是线宽一半）
- **通用原语**（v0.2.7，非验证码专用）：**图像指纹/差异**（sha256 +
  dHash/aHash + YIQ 差异/bbox/差异图）、**元素矩形+可见性**（视口 CSS
  像素、checkVisibility、视口交集、中心遮挡、pointer-events）、
  **iframe 坐标映射**（同源任意深度、跨域同进程、**跨站 OOPIF**；可见
  比例按「主视口 ∩ iframe 内容框」裁剪，iframe 外不会被算成可见；
  v0.2.8 补 OOPIF/裁剪）
- **交付**：落盘 / 剪贴板阅后即焚（`--clip`）/ 缺省 30 天 retention
  顺手清理旧图
- **MCP**：stdio JSON-RPC 2.0，二十三工具 `ashot_shot` / `ashot_annotate` /
  `ashot_screens` / `ashot_fonts`（v0.1.10 起）/ `ashot_show`（v0.1.12
  起）/ `ashot_cdp_tabs` + `ashot_cdp_shot`（v0.2.0）/ `ashot_cdp_key`
  + `ashot_cdp_wheel` + `ashot_cdp_click` + `ashot_cdp_drag`（v0.2.1）/
  `ashot_cdp_dblclick` + `ashot_cdp_type`（v0.2.3）/ `ashot_cdp_eval` +
  `ashot_cdp_view`（v0.2.5）/ `ashot_hash` + `ashot_diff` +
  `ashot_element` + `ashot_frames` + `ashot_frame_element`（v0.2.7-0.2.8）/ `ashot_snapshot`（v0.6.0）/ `ashot_crop` + `ashot_resize`
  （v0.4.0，裁切/缩放/JPEG）。**22 工具覆盖 CLI 的主要能力；
  `compose`/`info` 仅 CLI**；每个收据带 `ver`（识破旧进程）

## 用法

```bash
python -m ashot.cli shot --out shot.png          # 全桌面
python -m ashot.cli shot --max-side 1600 --jpg 85 --out small.jpg
                                                 # 截完即缩 + 压 JPEG
python -m ashot.cli shot area --area 100 100 800 500
python -m ashot.cli screens                      # 列显示器
python -m ashot.cli fonts kai                    # 列已装字体族（text 的 font 先查后用）
python -m ashot.cli show shot.png --title my-shot \
  --out-dir ./out                                # 图片→内嵌 HTML（用户可见展示）
python -m ashot.cli hash shot.png --algo dhash   # 图像指纹（sha/dhash/ahash）
python -m ashot.cli diff a.png b.png --out d.png # 两图差异（YIQ+bbox+差异图）
python -m ashot.cli element "#submit"            # 元素视口矩形+可见性（CSS px）
python -m ashot.cli frames                       # frame 树（含 iframe 矩形）
python -m ashot.cli annotate shot.png '[
  {"kind":"rect","x":10,"y":10,"w":200,"h":50,"width":8,
   "color":"#07C160","radius":12},
  {"kind":"arrow","x1":300,"y1":50,"x2":200,"y2":30,
   "width":10,"color":"#DC2626"},
  {"kind":"text","x":20,"y":80,"text":"这里有问题","size":28,
   "color":"#111827","font":"KaiTi","bold":false}]'
python -m ashot.cli crop shot.png --box 100,80,800,600 --scale 1.2 \
  --out crop.png                               # 对已有图片裁切+放大
python -m ashot.cli resize shot.png --max-side 1600 --jpg 85 \
  --out small.jpg                              # 只缩不放 + JPEG
python -m ashot.cli compose --area 100 100 1200 800 --box 0,0,900,600 \
  --rect 40,40,300,200 --text 60,560:这里是重点 --jpg 85 --out out.jpg
```

## MCP 接入

stdio JSON-RPC 2.0（协议 2024-11-05），二十三工具（覆盖 CLI 主要能力；
`compose`/`info` 仅 CLI）：每个收据
都带 `ver`——文件版本号对了但进程还是旧的，一眼识破；v0.2.6 起）：

| 工具 | 作用 |
|---|---|
| `ashot_shot` | 截图（full/screen/win/area；**v0.4.0 起可传 `scale`/`max_side`/`jpg`/`quality`——截完直接缩放/转 JPEG**；收据带 `all_black` 黑帧自检、`box_source` 区域来源、`gdi_error` 降级原因；v0.2.6 起 `preview` **缺省 true**，附 ≤200KB JPEG 缩图 ImageContent） |
| `ashot_crop` / `ashot_resize` | 裁切 / 缩放 / 转 JPEG（v0.4.0；crop 的 box 是 **x,y,w,h**，dpr 传 CSS 坐标换算，越界进 `bounds_warn`） |
| `ashot_annotate` | JSON ops 批量标注（PNG/JPEG；`dpr` 换算 CSS 坐标；收据带 `backend`/`pixel_ops`/`bounds_warn`/`degrade_reason`；text 可带 `w` 自动换行；preview 缺省 true） |
| `ashot_screens` | 列显示器 |
| `ashot_fonts` | 列已装字体族（text 的 font 先查后用；v0.1.10 起） |
| `ashot_show` | 图片→数据 URL 内嵌 HTML（用户可见展示；v0.1.12 起） |
| `ashot_hash` / `ashot_diff` | 图像指纹 / 两图差异（v0.2.7；sha/dhash/ahash、YIQ+bbox+差异图） |
| `ashot_element` / `ashot_frames` / `ashot_frame_element` | 元素视口矩形+可见性 / frame 树 / iframe 内元素映射（v0.2.7） |
| `ashot_snapshot` | 页面结构快照：`[ref=eN] [box=…]` + ref→选择器（v0.6.0；annotate 可用 `selector`/`ref` 定位） |
| `ashot_cdp_tabs` | 列 CDP 浏览器 page 标签页（自动发现端口；v0.2.0 起） |
| `ashot_cdp_shot` | CDP 标签页截图（无头/有头通吃，全页；v0.2.0 起） |
| `ashot_cdp_eval` / `ashot_cdp_view` | 执行 JS 取值 / 视口信息（vw/vh/dpr；v0.2.5） |
| `ashot_cdp_key` / `ashot_cdp_wheel` / `ashot_cdp_click` / `ashot_cdp_drag` / `ashot_cdp_dblclick` / `ashot_cdp_type` | 浏览器操作：按键/组合键、滚轮、单击（人类化轨迹）、拖拽（人类化轨迹）、双击、整段填表（v0.2.1-0.2.5 起；v0.2.5 加 eval/view 与节奏档） |

注册到宿主（示例为 ZCode 的 `mcp.servers.ashot`；路径基准=本文件
所在目录即仓库根）：

```json
{
  "ashot": {
    "type": "stdio",
    "command": "python",
    "args": ["ashot_mcp.py"],
    "cwd": "<仓库根>"
  }
}
```

- `<仓库根>` 即本文件所在目录；路径含空格无需引号（`args` 是数组，
  不经 shell）
- **改码后宿主重启未必真换 MCP 进程**（进程会赖旧代码，症状如
  screens 返回 0×0）——杀掉 `ashot_mcp.py` 进程即可，宿主下次调用
  自动重拉；v0.2.6 起每个收据都带 `ver`，新旧进程一秒识破
- **新增工具需宿主重连后才出现在工具表**（工具表是连接时拉的）

## 测试

```bash
python -m pytest tests/ -q          # 185 项（E2E 默认 skip）
$env:ASHOT_E2E=1; python -m pytest tests/test_browser_e2e.py -q   # 真浏览器 4 项
```

188 项（+6 项可选 E2E）：编码/解码 roundtrip、全部标注原语、箭头几何比例与多边形简单性、
GDI 句柄守恒（GetGuiResources 计数）、抗锯齿中间色分水岭、收据契约
（backend/pixel_ops/bounds_warn/degrade_reason/ver）、text 换行与越界
告警、字库查询与缓存失效、preview 图片收据（缺省开）、show 展示与
caption 转义、CDP 发现降级/多实例拒绝/坐标语义、MCP 坏帧韧性、
retention 边界等；v0.4.0 另加 `tests/test_transform.py` 30 项（裁切逐像素、越界告警、dpr、先裁后缩、JPEG 魔数/体积、CLI/MCP 三面）。

> Windows 上若 `tmp_path` 报 PermissionError（pytest 以 `mode=0o700`
> 建目录，本机 ACL 会拒读），加 `--basetemp=<工作区内新目录>` 即可；
> 这与项目代码无关。

## 画图与定位精度（2026-10-29 实测）

- **桌面截图** 3840×2160，`rect(100,100,200,100,width=6)` → 墨迹 bbox
  `97,97–303,203`，**坐标误差 0**（±3 是线宽一半）。
- **浏览器 dpr=2**：`snapshot` 的 box 与 `element_rect` 5/5 **最大 0px**；
  selector 画框中心 **0**、边缘 ±2（线宽 4 的一半）；`pad` 与
  `space=document` 的 scroll×dpr 偏移均 **0 误差**。
- **真实页 example.com**：`ref` 画 `<p>` 边框中心 **0**（边缘 ±2）。
- 交互：`click+verify` 生效、原生 range `8→82`、`scrollables` 只命中
  `overflow:auto` 容器。

> 结论：坐标本身不漂；肉眼看到的 ±2px 是描边线宽的一半，不是定位误差。

## 设计原则

- **零第三方依赖**：标准库 ctypes/zlib + 系统自带 .NET（GDI+ 渲染），
  不装 PIL 不装 Playwright
- **如实亮牌**：主路失败降级、黑帧、后端选择，全部进收据，绝不静默
- **模块纪律**：capture（只抓像素）/ annotate（只标注）/ output（只交付）
  / mcp（零业务只转发）


## 平台与边界

| 能力 | 状态 |
|---|---|
| Windows 桌面截图（全屏/单屏/窗口/区域）、标注、剪贴板 | ✓ |
| 裁切 / 缩放 / JPEG 交付（对已有图片） | ✓（.NET GDI+；Mac 随批2） |
| CDP 浏览器捕获/操作（无头/有头、任何宿主拉起的 Chromium） | ✓ 跨平台 |
| 超长页滚动拼接（含隐藏吸顶元素） | ✓ |
| 元素矩形/可见性、同源+跨域+跨站 OOPIF iframe 映射 | ✓（嵌套跨域仍不支持） |
| macOS 桌面捕获 | ✗ 设计态（v0.2.0 批2） |
| Windows 窗口枚举 / PrintWindow 后台窗口捕获 | ✗ 设计态（v0.2.0 批3） |
| 验证码识别 / OCR | ✗ **刻意不做**（Ashot 只提供视觉/DOM 原语） |
| 网络上传 | ✗ 永不做（隐私即卖点） |

## 目录结构

```
ashot/
├── capture.py / output.py      # 抓像素 / 交付（PNG、剪贴板、retention）
├── annotate.py / vector.py     # 像素画布 / 几何编译
├── annotate_gdi.py + _gdi_render.ps1  # GDI+ 矢量渲染（纯 ASCII 纪律）
├── cdp.py                      # CDP 客户端（WS/截图/输入/滚动拼接）
├── dom.py                      # 元素矩形+可见性 / iframe 坐标映射（v0.2.7+）
├── vision.py                   # 图像指纹与差异（v0.2.7）
├── transform.py + _gdi_image.ps1  # 裁切/缩放/JPEG（v0.4.0，纯 ASCII PS）
├── geometry.py                 # 曲线/弧线采样（v0.4.1，纯数学可单测）
├── fonts.py / show.py / mcp.py / cli.py / _coerce.py
├── docs/design/                # 设计文档（按版本）
├── docs/review/                # 审查/核查报告
├── tests/test_ashot.py         # 136 项（主回归锁）
├── tests/test_transform.py     # 30 项（裁切/缩放/JPEG）
└── tests/test_shapes.py        # 19 项（曲线/弧线/折线）
```

## 许可证

[MIT](LICENSE) © 2026 rekey-maker —— 可自由使用、修改、分发、商用，保留版权声明即可。

## 版本与文档

- 版本史：[CHANGELOG.md](CHANGELOG.md)；设计文档索引：[docs/design/README.md](docs/design/README.md)
- 审查与修复证据：[docs/review/](docs/review/)
- 当前 0.6.1：MCP 精确定位（snapshot ref / selector 标注 / 预览 to_source）；
  并修复 v0.6.0 审查发现的问题（见 CHANGELOG）
