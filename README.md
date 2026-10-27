# Ashot —— agent 友好的桌面截图与标注工具

零第三方依赖的 Windows 桌面截图 + 标注工具（Python 标准库 + 系统自带
GDI+）。为 AI agent 设计：CLI 与 MCP 双入口，JSON ops 批量标注，矢量
抗锯齿渲染，收据如实亮牌。

## 能力

- **截图**：全桌面 / 单屏 / 前台窗口 / 任意区域；GDI 主路 + PowerShell
  兜底自动降级；进程级 DPI 感知；多屏枚举；全黑帧检测（远程会话自检）
- **标注**（v0.1.7 起矢量形状走 GDI+ 抗锯齿，失败自动降级纯像素画布，
  收据 `backend` 字段如实标注）：
  `rect`（可选圆角）/ `ellipse` / `line` / `arrow`（缺省渐变实心箭头，
  尾细头胖+实心三角头）/ `text`（中文，系统字体）/ `mosaic` / `blur` /
  `step`（同次调用自动递增编号）/ `number` / `spotlight`（聚光灯压暗）/
  `smarterase`（边缘均值色填充）
  - 每个 op 独立 `color`（#RRGGBB）与 `width`（粗细）
  - 像素操作（mosaic/blur/spotlight/smarterase）走纯标准库像素画布
- **交付**：落盘 / 剪贴板阅后即焚（`--clip`）/ 缺省 30 天 retention
  顺手清理旧图
- **MCP**：stdio JSON-RPC，三工具 `ashot_shot` / `ashot_annotate` /
  `ashot_screens`，与 CLI 同能力

## 用法

```bash
python -m ashot.cli shot --out shot.png          # 全桌面
python -m ashot.cli shot area --area 100 100 800 500
python -m ashot.cli screens                      # 列显示器
python -m ashot.cli annotate shot.png '[
  {"kind":"rect","x":10,"y":10,"w":200,"h":50,"width":8,
   "color":"#07C160","radius":12},
  {"kind":"arrow","x1":300,"y1":50,"x2":200,"y2":30,
   "width":10,"color":"#DC2626"},
  {"kind":"text","x":20,"y":80,"text":"这里有问题","size":28,
   "color":"#111827"}]'
```

## 测试

```bash
python -m pytest tests/ -q
```

40 项：编码/解码 roundtrip、全部标注原语、GDI 句柄守恒（GetGuiResources
计数）、抗锯齿中间色分水岭、MCP 坏帧韧性、retention 边界等。

## 设计原则

- **零第三方依赖**：标准库 ctypes/zlib + 系统自带 .NET（GDI+ 渲染），
  不装 PIL 不装 Playwright
- **如实亮牌**：主路失败降级、黑帧、后端选择，全部进收据，绝不静默
- **模块纪律**：capture（只抓像素）/ annotate（只标注）/ output（只交付）
  / mcp（零业务只转发）
