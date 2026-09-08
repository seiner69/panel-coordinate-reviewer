# 画格坐标审核工具

一个在本机浏览器中审核纵向图像流候选区域的轻量工具。它把候选坐标叠加到原图上下文中，支持通过、驳回、类型调整、边界拖动、拆分、合并和自动保存，适合漫画画格、长截图区块、扫描页区域等人工复核任务。

## 亮点

- 使用零基、半开区间坐标：`x=[x0,x1)`、`y=[global_y0,global_y1)`。
- 在完整纵向图像流中显示候选及上下文，不需要预先生成每个候选的截图。
- 支持拖动四条边、按全局 Y 拆分、与相邻候选合并。
- 支持自定义候选类型、来源分段和跨来源提示。
- 通过状态修订号检测多窗口并发修改，阻止旧页面覆盖较新的审核结果。
- 审核状态以原子写入方式保存，降低中断造成 JSON 损坏的概率。
- 每次成功保存后追加一条最小化 JSONL 审计记录，只记录修订号、受影响候选和变化字段，不复制备注正文。
- HTTP 服务仅监听 `127.0.0.1`；前端对候选名称和来源名称使用文本节点，避免直接注入 HTML。

## 前置条件

- Python 3.9 或更高版本；
- Pillow 12.3.x，安装方式见下文；
- 一个现代浏览器。

## 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\create_example.py
python server.py
```

然后打开 `http://127.0.0.1:8765/`。默认加载仓库内的合成示例，不包含真实项目数据或第三方素材。

加载自己的数据：

```powershell
python server.py --data-dir D:\path\to\review-data --port 8765
```

数据目录至少包含：

```text
review-data/
├── project.json
├── candidates.json
└── stream.png
```

`project.json` 示例：

```json
{
  "title": "第一批区域审核",
  "stream_image": "stream.png",
  "candidates_file": "candidates.json",
  "state_file": "review-state.json",
  "context_margin": 600,
  "panel_types": ["single_panel", "composite_panel"],
  "sources": [
    {"name": "part-001", "global_y0": 0, "global_y1": 4000},
    {"name": "part-002", "global_y0": 4000, "global_y1": 8200}
  ]
}
```

`candidates.json` 示例：

```json
{
  "items": [
    {
      "provisional_id": "panel_0001",
      "x0": 12,
      "x1": 680,
      "global_y0": 120,
      "global_y1": 920,
      "panel_type": "single_panel"
    }
  ]
}
```

首次启动会在数据目录生成 `review-state.json`。之后的人工状态以该文件为准；若要重新开始，先备份并移走它。

成功保存还会在同一目录追加 `review-events.jsonl`。可以在 `project.json` 中用 `events_file` 改名，但路径必须留在数据目录内，且不能与图像、候选或状态文件重名。事件只描述 `added_item_ids`、`removed_item_ids`、`changed_fields_by_item` 等结构变化，不保存坐标值、状态值或备注内容；它适合定位何时发生了哪类修改，但不能代替完整状态备份。

## 操作方式

- `J` / `K` 或左右方向键：上一格、下一格；
- `A`：通过；`R`：驳回；`P`：恢复待审；
- `S`：按输入的全局 Y 拆分；
- `M`：与下一格合并；
- 鼠标拖动红框四边：修改坐标。

所有修改会自动保存。坐标越界、重复编号、未知类型和未知状态会被后端拒绝。

每次成功保存都会递增审核状态中的 `revision`。如果另一个浏览器窗口已经先保存，旧窗口会收到 HTTP 409 冲突提示，且旧数据不会写入文件；刷新页面取得最新状态后再重做当前修改。

## 已确认区域的只读保护

在自己的 `project.json` 中设置 `"locked_panel_ids": ["panel_0001"]`，再重启服务。编号必须真实存在且不重复；未设置时保留原来的全可编辑行为。

- 服务启动时，以现有 `review-state.json`（首次运行则为候选文件）建立锁定快照。锁定候选的坐标、类型、审核状态和备注不可修改，也不能删除、改编号、拆分或合并。
- 其他候选不能覆盖锁定区域；边缘相接允许。如果已有未锁定候选与锁定区域重叠，启动直接报错，不改写文件。
- 页面显示“只读”，禁用编辑控件、拖拽和相关快捷键；仍可查看图片、筛选及切换候选。后端同样强制校验，直接提交 HTTP 请求也不能绕过。
- 锁定名单只从本地配置读取，浏览器上传的同名字段不能解除锁定。要调整名单，请先停止服务、备份状态，修改配置后重启；锁定不是文件系统权限，拥有本地文件写权限的人仍可修改配置或状态。

这适用于“保留已确认区域，仅复审剩余候选”的工作流。功能整理日期：2026-09-08；未带入源项目的固定章节、名单、素材或私人审核状态。

## 目录结构

```text
.
├── server.py                 # 本机 HTTP 服务、校验和原子保存
├── web/                      # 无构建步骤的浏览器界面
├── example/                  # 合成配置与候选数据
├── scripts/create_example.py # 生成合成纵向示例图
├── tests/test_server.py      # 后端单元测试
└── requirements.txt
```

## 验证方式

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server.py scripts tests
node --check web\app.js
node --test tests/test_locked_ui.cjs
```

还可启动服务后检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8765/api/state | Select-Object -ExpandProperty StatusCode
```

## 已知限制

- 工具假设所有候选共享同一张纵向图像；暂不支持缩放级别不同的多图层画布。
- 浏览器会请求包含上下文的 PNG；超大宽度或超长候选会增加内存与响应时间。
- 合并操作以列表中的相邻项为对象，不分析图像语义。
- 当前没有账号、权限或多人合并机制，只适合可信本机环境；修订号能阻止静默覆盖，但冲突后的修改需要人工重做。
- `review-events.jsonl` 在状态文件成功落盘后追加，两份文件不是跨文件事务；磁盘故障可能造成最新状态已有而对应事件缺失。

## 来源与所有权状态

- 来源日期：2026-09-02。
- 该工具由一个项目专用画格审核界面泛化重建而来；公开版本删除了漫画名称、章节、绝对本机路径、外部提取器和真实素材，示例图完全由脚本合成。
- 代码与文档来自用户自己的 Codex 工作流整理，不包含已知第三方源代码。
- 本仓库未附带开源许可证。公开可见不等于授予复制、修改或再分发权；如需复用，请先取得仓库所有者许可。
