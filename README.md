# 个人图片批量处理工具箱 v1.0.0

离线桌面工具，基于 `pywebview + 本地 HTML/CSS/JS + Python`，封装 `script/` 下脚本能力，面向 Windows 本地批处理场景。

### 功能模块

| 界面任务名 | 对应脚本 | 说明 |
|------|------|------|
| `bgr2rgb` | `script/bgr2rgb.py` | 颜色通道转换（RGB -> BGR） |
| `rename2` | `script/rename2.py` | 图片 + JSON 批量重命名 |
| `select_diverse` | `script/select_diverse.py` | 多样性筛图（pHash） |
| `json_path` | `script/更改json路径.py` | JSON 的 `imagePath` 批量修复 |
| `reorder_labels` | `script/reorder_labels.py` | JSON 标注顺序重排 |
| `synthesize` | `script/synthesize.py` | 智能合成标注（物体 + 背景图 + LabelMe JSON） |

### 执行模式

1. `安全复制`（默认）：只写输出目录，不改原目录。
2. `原地修改`：执行前强制备份，再写入原目录。

### 合成标注（synthesize）规则

将带标注的物体合成到背景图中，自动更新 LabelMe JSON，包含以下行为：

- 自动抠图：rembg（u2net / u2net_small）
- 智能放置：地面区域优先，障碍物避让
- 随机增强：旋转 + 水平镜像
- 自动标注：生成多边形标注
- 源图目录规则：
  - 源图全部带 JSON 且唯一 label：自动带出`源标注标签`和`合成后标注标签`
  - 源图全部不带 JSON：必须填写`合成后标注标签`，`源标注标签`不可用
  - 目录混合（部分带 JSON）或 JSON label 不一致：直接阻断并提示整理目录

### 当前限制

- `系统设置`按钮当前为占位入口，点击统一提示`系统设置还在开发中`，尚未开放配置能力。

### 推荐环境（uv）

```bash
uv sync --dev
```

### 启动

```bash
uv run python main.py
```

### 运行测试

```bash
uv run python -m pytest -q
```

### pip 兜底方案（无 uv 时）

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

### 打包 EXE（Windows）

```bash
.\.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name ImgToolbox --add-data "ui;ui" main.py
.\.venv\Scripts\pyinstaller --noconfirm --clean --windowed --onefile --name ImgToolbox --add-data "ui;ui" main.py
```

### 目录结构

```
img_tool/
├─ app/
│  ├─ bridge.py
│  ├─ tasks.py
│  └─ wrappers.py
├─ script/
│  ├─ bgr2rgb.py
│  ├─ rename2.py
│  ├─ select_diverse.py
│  ├─ 更改json路径.py
│  ├─ reorder_labels.py
│  └─ synthesize.py
├─ tests/
│  ├─ test_bridge.py
│  ├─ test_settings_contract.py
│  ├─ test_stage2_contracts.py
│  ├─ test_tasks.py
│  └─ test_wrappers.py
├─ ui/
│  └─ new.html
├─ reports/
│  └─ iteration_report.md  # 本地产物，默认不纳入版本管理
├─ docs/
├─ pyproject.toml
└─ main.py
```
