# 个人图片批量处理工具箱 v1.0.0

离线桌面工具，基于 `pywebview + 本地 HTML/CSS/JS + Python`，封装 `script/` 下脚本能力。

### 功能模块

| 模块 | 说明 |
|------|------|
| `bgr2rgb` | 颜色通道转换（RGB -> BGR） |
| `rename2` | 图片 + JSON 批量重命名 |
| `select_diverse` | 多样性筛图（pHash） |
| `json_path` | JSON 的 `imagePath` 批量修复 |
| `reorder_labels` | JSON 标注顺序重排 |
| `synthesize` | 智能合成标注（物体 + 背景图 + LabelMe JSON） |

### 执行模式

1. `安全复制`（默认）：只写输出目录，不改原目录
2. `原地修改`：执行前强制备份，再写入原目录

### 合成标注 (synthesize)

将带标注的物体合成到背景图中，自动更新 LabelMe JSON：

- 自动抠图：rembg (u2net / u2net_small)
- 智能放置：地面区域优先，障碍物避让
- 随机增强：旋转 + 水平镜像
- 自动标注：生成多边形标注

### 推荐环境（项目内 venv）

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
```

### 启动

```bash
.\.venv\Scripts\python.exe main.py
```

### 运行测试

```bash
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
│  ├─ bridge.py      # API 桥接
│  ├─ tasks.py       # 任务管理
│  └─ wrappers.py    # 任务实现
├─ script/
│  ├─ bgr2rgb.py
│  ├─ rename2.py
│  ├─ select_diverse.py
│  ├─ json_path.py
│  ├─ reorder_labels.py
│  └─ synthesize.py
├─ tests/
│  ├─ test_bridge.py
│  ├─ test_tasks.py
│  └─ test_wrappers.py
├─ ui/
│  └─ new.html
├─ docs/             # 开发文档
└─ main.py
```
