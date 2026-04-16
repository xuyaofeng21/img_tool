# 个人图片批量处理工具箱 v1.0.4

离线桌面工具，基于 `pywebview + 本地 HTML/CSS/JS + Python`，封装 `script/` 下脚本能力，面向 Windows 本地批处理场景。

### v1.0.4 更新（2026-04-16）

**多样性筛图（select_diverse）核心改进：**
- 原地修改模式改为**剪切移动**而非复制 — 选中图片从源目录移到输出目录，源目录只保留未选中的重复照片
- 输入格式扩展 — 支持 JPG、PNG、BMP、TIFF、GIF、WebP 等所有常见图片格式，不再限于 PNG
- "保留数量"改名为"**挑选数量**"，语义更清晰
- 输出目录路径在原地修改模式下也可选 — 可以指定移动目标目录
- 任务成功后自动刷新路径解析预览，实时显示目录最新文件数量

**标签排序（reorder_labels）限制调整：**
- 禁用"另存输出"模式，强制使用原地修改 — 操作直接生效，无需额外输出目录

**UX 改进：**
- 终端日志支持选中文本复制 — 添加 `user-select: text`，解决日志无法复制的问题

### v1.0.3 更新（2026-04-14）

**合成标注（synthesize）核心修复：**
- 物体放置改为全 bbox  containment 检查 — 物体整个边界框必须完全落在有效草地内，而非仅中心点
- 有效草地区域计算升级 — `grass 减去 obstacle` 得到纯草地，物体不会放置在障碍物上
- 无 grass 标签时跳过 — 背景图无 grass 标签时直接跳过，不强制失败
- 原图均衡使用 — 旋转池机制（`random.sample` + 索引），100 张原图均匀分配到各背景图，无放回抽样

**UX 改进：**
- 标签输入改为下拉组合框 — 支持从下拉列表选择，也可自由输入
- 清除缓存按钮 — 合成模式下显示，点击清空 rembg 模型缓存目录
- 原地修改模式优化 — 简化备份目录要求，`synthesize` 任务强制使用安全复制模式

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
2. `原地修改`：直接修改源文件，执行前会有确认提示，请注意备份。

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
