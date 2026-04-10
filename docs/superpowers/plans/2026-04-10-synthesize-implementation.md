# Synthesize 模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 GUI 中新增 `synthesize` 任务类型，实现智能多边形标注合成功能。

**Architecture:** 复用现有 TaskManager + wrappers 架构。新增 `synthesize` 任务路由到 `_run_synthesize`，核心逻辑直接实现在 wrappers.py 中（复用 script/synthesize.py 的辅助函数）。进度通过 log 函数输出到终端日志。

**Tech Stack:** Python (app/wrappers.py), JavaScript (ui/new.html), 外部依赖: rembg, shapely, opencv-python, PIL

---

## 文件结构

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/wrappers.py` | 修改 | 新增 `_run_synthesize` 函数和任务路由 |
| `ui/new.html` | 修改 | 新增 `synthesize` 任务配置 |
| `script/synthesize.py` | 修改 | 提取可复用的辅助函数 |

---

## Task 1: 添加 UI 任务配置

**Files:**
- Modify: `ui/new.html:596-604`

- [ ] **Step 1: 在 TASKS 对象中添加 synthesize 配置**

在 `reorder_labels` 配置后面添加:

```javascript
synthesize: {
    title: "合成标注",
    desc: "将物体图像合成到背景图中，自动更新 LabelMe JSON 标注。",
    icon: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>',
    supportsInputMode: false,
    paths: [
        { key: "source_folder", label: "源物体目录", hint: "包含待合成物体图片的目录", placeholder: "选择文件夹...", required: true },
        { key: "bg_json_folder", label: "背景图目录", hint: "带 JSON 标注的背景图目录", placeholder: "选择文件夹...", required: true },
        { key: "output_folder", label: "输出目录", hint: "合成结果保存位置", placeholder: "选择文件夹...", required: true, safeOnly: true }
    ],
    params: [
        { key: "label", label: "标注名称", hint: "合成后物体的标注名称", placeholder: "如: 刺猬", required: true, type: "text" },
        { key: "target_label", label: "源标注标签", hint: "从哪个标签抠图(可选)", placeholder: "如: animal", type: "text" },
        { key: "max_objects", label: "放置数量", hint: "每张背景图放置物体数量", placeholder: "3", type: "number", step: "1", min: "1", max: "10", default: 3 },
        { key: "max_object_size", label: "物体最大尺寸", hint: "物体最大边长(像素)", placeholder: "350", type: "number", step: "10", min: "50", max: "800", default: 350 },
        { key: "model", label: "抠图模型", hint: "small=快, precise=准", type: "radio", default: "small", options: [ { label: "轻量(快)", value: "small" }, { label: "精准(慢)", value: "precise" } ] },
        { key: "rotation_angle", label: "最大旋转角度", hint: "随机旋转范围", placeholder: "30", type: "number", step: "5", min: "0", max: "90", default: 30 },
        { key: "grass_label", label: "地面标签名", hint: "表示地面的标签名", placeholder: "grass", type: "text", default: "grass" }
    ]
}
```

- [ ] **Step 2: 提交**

```bash
git add ui/new.html
git commit -m "feat(ui): add synthesize task definition"
```

---

## Task 2: 添加 wrapper 路由

**Files:**
- Modify: `app/wrappers.py:1488-1490`

- [ ] **Step 1: 在 execute_task 中添加路由**

在 `reorder_labels` 路由后添加:

```python
if task == "reorder_labels":
    return _run_reorder_labels(paths, mode, backup_dir, log)
if task == "synthesize":
    return _run_synthesize(paths, params, mode, backup_dir, log)
raise ValueError(f"不支持的 task: {task}")
```

- [ ] **Step 2: 提交**

```bash
git add app/wrappers.py
git commit -m "feat(wrappers): add synthesize task routing"
```

---

## Task 3: 实现核心辅助函数

**Files:**
- Modify: `app/wrappers.py` (在文件末尾 `_run_reorder_labels` 函数之后添加)

- [ ] **Step 1: 添加辅助函数**

需要从 `script/synthesize.py` 提取并适配以下函数:

```python
# ===== Synthesize 辅助函数 =====

def _get_cache_path(cache_dir: str, filename: str, mtime: float, max_size: tuple[int, int], model_name: str) -> str:
    """生成本地缓存路径"""
    import os
    name_without_ext = os.path.splitext(filename)[0]
    return os.path.join(cache_dir, f"{name_without_ext}_{mtime}_{max_size[0]}_{max_size[1]}_{model_name}.png")


def _is_cache_valid(cache_path: str, source_mtime: float) -> bool:
    """校验缓存是否有效"""
    import os
    if not os.path.exists(cache_path):
        return False
    cache_stat = os.stat(cache_path)
    return cache_stat.st_mtime >= source_mtime


def _create_alpha_mask_from_labelme(json_path: str, img_height: int, img_width: int, target_label: str) -> "np.ndarray":
    """从 LabelMe JSON 读取指定标签的多边形，创建 alpha mask"""
    import cv2
    import json
    import numpy as np
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    mask = np.zeros((img_height, img_width), dtype=np.uint8)
    for shape in data.get("shapes", []):
        if shape.get("label") == target_label and shape.get("shape_type") == "polygon":
            points = np.array(shape["points"], dtype=np.int32)
            cv2.fillPoly(mask, [points], 255)
    return mask


def _compute_object_hash(file_path: str) -> "Any":
    """计算图片的感知哈希（用于去重，可选）"""
    import imagehash
    from PIL import Image
    return imagehash.phash(Image.open(file_path))


def _load_script_module_synthesize() -> "ModuleType":
    """加载 synthesize 脚本模块"""
    return _load_script_module("script_synthesize", "synthesize.py")
```

- [ ] **Step 2: 提交**

```bash
git add app/wrappers.py
git commit -m "feat(wrappers): add synthesize helper functions"
```

---

## Task 4: 实现 _run_synthesize 主函数

**Files:**
- Modify: `app/wrappers.py`

- [ ] **Step 1: 实现 _run_synthesize 函数**

在 `_run_reorder_labels` 函数之后添加完整实现:

```python
def _run_synthesize(
    paths: dict[str, Any],
    params: dict[str, Any],
    mode: str,
    backup_dir: str,
    log: LogFn,
) -> dict[str, Any]:
    """合成任务主函数"""
    import os
    import cv2
    import json
    import random
    import shutil
    import tempfile
    import numpy as np
    from pathlib import Path
    from PIL import Image
    from rembg import remove
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    # 解析参数
    label = str(params.get("label", "")).strip()
    target_label = str(params.get("target_label", "")).strip() or None
    max_objects = int(params.get("max_objects", 3))
    max_object_size = int(params.get("max_object_size", 350))
    model_choice = str(params.get("model", "small")).strip()
    rotation_angle = float(params.get("rotation_angle", 30))
    grass_label = str(params.get("grass_label", "grass")).strip()

    if not label:
        raise ValueError("标注名称不能为空")

    # 获取路径
    source_folder = _collect_first_existing_dir(paths, ["source_folder", "input_dir"])
    bg_json_folder = _collect_first_existing_dir(paths, ["bg_json_folder", "source_dir"])
    output_folder = _ensure_safe_output_dir(str(paths.get("output_folder", "")), [source_folder, bg_json_folder], "output_dir")

    if source_folder is None:
        raise ValueError("源物体目录无效")
    if bg_json_folder is None:
        raise ValueError("背景图目录无效")

    source_folder = Path(source_folder)
    bg_json_folder = Path(bg_json_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    log("info", f"合成任务开始: label={label}, max_objects={max_objects}")

    # 扫描源物体
    source_files = [p for p in source_folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    if not source_files:
        raise ValueError(f"源物体目录为空: {source_folder}")

    # 扫描背景图
    bg_json_pairs = []
    for file in bg_json_folder.iterdir():
        if file.is_file() and file.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
            json_path = bg_json_folder / f"{file.stem}.json"
            if json_path.exists():
                bg_json_pairs.append((file, json_path))

    if not bg_json_pairs:
        raise ValueError(f"背景图目录中未找到带 JSON 的图片: {bg_json_folder}")

    log("info", f"源物体: {len(source_files)} 张, 背景图: {len(bg_json_pairs)} 张")

    # 缓存目录
    cache_dir = Path(tempfile.gettempdir()) / "img_tool_synthesize_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    model_name = "u2net" if model_choice == "precise" else "u2net_small"

    # 处理每张背景图
    success_count = 0
    fail_count = 0

    for idx, (bg_path, json_path) in enumerate(bg_json_pairs, 1):
        _require_not_cancelled()
        try:
            result = _process_single_synthesize(
                bg_path, json_path, source_files, output_folder,
                label, target_label, max_objects, max_object_size, model_name,
                rotation_angle, grass_label, cache_dir, log
            )
            if result:
                success_count += 1
            else:
                fail_count += 1
        except Exception as exc:
            log("error", f"处理失败 {bg_path.name}: {exc}")
            fail_count += 1

        if idx % 10 == 0 or idx == len(bg_json_pairs):
            log("info", f"已处理 {idx}/{len(bg_json_pairs)}")

    log("info", f"合成完成: 成功 {success_count}, 失败 {fail_count}")

    return {
        "status": "success",
        "success_count": success_count,
        "fail_count": fail_count,
        "skipped_count": 0,
        "output_path": str(output_folder),
        "backup_path": "",
        "error": "",
    }


def _process_single_synthesize(
    bg_path: Path,
    json_path: Path,
    source_files: list[Path],
    output_folder: Path,
    label: str,
    target_label: str | None,
    max_objects: int,
    max_object_size: int,
    model_name: str,
    rotation_angle: float,
    grass_label: str,
    cache_dir: Path,
    log: LogFn,
) -> bool:
    """处理单张背景图的合成"""
    import cv2
    import json
    import random
    import numpy as np
    from PIL import Image
    from rembg import remove
    from shapely.geometry import Polygon, box

    # 加载背景图
    bg_img = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED)
    if bg_img is None:
        return False

    # 转换为 BGRA
    if len(bg_img.shape) == 2:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_GRAY2BGRA)
    elif bg_img.shape[2] == 3:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_BGR2BGRA)
    else:
        bg_img = cv2.cvtColor(bg_img, cv2.COLOR_RGBA2BGRA)

    # 解析 JSON 获取 grass 和 obstacles 区域
    with open(json_path, "r", encoding="utf-8") as f:
        original_json = json.load(f)

    grass_polygons = []
    obstacles_polygons = []
    for shape in original_json.get("shapes", []):
        if shape.get("shape_type") != "polygon":
            continue
        poly_points = [tuple(p) for p in shape["points"]]
        try:
            poly = Polygon(poly_points)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_valid:
                if shape.get("label") == grass_label:
                    grass_polygons.append(poly)
                elif shape.get("label") == "obstacles":
                    obstacles_polygons.append(poly)
        except Exception:
            pass

    bg_h, bg_w = bg_img.shape[:2]

    # 选择放置物体
    num_objects = random.randint(1, max_objects)
    selected_sources = random.choices(source_files, k=num_objects)

    placed_objects = []  # [(bbox, object_img, object_shape)]

    for source_path in selected_sources:
        obj_result = _get_or_create_object_cache(
            source_path, target_label, max_object_size, model_name, cache_dir, log
        )
        if obj_result is None:
            continue

        object_img, obj_hash = obj_result

        # 旋转和镜像
        object_img = _apply_rotation_and_flip(object_img, rotation_angle, log)

        # 放置物体
        placed, bbox = _place_object_on_grass(
            object_img, bg_img, grass_polygons, obstacles_polygons, placed_objects, log
        )

        if placed and bbox is not None:
            # 创建多边形标注
            obj_shape = _create_polygon_from_object(object_img, bbox, label)
            placed_objects.append((bbox, object_img, obj_shape))

    if not placed_objects:
        return False

    # 保存合成图
    output_img_path = output_folder / bg_path.name
    if bg_img.shape[2] == 4:
        cv2.imwrite(str(output_img_path), cv2.cvtColor(bg_img, cv2.COLOR_BGRA2BGR))
    else:
        cv2.imwrite(str(output_img_path), bg_img)

    # 更新 JSON
    new_shapes = list(original_json.get("shapes", []))
    for obj_shape in placed_objects:
        new_shapes = _adjust_polygons_with_object(new_shapes, obj_shape, log)
        new_shapes.append(obj_shape)

    new_json = {
        "version": original_json.get("version", "4.5.6"),
        "flags": original_json.get("flags", {}),
        "shapes": new_shapes,
        "imagePath": bg_path.name,
        "imageWidth": original_json.get("imageWidth", bg_w),
        "imageHeight": original_json.get("imageHeight", bg_h),
    }

    output_json_path = output_folder / f"{bg_path.stem}.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(new_json, f, ensure_ascii=False, indent=2)

    return True
```

- [ ] **Step 2: 实现辅助函数 _get_or_create_object_cache**

在 `_process_single_synthesize` 之后添加:

```python
def _get_or_create_object_cache(
    source_path: Path,
    target_label: str | None,
    max_object_size: int,
    model_name: str,
    cache_dir: Path,
    log: LogFn,
):
    """获取或创建物体缓存"""
    import cv2
    import json
    from PIL import Image
    from rembg import remove

    source_stat = source_path.stat()
    source_mtime = source_stat.st_mtime
    cache_path = _get_cache_path(str(cache_dir), source_path.name, source_mtime, (max_object_size, max_object_size), model_name)

    # 检查缓存
    if _is_cache_valid(cache_path, source_mtime):
        try:
            img = cv2.imread(cache_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                return img, None
        except Exception:
            pass

    # 加载图片
    img = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA)

    h, w = img.shape[:2]

    # 尝试用 labelme 标注抠图
    json_path = source_path.parent / f"{source_path.stem}.json"
    has_label_mask = False

    if target_label and json_path.exists():
        try:
            label_mask = _create_alpha_mask_from_labelme(str(json_path), h, w, target_label)
            if cv2.countNonZero(label_mask) > 0:
                img[:, :, 3] = label_mask
                has_label_mask = True
        except Exception:
            pass

    # 用 rembg 抠图
    if not has_label_mask:
        try:
            img_rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
            img_pil = Image.fromarray(img_rgba)
            img_no_bg_pil = remove(img_pil, model=model_name, alpha_matting=False)
            img = cv2.cvtColor(np.array(img_no_bg_pil), cv2.COLOR_RGBA2BGRA)
        except Exception:
            return None

    # 缩放
    h, w = img.shape[:2]
    if w > max_object_size or h > max_object_size:
        scale = min(max_object_size / w, max_object_size / h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # 保存缓存
    cv2.imwrite(cache_path, img)
    return img
```

- [ ] **Step 3: 实现 _apply_rotation_and_flip 函数**

```python
def _apply_rotation_and_flip(object_img: "np.ndarray", max_angle: float, log: LogFn) -> "np.ndarray":
    """应用随机旋转和镜像"""
    import cv2
    import numpy as np
    import random

    # 水平镜像
    if random.choice([True, False]):
        object_img = cv2.flip(object_img, 1)

    # 随机旋转
    angle = random.uniform(-max_angle, max_angle)
    h, w = object_img.shape[:2]
    center = (w // 2, h // 2)

    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    # 计算旋转后尺寸
    cos_val = np.abs(rotation_matrix[0, 0])
    sin_val = np.abs(rotation_matrix[0, 1])
    new_w = int((h * sin_val) + (w * cos_val))
    new_h = int((h * cos_val) + (w * sin_val))

    rotation_matrix[0, 2] += (new_w / 2) - center[0]
    rotation_matrix[1, 2] += (new_h / 2) - center[1]

    rotated = cv2.warpAffine(
        object_img,
        rotation_matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=[0, 0, 0, 0]
    )

    return rotated
```

- [ ] **Step 4: 实现 _place_object_on_grass 函数**

```python
def _place_object_on_grass(
    object_img: "np.ndarray",
    bg_img: "np.ndarray",
    grass_polygons: list,
    obstacles_polygons: list,
    placed_objects: list,
    log: LogFn,
) -> tuple[bool, tuple | None]:
    """将物体放置在草地上"""
    import cv2
    import random
    from shapely.geometry import box

    obj_h, obj_w = object_img.shape[:2]
    bg_h, bg_w = bg_img.shape[:2]

    # 计算有效放置区域
    if grass_polygons:
        # 用 grass 的边界框
        try:
            union_grass = unary_union(grass_polygons)
            bounds = union_grass.bounds
            min_x, min_y, max_x, max_y = bounds
            # 扩大范围到图像边界
            min_x = max(0, min_x)
            min_y = max(0, min_y)
            max_x = min(bg_w, max_x)
            max_y = min(bg_h, max_y)
        except Exception:
            min_x, max_x = 0, bg_w
            min_y, max_y = bg_h // 3, bg_h
    else:
        # 回退到下半部分
        min_x, max_x = 0, bg_w
        min_y, max_y = bg_h // 3, bg_h

    max_attempts = 50
    for attempt in range(max_attempts):
        # 随机位置
        x1 = random.randint(int(min_x), max(1, int(max_x - obj_w)))
        y1 = random.randint(int(min_y), max(1, int(max_y - obj_h)))
        x2 = x1 + obj_w
        y2 = y1 + obj_h
        candidate_bbox = (x1, y1, x2, y2)

        # 检查是否完全在 obstacles 内
        if obstacles_polygons:
            candidate_poly = box(x1, y1, x2, y2)
            is_fully_in_obstacle = any(obs.contains(candidate_poly) for obs in obstacles_polygons)
            if is_fully_in_obstacle:
                continue

        # 检查与已放置物体重叠
        overlap = False
        for (ex1, ey1, ex2, ey2) in placed_objects:
            if not (x2 < ex1 or x1 > ex2 or y2 < ey1 or y1 > ey2):
                overlap = True
                break
        if overlap:
            continue

        # 放置物体
        alpha = object_img[:, :, 3] / 255.0
        roi = bg_img[y1:y2, x1:x2]
        object_rgb = object_img[:, :, :3]

        for c in range(3):
            roi[:, :, c] = (alpha * object_rgb[:, :, c] + (1 - alpha) * roi[:, :, c]).astype(np.uint8)

        bg_img[y1:y2, x1:x2] = roi
        return True, candidate_bbox

    return False, None
```

- [ ] **Step 5: 实现 _create_polygon_from_object 函数**

```python
def _create_polygon_from_object(object_img: "np.ndarray", bbox: tuple, label: str) -> dict:
    """从物体图像创建多边形标注"""
    import cv2
    import numpy as np

    x1, y1, _, _ = bbox
    alpha_channel = object_img[:, :, 3]
    _, binary_mask = cv2.threshold(alpha_channel, 127, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)
    if not contours:
        return {"label": label, "points": [[float(x1), float(y1)], [float(x1 + object_img.shape[1]), float(y1)], [float(x1 + object_img.shape[1]), float(y1 + object_img.shape[0])], [float(x1), float(y1 + object_img.shape[0])]], "shape_type": "polygon"}

    largest_contour = max(contours, key=cv2.contourArea)
    epsilon = 0.01 * cv2.arcLength(largest_contour, True)
    approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

    contour_points = approx_contour.reshape(-1, 2) + np.array([x1, y1])
    points = [[float(p[0]), float(p[1])] for p in contour_points]

    return {"label": label, "points": points, "shape_type": "polygon"}
```

- [ ] **Step 6: 实现 _adjust_polygons_with_object 函数**

```python
def _adjust_polygons_with_object(original_shapes: list, object_shape: dict, log: LogFn) -> list:
    """当物体与原有多边形重叠时，裁剪多边形边界"""
    from shapely.geometry import Polygon, MultiPolygon

    adjusted = []
    try:
        object_poly = Polygon(object_shape["points"])
        if not object_poly.is_valid:
            object_poly = object_poly.buffer(0)
    except Exception:
        return original_shapes

    for shape in original_shapes:
        if shape.get("shape_type") != "polygon":
            adjusted.append(shape)
            continue

        try:
            shape_poly = Polygon(shape["points"])
            if not shape_poly.is_valid:
                shape_poly = shape_poly.buffer(0)
            if not shape_poly.is_valid:
                adjusted.append(shape)
                continue

            if shape_poly.contains(object_poly):
                adjusted.append(shape)
                continue

            if not shape_poly.intersects(object_poly):
                adjusted.append(shape)
                continue

            difference = shape_poly.difference(object_poly)

            if difference.is_empty:
                continue

            if isinstance(difference, Polygon):
                new_points = [[float(x), float(y)] for x, y in difference.exterior.coords[:-1]]
                if len(new_points) >= 3:
                    adjusted.append({"label": shape["label"], "points": new_points, "shape_type": "polygon"})
            elif isinstance(difference, MultiPolygon):
                for poly in difference.geoms:
                    new_points = [[float(x), float(y)] for x, y in poly.exterior.coords[:-1]]
                    if len(new_points) >= 3:
                        adjusted.append({"label": shape["label"], "points": new_points, "shape_type": "polygon"})
        except Exception:
            adjusted.append(shape)

    return adjusted
```

- [ ] **Step 7: 提交**

```bash
git add app/wrappers.py
git commit -m "feat(wrappers): implement _run_synthesize and helper functions"
```

---

## Task 5: 测试验证

**Files:**
- Modify: `app/wrappers.py` (添加类型注解)

- [ ] **Step 1: 验证导入正常**

```bash
cd d:/img_tool && python -c "from app.wrappers import _run_synthesize; print('Import OK')"
```

- [ ] **Step 2: 验证任务路由**

```bash
cd d:/img_tool && python -c "from app.wrappers import execute_task; print('execute_task OK')"
```

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: verify synthesize module imports"
```

---

## 依赖检查清单

在实现前确保以下依赖已安装:

```bash
pip install rembg shapely opencv-python pillow numpy imagehash
```

---

## 进度输出示例

任务执行时终端日志输出:

```
[INFO] 合成任务开始: label=刺猬, max_objects=3
[INFO] 源物体: 50 张, 背景图: 200 张
[INFO] 已处理 10/200
[INFO] 已处理 20/200
...
[INFO] 合成完成: 成功 195, 失败 5
```

---

## 注意事项

1. **循环导入**: wrappers.py 中如需导入 tasks 模块，使用函数内导入
2. **取消任务**: 在主循环中使用 `_require_not_cancelled()` 检查
3. **缓存清理**: 设置页面需添加清除缓存按钮
4. **内存管理**: 流式处理，不需要预加载所有物体到内存

