# 画格坐标审核工具

一个在本机浏览器中审核纵向图像流候选区域的轻量工具。它把候选坐标叠加到原图上下文中，支持通过、驳回、类型调整、边界拖动、拆分、合并和自动保存，适合漫画画格、长截图区块、扫描页区域等人工复核任务。

## 亮点

- 使用零基、半开区间坐标：`x=[x0,x1)`、`y=[global_y0,global_y1)`。
- 在完整纵向图像流中显示候选及上下文，不需要预先生成每个候选的截图。
- 支持拖动四条边、按全局 Y 拆分、与相邻候选合并。
- 支持自定义候选类型、来源分段和跨来源提示。
- 通过状态修订号检测多窗口并发修改，阻止旧页面覆盖较新的审核结果。
- 审核状态以原子写入方式保存，降低中断造成 JSON 损坏的概率。
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

## 操作方式

- `J` / `K` 或左右方向键：上一格、下一格；
- `A`：通过；`R`：驳回；`P`：恢复待审；
- `S`：按输入的全局 Y 拆分；
- `M`：与下一格合并；
- 鼠标拖动红框四边：修改坐标。

所有修改会自动保存。坐标越界、重复编号、未知类型和未知状态会被后端拒绝。

每次成功保存都会递增审核状态中的 `revision`。如果另一个浏览器窗口已经先保存，旧窗口会收到 HTTP 409 冲突提示，且旧数据不会写入文件；刷新页面取得最新状态后再重做当前修改。

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

## 来源与所有权状态

- 来源日期：2026-09-02。
- 该工具由一个项目专用画格审核界面泛化重建而来；公开版本删除了漫画名称、章节、绝对本机路径、外部提取器和真实素材，示例图完全由脚本合成。
- 代码与文档来自用户自己的 Codex 工作流整理，不包含已知第三方源代码。
- 本仓库未附带开源许可证。公开可见不等于授予复制、修改或再分发权；如需复用，请先取得仓库所有者许可。
