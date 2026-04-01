## 个人图片批量处理工具箱

离线桌面工具，基于 `pywebview + 本地 HTML/CSS/JS + Python`，封装 `script/` 下 4 个原始脚本能力。

### 功能模块
1. `bgr2rgb`：颜色通道转换（RGB -> BGR）
2. `rename2`：图片 + JSON 批量重命名
3. `select_diverse`：多样性筛图（pHash）
4. `json_path`：JSON 的 `imagePath` 批量修复

### 执行模式
1. `安全复制`（默认）：只写输出目录，不改原目录
2. `原地修改`：执行前强制备份，再写入原目录

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
```text
img_tool/
├─ app/
│  ├─ bridge.py
│  ├─ tasks.py
│  └─ wrappers.py
├─ script/
│  ├─ bgr2rgb.py
│  ├─ rename2.py
│  ├─ select_diverse.py
│  └─ 更改json路径.py
├─ tests/
│  ├─ test_bridge.py
│  ├─ test_tasks.py
│  └─ test_wrappers.py
├─ ui/
│  └─ index.html
└─ main.py
```

