# 更新日志（Changelog）

所有显著变更记录于此。格式参考 Keep a Changelog，版本号遵循 SemVer。

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
