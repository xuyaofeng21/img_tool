# ImgToolbox — 离线图片批量处理工具箱

基于 `pywebview + Python + HTML/CSS/JS` 的桌面工具，面向 Windows/Linux 本地图片批处理场景。

当前版本：**v1.5.0**

---

## v1.5.0 更新（2026-05-12）

**手动合成透视倾斜 + 镜像翻转：**

- 选中物体后显示三个控制手柄：**镜像**（左上角橙色）、**透视倾斜**（底部中间紫色）、**旋转**（右上角蓝色）
- 拖拽底部紫色手柄左右拖动，对物体施加 Y 轴透视倾斜（±75°），模拟 3D 空间绕垂直轴旋转效果
- 拖动过程中前端实时显示 CSS 3D 预览（`perspective(800px) rotateY()`），松开鼠标后由后端 OpenCV `cv2.warpPerspective` 生成精确渲染结果替换
- 点击左上角橙色按钮切换水平镜像翻转
- 透视变换与镜像、旋转、缩放自由组合，变换流程为：旋转 → 镜像 → 透视倾斜 → 缩放
- 多边形标注坐标在所有变换步骤中同步更新（`cv2.perspectiveTransform`），确保标注与图像严丝合缝

**技术细节：**

- 透视投影数学与 CSS `perspective(800px) rotateY()` 完全一致：`z = -cx * sin(θ)`, `k = P / (P - z)`, 屏幕坐标 `sx = cx * cos(θ) * k + w/2`
- 前端 warp 模式下控制手柄使用屏幕坐标命中检测，非 warp 模式使用局部坐标旋转矩阵计算

**Bug 修复：**

- 修复镜像翻转后 Canvas 预览和实际合成结果方向相反的问题
- 修复透视倾斜松手后再点击物体控制手柄不显示的问题

---

## v1.4.0 更新（2026-05-06）

**手动合成标注叠加显示：**
- 画布导航栏新增"标注"切换按钮，点击可叠加显示 labelme JSON 中的多边形标注
- 标注以半透明填充 + 实线边框 + 标签文字形式显示，不同 label 不同颜色
- 切换背景图时标注自动更新，无 JSON 文件时不报错

**标签排序功能增强：**
- 不再硬编码 station 标签，改为自动检测 JSON 目录中所有 label 供用户选择
- 新增"底层标签"参数，支持多标签（逗号分隔），路径变化时自动检测并填充下拉建议
- 未指定时默认使用 station，保持向后兼容

**Bug 修复：**
- 修复鼠标移出画布后再移入，已选中素材的透明预览无法恢复的问题

---

## v1.3.0 更新（2026-04-29）

**手动合成旋转功能：**
- 点击已放置的物体出现蓝色选中框，右上角显示旋转手柄
- 拖拽手柄实时旋转素材（0°~360°），多边形标注同步变换
- 选中态持久常驻，滚动滚轮缩放选中物体
- 边框和手柄不会随鼠标移动消失

**Bug 修复：**
- 修复旋转后多边形标注与图像错位的问题（旋转变换矩阵 sin 符号错误）
- 修复点击物体后选中框延迟出现的问题

---

## v1.2.0 更新（2026-04-27）

**性能与稳定性：**
- 重命名 `in_place` 模式提速：去掉暂存目录复制→移动流水线，直接 `os.rename()` 原地操作
- JSON 路径修复简化：移除 `另存输出` 模式，只保留直接修改源文件，前端默认选中覆盖源文件
- JSON 路径修复弹窗 BUG 修复：`multiprocessing.Pool` 改为 `ThreadPoolExecutor`，不再弹出多个控制台窗口
- 日志系统：双文件日志（`task.log` + `system.log`），记录任务全流程、异常堆栈和应用启停事件

**手动合成标注修复：**
- 修复合成标注偏差问题：手动模式直接应用源 JSON 的 labelme 多边形标注，跳过 rembg 重新计算
- 修复切换到手动合成时输出目录路径字段不显示的问题

**素材库增强：**
- 同素材全局放置次数限制（默认 10 次），跨背景图统计，素材卡片显示 `已用/上限` 徽章
- 达到上限的素材自动变灰禁用，切换源目录自动重置计数
- 阈值可通过设置配置

**功能调整：**
- 系统合成模式暂时置灰，当前仅开放手动合成
- 抠图模型检测 UI 已移除

**UX 改进：**
- 路径解析预览默认展开文件详情，去掉折叠/展开交互
- 日志过滤 pywebview 框架内部噪音，system.log 清爽可读

---

## 功能模块

| 界面任务名 | 说明 |
|------|------|
| `bgr2rgb` | 颜色通道转换（RGB ↔ BGR） |
| `rename2` | 图片 + JSON 批量重命名 |
| `select_diverse` | 多样性筛图（pHash 去重） |
| `json_path` | JSON 的 `imagePath` 字段批量修复 |
| `reorder_labels` | JSON 标注顺序重排（自选标签 → 底层） |
| `synthesize` | 合成标注（手动模式：点击放置 + 拖动调整） |

---

## 执行模式

| 模式 | 说明 |
|------|------|
| 安全复制（默认） | 结果写入输出目录，不改原文件 |
| 原地修改 | 直接修改源文件，执行前弹出确认提示 |

---

## 合成标注（synthesize）

将带标注的物体合成到背景图中，自动更新 LabelMe JSON。

### 手动合成（当前唯一开放模式）

- 用户在画布上点击放置源物体
- 点击选中物体显示蓝色边框和三个控制手柄：
  - **橙色（左上角）**：点击切换水平镜像翻转
  - **紫色（底部中间）**：拖拽施加透视倾斜（±75°），实时 CSS 3D 预览
  - **蓝色（右上角）**：拖拽旋转物体（0°~360°）
- 放置后可拖动调整位置，滚轮/滑块缩放（0.2x ~ 3.0x）
- 每张背景图最多 3 个物体
- 键盘 A/D 快速切换背景图，支持多张背景图批量执行
- 标注直接应用源 JSON 的 labelme 多边形坐标，经过旋转 → 镜像 → 透视倾斜 → 缩放变换，确保严丝合缝
- 素材库显示每个素材的全局使用次数，同一素材在所有背景图中累计不超过配置上限

### 源图目录规则

- 源图全部带 JSON 且 label 一致：自动识别标注标签
- 源图全部不带 JSON：需手动填写合成后标注标签
- 目录混合或 label 不一致：直接阻断并提示整理目录

---

## 日志

应用启动时自动在以下位置创建日志文件：

| 文件 | 内容 |
|------|------|
| `logs/task.log` | 任务执行全流程日志、异常堆栈 |
| `logs/system.log` | 应用启停事件、未捕获异常 |

- 开发环境：`项目根目录/logs/`
- 打包后：`可执行文件同级目录/logs/`
- 每次启动覆盖旧日志，不留历史冗余

---

## 开发环境

### 推荐（uv）

```bash
uv sync --dev
uv run python main.py
```

### 运行测试

```bash
uv run python -m pytest -q
```

### pip 兜底方案

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 打包

### Windows EXE

```bash
.\.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name ImgToolbox --add-data "ui;ui" --add-data "script;script" main.py
```

### Linux AppImage

项目使用 GitHub Actions 双平台自动构建（`.github/workflows/build.yml`），基于 `linuxdeploy-plugin-gtk` 打包 GTK 依赖。

---

## 目录结构

```
img_tool/
├─ app/
│  ├─ __init__.py
│  ├─ bridge.py          # pywebview API 桥接层
│  ├─ logger.py           # 日志模块（task.log + system.log）
│  ├─ settings_store.py  # 设置持久化
│  ├─ tasks.py           # 任务调度与日志
│  └─ wrappers.py        # 各任务执行逻辑
├─ script/
│  ├─ bgr2rgb.py
│  ├─ rename2.py
│  ├─ select_diverse.py
│  ├─ 更改json路径.py
│  ├─ reorder_labels.py
│  └─ synthesize.py
├─ tests/
│  ├─ conftest.py
│  ├─ test_bridge.py
│  ├─ test_manual_synthesize.py
│  ├─ test_settings_contract.py
│  ├─ test_stage2_contracts.py
│  ├─ test_tasks.py
│  └─ test_wrappers.py
├─ ui/
│  └─ new.html           # 单文件前端（HTML/CSS/JS ~4300 行）
├─ models/
│  └─ u2net.onnx         # rembg 模型（需手动下载）
├─ logs/                  # 运行时生成
│  ├─ task.log
│  └─ system.log
├─ pyproject.toml
├─ README.md
└─ main.py
```

---

## 技术栈

- **后端**：Python 3.12+ / pywebview / shapely / rembg / OpenCV
- **前端**：Vanilla HTML/CSS/JS（单文件 ~4300 行），无框架
- **构建**：PyInstaller (Windows) / linuxdeploy (Linux AppImage)
- **CI/CD**：GitHub Actions 双平台自动构建
