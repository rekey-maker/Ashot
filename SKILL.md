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
- `annotate <png> '<ops JSON>'`——对既有图标注，ops kind ∈
  **rect/ellipse/arrow/line/text（v0.1.7 起中文可标注；v0.1.9 起可选
  `font`=字体族名 / `bold`=粗体开关，缺省微软雅黑+粗体，仅矢量路生效，
  未安装字体名 GDI+ 静默回退默认字体——**先 `fonts <子串>` 核名再写
  font**）/mosaic/blur/
  step（自动递增编号）/number（显式编号 value）/spotlight（聚光灯 dim）/
  smarterase（智能擦除）**，坐标亦收 "x,y,w,h" 串（coords/area 键）。
  **每个 op 独立** `color:"#RRGGBB"` 与 `width`（粗细）；`arrow` 缺省=
  渐变实心箭头（v0.1.8 重校准：细杆恒定≈width + 1:1 细三角头，头长=
  头宽=3.5×width，短箭头长封顶 0.4×全长；端点定总长，杆=总长−头可
  自由伸缩；`"style":"line"` 回退旧直杆）；`rect` 可选 `radius`（圆角
  描边）。**width 用量**：4K 截图 10~14、1080p 4~6（width=杆像素粗细）。
  **渲染双后端（v0.1.7 矢量 / v0.1.8 收据）**：矢量形状走 GDI+
  （System.Drawing 抗锯齿，真矢量——边缘平滑无马赛克感，文字走微软
  雅黑）；GDI+ 失败自动降级纯像素画布（硬边）。收据 `backend` 只反映
  形状渲染后端（`gdi+`=矢量成功 / `pixel`=降级或纯像素，混合 ops 仍
  gdi+），`pixel_ops`=像素操作数量；**像素 ops（mosaic/blur/spotlight/
  smarterase）恒在形状之后叠加，与 ops 数组位置无关**（spotlight 排
  第 1 也会把画在框外的形状压暗）。
  例：
  `annotate shot.png '[{"kind":"rect","x":10,"y":10,"w":200,"h":50,
  "width":8,"color":"#07C160","radius":12},
  {"kind":"arrow","x1":300,"y1":50,"x2":200,"y2":30,"width":10,
  "color":"#FF3B30"},
  {"kind":"text","x":20,"y":80,"text":"这里有问题","size":28,
  "color":"#FFFFFF"}]'`
- `fonts [filter]`（v0.1.10）——列出已装字体族（英文规范名，双语过滤：
  "kai"/"楷体" 都能查到 KaiTi）；族名走 stdout、计数走 stderr。
- `show <image> --title T [--caption C] [--out-dir D] [--width N]`
  （v0.1.12）——图片→数据 URL 内嵌 HTML（用户可见展示，::visualize
  场景 out_dir 传会话可视化目录）；html 路径 stdout、preview 信息
  stderr。
- `cdp-tabs --port P` / `cdp-shot [--port P] [--index N] [--viewport]`
  （v0.2.0）——**CDP 浏览器捕获**：无头/有头通吃、与 AI 宿主无关
  （任何宿主启动的 Chromium 系，含 --remote-debugging 启动的无头
  浏览器）；--port 缺省自动发现（进程枚举→DevToolsActivePort→常见
  端口）；cdp-shot 缺省 captureBeyondViewport 全页。Chrome 136+ 默认
  profile 拒远程调试——浏览器须用非默认 --user-data-dir 启动。
- **CDP 输入注入**（v0.2.1/0.2.3）：`cdp-key <键> [--modifiers ctrl+shift]
  [--text T]`（回车/Tab/方向键/F1-F12/符号/任意字符/组合快捷键，
  rawKeyDown+char 双发；未知键收据 unresolved_keys 亮牌）、
  `cdp-wheel --dx --dy`（滚轮）、`cdp-click x y [--button]`（单击，
  left/right/middle）、`cdp-dblclick x y [--count]`（双击/三连击）、
  `cdp-drag x1 y1 x2 y2 [--steps]`（拖拽）、`cdp-type <文本> [--x --y]`
  （**填表整段输入**，Input.insertText 粘贴式含中文，不逐键击）——
  全部 --port/--index/--ws 同 cdp-shot。注入的是 CDP isTrusted 事件
  （页面无法区分），**只进指定标签页、不占用户物理键鼠**（自动化与
  用户操作天然隔离）；insertText 落点=目标标签页当前焦点元素
  （--x/--y 先点击聚焦）。
- `screens`——列出显示器（非 Windows 平台如实报「批2」）。

## MCP（ashot 域名，宿主注册后可用）
`ashot_shot`（mode/screen/out/clip/keep/retention_days/area；收据带
`all_black`——远程会话黑帧自检，true=如实报「当前会话截不出」）、
`ashot_annotate`（image/ops/out；**缺省写 <原名>_annotated.png，绝不
覆盖原图**）、`ashot_fonts`（v0.1.10，filter?——列已装字体族，收据
{ok, count, families}）、**`ashot_show`（v0.1.12，image/title/
out_dir 必填 + caption?/width?——用户可见展示，见上）**；**新增工具
需宿主重连后才出现在工具表**——与 CLI 同能力。**v0.1.11 起两工具均可选 `preview`=true：收据升级多
内容块、附 1200px JPEG 缩图（ImageContent，audience:user；≤500KB
梯次降档）。ZCode 宿主实测（用户纠偏修正）：宿主把图转成**视觉块喂
模型**（agent 可直接看图自检标注，省 Read 大图）但**不渲染给用户**。
**v0.1.12 起用户看图走第五工具 `ashot_show`（image/title/out_dir
必填 + caption?/width?）或 CLI `show`**——数据 URL 内嵌 HTML 落
会话可视化目录，配 ::visualize 引用（唯一被证实的用户可见通道），
两通道分工勿混。**

**部署纪律（2026-10-28 实弹）**：改了 Ashot 代码后，宿主重启未必真换
MCP 进程（进程会赖着旧代码，如 screens 返回 0×0 假象）——杀掉
ashot_mcp.py 进程即可，宿主下次调用自动重拉新版。

## 标注形态分工
- **C 形态（已交付）**：JSON ops 批量标注——agent 的主用路（拿到截图后
  自己画框标注再交付用户）；
- **B 形态（v0.2 预留）**：tkinter 交互画布（人手画），调了会诚实报
  Not Implemented。
