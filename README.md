# Ashot —— agent 友好的桌面截图与标注工具

零第三方依赖的 Windows 桌面截图 + 标注工具（Python 标准库 + 系统自带
GDI+）。为 AI agent 设计：CLI 与 MCP 双入口，JSON ops 批量标注，矢量
抗锯齿渲染，收据如实亮牌。

## 能力

- **截图**：全桌面 / 单屏 / 前台窗口 / 任意区域；GDI 主路 + PowerShell
  兜底自动降级（失败原因 `gdi_error` 如实带出）；前台窗口走 **DWM 可见
  帧界**（v0.2.6，不再把阴影/不可见 resize 边截进来）；进程级 DPI 感知；
  多屏枚举；全黑帧检测（远程会话自检）
- **标注**（v0.1.7 起矢量形状走 GDI+ 抗锯齿，失败自动降级纯像素画布，
  收据 `backend` 字段如实标注）：
  `rect`（可选圆角）/ `ellipse` / `line` / `arrow`（缺省渐变实心箭头，
  细杆恒定 + 1:1 细三角头，短箭头长封顶）/ `text`（中文；v0.1.9 起可选
  `font`/`bold`，缺省微软雅黑粗体；v0.2.6 起可带 `w` 由 GDI+ 原生
  换行，越界进 `bounds_warn` 而不是悄悄被裁）/ `mosaic` / `blur` /
  `step`（同次调用自动递增编号）/ `number` / `spotlight`（聚光灯压暗）/
  `smarterase`（边缘均值色填充）
  - 每个 op 独立 `color`（#RRGGBB）与 `width`（粗细）
  - 像素操作（mosaic/blur/spotlight/smarterase）走纯标准库像素画布
- **浏览器捕获**（v0.2.0）：纯标准库 CDP 客户端——`cdp-tabs`/
  `cdp-shot` 抓任何 Chromium 系浏览器的标签页（**无头/有头通吃，与
  AI 宿主无关**），captureBeyondViewport 全页，自动发现调试端口；
  **超长页自动滚动拼接**（v0.2.6：先试单张，被拒才逐屏拼；收据
  `stitched/shots`，`--no-stitch` 关闭）
- **浏览器操作**（v0.2.1-0.2.5）：点击/双击/拖拽/滚轮/全键盘/组合
  快捷键/整段填表（insertText 含中文）；**人类化鼠标轨迹**（三次
  贝塞尔+缓动+微抖动，节奏三档可调（fast/normal/**captcha** 900~2600ms，
  过滑块验证码用 captcha 档；`--total-ms` 显式优先），拖拽缺省**受轨道
  约束**（垂直偏移 ≤2.5px，520px 也不再漂 50px），`--free` 回自由弧线、
  `--teleport` 退回瞬移）——事件只进指定标签页，与用户键鼠天然隔离
- **通用原语**（v0.2.7，非验证码专用）：**图像指纹/差异**（sha256 +
  dHash/aHash + YIQ 差异/bbox/差异图）、**元素矩形+可见性**（视口 CSS
  像素、checkVisibility、视口交集、中心遮挡、pointer-events）、
  **iframe 坐标映射**（同源任意深度、跨域同进程、跨站 OOPIF；可见比例按 iframe 边界裁剪）
- **交付**：落盘 / 剪贴板阅后即焚（`--clip`）/ 缺省 30 天 retention
  顺手清理旧图
- **MCP**：stdio JSON-RPC 2.0，十五工具 `ashot_shot` / `ashot_annotate` /
  `ashot_screens` / `ashot_fonts`（v0.1.10 起）/ `ashot_show`（v0.1.12
  起）/ `ashot_cdp_tabs` + `ashot_cdp_shot`（v0.2.0）/ `ashot_cdp_key`
  + `ashot_cdp_wheel` + `ashot_cdp_click` + `ashot_cdp_drag`（v0.2.1）/
  `ashot_cdp_dblclick` + `ashot_cdp_type`（v0.2.3）/ `ashot_cdp_eval` +
  `ashot_cdp_view`（v0.2.5）/ `ashot_hash` + `ashot_diff` +
  `ashot_element` + `ashot_frames` + `ashot_frame_element`（v0.2.7），与 CLI 同能力

## 用法

```bash
python -m ashot.cli shot --out shot.png          # 全桌面
python -m ashot.cli shot area --area 100 100 800 500
python -m ashot.cli screens                      # 列显示器
python -m ashot.cli fonts kai                    # 列已装字体族（text 的 font 先查后用）
python -m ashot.cli show shot.png --title my-shot \
  --out-dir ./out                                # 图片→内嵌 HTML（用户可见展示）
python -m ashot.cli annotate shot.png '[
  {"kind":"rect","x":10,"y":10,"w":200,"h":50,"width":8,
   "color":"#07C160","radius":12},
  {"kind":"arrow","x1":300,"y1":50,"x2":200,"y2":30,
   "width":10,"color":"#DC2626"},
  {"kind":"text","x":20,"y":80,"text":"这里有问题","size":28,
   "color":"#111827","font":"KaiTi","bold":false}]'
```

## MCP 接入

stdio JSON-RPC 2.0（协议 2024-11-05），二十工具与 CLI 同能力（每个收据
都带 `ver`——文件版本号对了但进程还是旧的，一眼识破；v0.2.6 起）：

| 工具 | 作用 |
|---|---|
| `ashot_shot` | 截图（full/screen/win/area；收据带 `all_black` 黑帧自检、`box_source` 区域来源、`gdi_error` 降级原因；v0.2.6 起 `preview` **缺省 true**，附 ≤200KB JPEG 缩图 ImageContent） |
| `ashot_annotate` | JSON ops 批量标注（收据带 `backend`/`pixel_ops`/`bounds_warn` 越界告警/`degrade_reason` 降级原因；text 可带 `w` 自动换行；preview 缺省 true） |
| `ashot_screens` | 列显示器 |
| `ashot_fonts` | 列已装字体族（text 的 font 先查后用；v0.1.10 起） |
| `ashot_show` | 图片→数据 URL 内嵌 HTML（用户可见展示；v0.1.12 起） |
| `ashot_hash` / `ashot_diff` | 图像指纹 / 两图差异（v0.2.7；sha/dhash/ahash、YIQ+bbox+差异图） |
| `ashot_element` / `ashot_frames` / `ashot_frame_element` | 元素视口矩形+可见性 / frame 树 / iframe 内元素映射（v0.2.7） |
| `ashot_cdp_tabs` | 列 CDP 浏览器 page 标签页（自动发现端口；v0.2.0 起） |
| `ashot_cdp_shot` | CDP 标签页截图（无头/有头通吃，全页；v0.2.0 起） |
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
python -m pytest tests/ -q
```

108 项：编码/解码 roundtrip、全部标注原语、箭头几何比例与多边形简单性、
GDI 句柄守恒（GetGuiResources 计数）、抗锯齿中间色分水岭、收据契约
（backend/pixel_ops/bounds_warn/degrade_reason/ver）、text 换行与越界
告警、字库查询与缓存失效、preview 图片收据（缺省开）、show 展示与
caption 转义、CDP 发现降级/多实例拒绝/坐标语义、MCP 坏帧韧性、
retention 边界等。

> Windows 上若 `tmp_path` 报 PermissionError（pytest 以 `mode=0o700`
> 建目录，本机 ACL 会拒读），加 `--basetemp=<工作区内新目录>` 即可；
> 这与项目代码无关。

## 设计原则

- **零第三方依赖**：标准库 ctypes/zlib + 系统自带 .NET（GDI+ 渲染），
  不装 PIL 不装 Playwright
- **如实亮牌**：主路失败降级、黑帧、后端选择，全部进收据，绝不静默
- **模块纪律**：capture（只抓像素）/ annotate（只标注）/ output（只交付）
  / mcp（零业务只转发）
