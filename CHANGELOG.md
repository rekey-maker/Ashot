# 更新日志（Changelog）

所有显著变更记录于此。格式参考 Keep a Changelog，版本号遵循 SemVer。

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
