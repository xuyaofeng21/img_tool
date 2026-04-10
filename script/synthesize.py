import os
import sys
import argparse
import cv2
import numpy as np
import random
import json
from rembg import remove
from PIL import Image
import base64
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from multiprocessing import Pool, cpu_count
from tqdm import tqdm
import tempfile
import shutil
from datetime import datetime, timedelta


def detect_label_in_source_folder(source_folder):
    """自动检测源文件夹中 JSON 标注的标签种类"""
    labels = set()
    valid_count = 0

    for filename in os.listdir(source_folder):
        if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            continue
        name_without_ext = os.path.splitext(filename)[0]
        json_path = os.path.join(source_folder, f"{name_without_ext}.json")
        if os.path.exists(json_path):
            valid_count += 1
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for shape in data.get("shapes", []):
                    if shape.get("shape_type") == "polygon":
                        label = shape.get("label", "")
                        if label:
                            labels.add(label)
            except Exception:
                pass

    return labels, valid_count


def create_alpha_mask_from_labelme(json_path, img_height, img_width, target_label):
    """从 LabelMe JSON 读取指定标签的多边形，创建 alpha mask"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mask = np.zeros((img_height, img_width), dtype=np.uint8)

    for shape in data.get("shapes", []):
        if shape.get("label") == target_label and shape.get("shape_type") == "polygon":
            points = np.array(shape["points"], dtype=np.int32)
            cv2.fillPoly(mask, [points], 255)

    return mask


def get_cache_path(cache_dir, filename, mtime, max_size, model_name):
    """生成本地缓存路径"""
    name_without_ext = os.path.splitext(filename)[0]
    return os.path.join(cache_dir, f"{name_without_ext}_{mtime}_{max_size[0]}_{max_size[1]}_{model_name}.png")


def is_cache_valid(cache_path, source_mtime):
    """校验缓存是否有效"""
    if not os.path.exists(cache_path):
        return False
    # 检查源文件是否比缓存新
    cache_stat = os.stat(cache_path)
    return cache_stat.st_mtime >= source_mtime




def clean_expired_cache(cache_dir, expire_days, verbose=1):
    """清理过期缓存"""
    if not os.path.exists(cache_dir):
        return 0

    expire_time = datetime.now() - timedelta(days=expire_days)
    removed_count = 0

    for filename in os.listdir(cache_dir):
        cache_path = os.path.join(cache_dir, filename)
        if os.path.isfile(cache_path):
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
            if mtime < expire_time:
                try:
                    os.remove(cache_path)
                    removed_count += 1
                except Exception:
                    pass

    if verbose >= 1 and removed_count > 0:
        print(f"🧹 已清理 {removed_count} 个过期缓存文件")
    return removed_count


def process_single_animal(args):
    filename, source_folder, cache_dir, max_animal_size, model_name, target_label, verbose = args

    file_path = os.path.join(source_folder, filename)
    name_without_ext = os.path.splitext(filename)[0]
    json_path = os.path.join(source_folder, f"{name_without_ext}.json")
    source_stat = os.stat(file_path)
    source_mtime = source_stat.st_mtime

    # 生成缓存路径
    cache_path = get_cache_path(cache_dir, filename, source_mtime, max_animal_size, model_name)

    # 检查缓存是否有效
    if is_cache_valid(cache_path, source_mtime):
        try:
            img = cv2.imread(cache_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                if verbose >= 2:
                    print(f"   命中缓存：{filename}")
                return (cache_path, filename, img.shape[1], img.shape[0])
        except Exception:
            pass

    # 缓存无效或不存在，进行抠图处理
    try:
        img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None

        if img.shape[2] == 3:
            animal_img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        elif img.shape[2] == 4:
            animal_img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA)
        else:
            return None

        h, w = animal_img.shape[:2]
    except Exception:
        return None

    has_label_mask = False

    # 尝试使用 LabelMe 标注生成 alpha mask
    if target_label and os.path.exists(json_path):
        try:
            label_mask = create_alpha_mask_from_labelme(json_path, h, w, target_label)
            if cv2.countNonZero(label_mask) > 0:
                img_no_bg = animal_img.copy()
                img_no_bg[:, :, 3] = label_mask
                has_label_mask = True
                if verbose >= 2:
                    print(f"   使用标注抠图：{filename}")
        except Exception as e:
            if verbose >= 2:
                print(f"   标注解析失败：{str(e)}")

    # 没有标注或解析失败，使用 rembg 模型
    if not has_label_mask:
        try:
            img_rgba = cv2.cvtColor(animal_img, cv2.COLOR_BGRA2RGBA)
            img_pil = Image.fromarray(img_rgba)
            img_no_bg_pil = remove(img_pil, model=model_name, alpha_matting=False)
            img_no_bg = cv2.cvtColor(np.array(img_no_bg_pil), cv2.COLOR_RGBA2BGRA)
            if verbose >= 2:
                print(f"   使用模型抠图：{filename}")
        except Exception:
            return None

    h, w = img_no_bg.shape[:2]
    if w > max_animal_size[0] or h > max_animal_size[1]:
        scale = min(max_animal_size[0] / w, max_animal_size[1] / h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(img_no_bg, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        resized = img_no_bg

    # 保存到持久化缓存
    cv2.imwrite(cache_path, resized)
    if verbose >= 2:
        print(f"   已缓存：{filename}")
    return (cache_path, filename, resized.shape[1], resized.shape[0])


def process_single_background(args):
    bg_path, json_path, bg_name, processed_objects, output_folder, max_objects, label, verbose = args

    try:
        # 加载背景图
        bg_img = cv2.imread(bg_path, cv2.IMREAD_UNCHANGED)
        if bg_img is None:
            return (bg_name, False)

        # 转换为 BGRA（如果是灰度图则先转BGR再转BGRA）
        if len(bg_img.shape) == 2:
            bg_img = cv2.cvtColor(bg_img, cv2.COLOR_GRAY2BGR)
        if bg_img.shape[2] == 3:
            bg_img = cv2.cvtColor(bg_img, cv2.COLOR_BGR2BGRA)
        elif bg_img.shape[2] == 4:
            bg_img = cv2.cvtColor(bg_img, cv2.COLOR_RGBA2BGRA)

        # 加载原始JSON并提取obstacles多边形
        obstacles_polygons = []
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                original_json = json.load(f)
            for shape in original_json.get("shapes", []):
                if shape.get("label") == "obstacles" and shape.get("shape_type") == "polygon":
                    try:
                        poly = Polygon(shape["points"])
                        if not poly.is_valid:
                            poly = poly.buffer(0)
                        if poly.is_valid:
                            obstacles_polygons.append(poly)
                    except Exception as e:
                        if verbose >= 2:
                            print(f"   忽略无效obstacles多边形：{str(e)}")
        except Exception as e:
            if verbose >= 1:
                print(f"   读取JSON获取obstacles失败：{str(e)}")

        # 选择物体
        num_objects = random.randint(1, max_objects)
        if num_objects <= len(processed_objects):
            selected_objects = random.sample(processed_objects, num_objects)
        else:
            selected_objects = [random.choice(processed_objects) for _ in range(num_objects)]

        combined_img = bg_img.copy()
        object_shapes = []
        existing_bboxes = []
        placed_count = 0

        for object_data in selected_objects:
            combined_img, bbox, object_resized, placed = add_object_with_rotation(
                object_data, combined_img, existing_bboxes, obstacles_polygons, label, verbose=verbose)

            if placed and bbox and object_resized is not None:
                existing_bboxes.append(bbox)
                object_shapes.append(create_simple_polygon(object_resized, bbox, label))
                placed_count += 1

        if placed_count == 0:
            return (bg_name, False)

        # 保存合成图
        output_img_path = os.path.join(output_folder, bg_name)
        if combined_img.shape[2] == 4:
            combined_img = cv2.cvtColor(combined_img, cv2.COLOR_BGRA2BGR)
        cv2.imwrite(output_img_path, combined_img)

        # 保存JSON
        json_name = os.path.splitext(bg_name)[0] + ".json"
        output_json_path = os.path.join(output_folder, json_name)
        new_json = update_json_fast(json_path, output_img_path, object_shapes)

        if new_json:
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(new_json, f, ensure_ascii=False, indent=2)
            return (bg_name, True)
        return (bg_name, False)
    except Exception as e:
        if verbose >= 1:
            print(f"   处理{bg_name}出错：{str(e)}")
        return (bg_name, False)


def rotate_object(object_img, verbose=1):
    flip_horizontal = random.choice([True, False])
    if flip_horizontal:
        object_img = cv2.flip(object_img, 1)
        if verbose >= 2:
            print(f"   已执行水平镜像反转")

    direction = random.choice(["clockwise", "counterclockwise"])
    angle = random.uniform(0, 30)

    h, w = object_img.shape[:2]
    diagonal = np.sqrt(h ** 2 + w**2)
    new_w, new_h = int(diagonal), int(diagonal)

    center = (w // 2, h // 2)
    if direction == "clockwise":
        rotation_matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)
    else:
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

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

    if verbose >= 2:
        print(f"   旋转: {direction} {angle:.1f}度，新尺寸: {new_w}x{new_h}")

    return rotated


def print_welcome_message():
    print("=" * 60)
    print("   智能多边形标注工具（带障碍区域检查）   ")
    print("=" * 60)
    print("核心功能：")
    print("  1. 图像批量预处理+持久化缓存，自动抠图")
    print("  2. 随机旋转（0-30度）+ 水平镜像增强")
    print("  3. 多边形智能裁剪：原多边形与物体重叠时，边界沿物体边缘调整")
    print("  4. 障碍区域检查：物体不会被完全放置在obstacles标签多边形内")
    print("  5. 多进程并行处理，提升效率")
    print("-" * 60)


def get_valid_folder_path(prompt):
    while True:
        path = input(prompt).strip()
        if (path.startswith('"') and path.endswith('"')) or (path.startswith("'") and path.endswith("'")):
            path = path[1:-1]

        if os.path.isdir(path):
            abs_path = os.path.abspath(path)
            print(f"✅ 已选择文件夹：{abs_path}")
            return abs_path
        elif os.path.exists(path):
            print(f"❌ 错误：'{path}' 是文件，不是文件夹，请重新输入！")
        else:
            create_confirm = input(f"❓ 文件夹 '{path}' 不存在，是否创建？(y/n): ").lower()
            if create_confirm in ('y', 'yes'):
                try:
                    os.makedirs(path, exist_ok=True)
                    abs_path = os.path.abspath(path)
                    print(f"✅ 已创建文件夹：{abs_path}")
                    return abs_path
                except Exception as e:
                    print(f"❌ 创建失败：{str(e)}")
            else:
                print("🔄 请重新输入文件夹路径...")


def get_label_input():
    """获取标签输入（必填）"""
    while True:
        label = input("请输入标注标签（如 cat、dog、car 等）：").strip()
        if label:
            print(f"✅ 已设置标签：{label}")
            return label
        else:
            print("❌ 标签不能为空，请重新输入！")


def get_image_files_with_json(folder):
    valid_extensions = ('.png', '.jpg', '.jpeg', '.bmp')
    image_json_pairs = []

    for file in sorted(os.listdir(folder)):
        file_path = os.path.join(folder, file)
        if os.path.isfile(file_path) and file.lower().endswith(valid_extensions):
            img_name_no_ext = os.path.splitext(file)[0]
            json_path = os.path.join(folder, f"{img_name_no_ext}.json")
            if os.path.exists(json_path):
                image_json_pairs.append((file_path, json_path, file))

    return image_json_pairs


def batch_preprocess_objects(source_folder, max_object_size, model_choice, cache_dir, target_label, verbose=1):
    valid_extensions = ('.png', '.jpg', '.jpeg', '.bmp')

    # 检查文件夹是否存在
    if not os.path.exists(source_folder):
        if verbose >= 1:
            print(f"❌ 源文件文件夹不存在：{source_folder}")
        return [], None

    # 获取所有文件
    try:
        all_files = os.listdir(source_folder)
    except Exception as e:
        if verbose >= 1:
            print(f"❌ 无法读取源文件文件夹：{str(e)}")
        return [], None

    if not all_files:
        if verbose >= 1:
            print(f"❌ 源文件文件夹为空：{source_folder}")
        return [], None

    object_files = [f for f in all_files if os.path.isfile(os.path.join(source_folder, f))
                    and f.lower().endswith(valid_extensions)]

    if not object_files:
        if verbose >= 1:
            print(f"❌ 源文件文件夹无有效图片（支持格式：{', '.join(valid_extensions)}）")
            print(f"   文件夹内共有 {len(all_files)} 个文件/文件夹，但无匹配的图片")
            # 显示前10个文件供参考
            sample_files = sorted(all_files)[:10]
            print(f"   文件夹内容示例: {sample_files}")
            if len(all_files) > 10:
                print(f"   ... 还有 {len(all_files) - 10} 个项目")
        return [], None

    os.makedirs(cache_dir, exist_ok=True)
    processed_objects = []
    model_name = "u2net" if model_choice == "precise" else "u2net_small"

    if verbose >= 1:
        print(f"\n📥 批量预处理 {len(object_files)} 张图片（缓存目录：{cache_dir}）")

    task_args = [
        (filename, source_folder, cache_dir, max_object_size, model_name, target_label, verbose)
        for filename in object_files
    ]

    with Pool(processes=cpu_count()) as pool:
        results = list(tqdm(
            pool.imap(process_single_animal, task_args),
            total=len(task_args),
            desc="预处理图片",
            unit="张"
        ))

    for res in results:
        if res is not None:
            cache_path, filename, w, h = res
            processed_objects.append({
                "cache_path": cache_path,
                "filename": filename,
                "width": w,
                "height": h
            })

    if verbose >= 1:
        print(f"✅ 预处理完成，有效图片：{len(processed_objects)}/{len(object_files)}")
    return processed_objects, cache_dir


def check_overlap_fast(bbox, existing_bboxes, min_distance=10):
    x1, y1, x2, y2 = bbox
    x1 -= min_distance
    y1 -= min_distance
    x2 += min_distance
    y2 += min_distance

    for (ex1, ey1, ex2, ey2) in existing_bboxes:
        if x2 < ex1 or x1 > ex2 or y2 < ey1 or y1 > ey2:
            continue
        return True
    return False


def add_object_with_rotation(object_data, background_img, existing_bboxes, obstacles_polygons, label, max_attempts=50, verbose=1):
    """放置物体到背景图中"""
    object_img = cv2.imread(object_data["cache_path"], cv2.IMREAD_UNCHANGED)
    if object_img is None:
        return background_img, None, None, False

    original_w, original_h = object_data["width"], object_data["height"]
    bg_h, bg_w = background_img.shape[:2]

    scale = random.uniform(0.9, 1.1)
    new_object_w, new_object_h = int(round(original_w * scale)), int(round(original_h * scale))
    object_resized = cv2.resize(object_img, (new_object_w, new_object_h), interpolation=cv2.INTER_LINEAR)

    object_rotated = rotate_object(object_resized, verbose=verbose)
    rot_h, rot_w = object_rotated.shape[:2]

    # 计算放置区域（下半部分为主）
    min_y = max(0, bg_h // 3)
    max_y = max(0, bg_h - rot_h)
    if min_y > max_y:
        min_y, max_y = 0, max(0, bg_h - rot_h)

    for attempt in range(max_attempts):
        x1 = random.randint(0, max(0, bg_w - rot_w))
        y1 = random.randint(min_y, max_y) if min_y <= max_y else 0
        x2 = x1 + rot_w
        y2 = y1 + rot_h
        candidate_bbox = (x1, y1, x2, y2)

        # 检查物体是否完全包含在任何obstacles多边形内
        if obstacles_polygons:
            object_bbox_poly = box(x1, y1, x2, y2)
            is_fully_in_obstacle = False
            for obs_poly in obstacles_polygons:
                if obs_poly.contains(object_bbox_poly):
                    is_fully_in_obstacle = True
                    break
            if is_fully_in_obstacle:
                if verbose >= 2:
                    print(f"   位置{attempt+1}：物体完全在obstacles内，跳过")
                continue

        # 检查与现有物体是否重叠
        if not check_overlap_fast(candidate_bbox, existing_bboxes):
            # 放置物体
            alpha = object_rotated[:, :, 3] / 255.0
            roi = background_img[y1:y2, x1:x2]
            object_rgb = object_rotated[:, :, :3]

            for c in range(3):
                roi[:, :, c] = (alpha * object_rgb[:, :, c] + (1 - alpha) * roi[:, :, c]).astype(np.uint8)

            background_img[y1:y2, x1:x2] = roi
            return background_img, candidate_bbox, object_rotated, True

    if verbose >= 1:
        print(f"   尝试{max_attempts}次后仍无法放置物体（可能被obstacles或其他物体阻挡）")
    return background_img, None, None, False


def create_simple_polygon(object_img, bbox, label, epsilon_ratio=0.01):
    x1, y1, _, _ = bbox
    alpha_channel = object_img[:, :, 3]
    _, binary_mask = cv2.threshold(alpha_channel, 127, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)
    if not contours:
        x1, y1, x2, y2 = bbox
        return {
            "label": label,
            "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "shape_type": "polygon"
        }

    largest_contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(largest_contour, True)
    epsilon = epsilon_ratio * perimeter
    approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

    contour_points = approx_contour.reshape(-1, 2) + np.array([x1, y1])
    points = [[float(p[0]), float(p[1])] for p in contour_points]
    return {"label": label, "points": points, "shape_type": "polygon"}


def adjust_polygons_fast(original_shapes, object_shape, verbose=1):
    adjusted_shapes = []
    try:
        object_poly = Polygon(object_shape["points"])
        if not object_poly.is_valid:
            object_poly = object_poly.buffer(0)
        if not object_poly.is_valid:
            return original_shapes.copy()
    except Exception as e:
        if verbose >= 2:
            print(f"   物体多边形无效：{str(e)}")
        return original_shapes.copy()

    for shape in original_shapes:
        if shape["label"] == "animal" or shape["shape_type"] != "polygon":
            adjusted_shapes.append(shape)
            continue

        try:
            shape_poly = Polygon(shape["points"])
            if not shape_poly.is_valid:
                shape_poly = shape_poly.buffer(0)
            if not shape_poly.is_valid:
                adjusted_shapes.append(shape)
                continue

            if shape_poly.contains(object_poly):
                adjusted_shapes.append(shape)
                continue

            if not shape_poly.intersects(object_poly):
                adjusted_shapes.append(shape)
                continue

            difference = shape_poly.difference(object_poly)

            if difference.is_empty:
                if verbose >= 2:
                    print(f"   原多边形完全被物体覆盖，已移除：{shape['label']}")
                continue

            if isinstance(difference, Polygon):
                new_points = [[float(x), float(y)] for x, y in difference.exterior.coords[:-1]]
                if len(new_points) >= 3:
                    adjusted_shapes.append({
                        "label": shape["label"],
                        "points": new_points,
                        "shape_type": "polygon"
                    })
            elif isinstance(difference, MultiPolygon):
                for poly in difference.geoms:
                    new_points = [[float(x), float(y)] for x, y in poly.exterior.coords[:-1]]
                    if len(new_points) >= 3:
                        adjusted_shapes.append({
                            "label": shape["label"],
                            "points": new_points,
                            "shape_type": "polygon"
                        })
            else:
                if verbose >= 2:
                    print(f"   裁剪后无有效多边形，移除原多边形：{shape['label']}")

        except Exception as e:
            if verbose >= 2:
                print(f"   裁剪多边形出错：{str(e)}，保留原多边形")
            adjusted_shapes.append(shape)

    return adjusted_shapes


def update_json_fast(original_json_path, new_img_path, object_shapes):
    try:
        with open(original_json_path, "r", encoding="utf-8") as f:
            original_json = json.load(f)

        adjusted_shapes = original_json["shapes"].copy()
        for object_shape in object_shapes:
            adjusted_shapes = adjust_polygons_fast(adjusted_shapes, object_shape)
        adjusted_shapes.extend(object_shapes)

        with open(new_img_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "version": original_json.get("version", "4.5.6"),
            "flags": original_json.get("flags", {}),
            "shapes": adjusted_shapes,
            "imagePath": os.path.basename(new_img_path),
            "imageData": img_data,
            "imageWidth": original_json["imageWidth"],
            "imageHeight": original_json["imageHeight"]
        }
    except Exception as e:
        print(f"   更新JSON失败：{str(e)}")
        return None


def get_int_input(prompt, min_val, max_val, default):
    while True:
        user_input = input(f"{prompt}（{min_val}-{max_val}，默认{default}）：").strip()
        if not user_input:
            return default
        try:
            num = int(user_input)
            if min_val <= num <= max_val:
                return num
            else:
                print(f"❌ 请输入{min_val}~{max_val}之间的整数！")
        except ValueError:
            print(f"❌ 输入无效，请输入整数（如{default}）！")


def get_model_choice():
    while True:
        choice = input(
            "\n选择抠图模型：\n  1. 轻量模式（快）\n  2. 精准模式（较慢）\n输入1/2（默认1）：").strip()
        if not choice:
            return "small"
        elif choice in ("1", "2"):
            return "small" if choice == "1" else "precise"
        else:
            print("❌ 输入无效，请选1或2！")


def batch_process(source_folder, bg_json_folder, output_folder, max_objects, max_object_size, model_choice, cache_dir, label, target_label, verbose=1):
    processed_objects, cache_dir = batch_preprocess_objects(
        source_folder, max_object_size, model_choice, cache_dir, target_label, verbose)
    if not processed_objects:
        return

    bg_json_pairs = get_image_files_with_json(bg_json_folder)
    if not bg_json_pairs:
        if verbose >= 1:
            print("\n❌ 未找到带JSON的背景图")
        return

    os.makedirs(output_folder, exist_ok=True)
    if verbose >= 1:
        print(f"\n📌 结果保存至：{output_folder}")
        print(f"\n🎨 开始并行处理（{len(bg_json_pairs)}张图，进程数：{min(cpu_count(), 4)}）")

    task_args = [
        (bg_path, json_path, bg_name, processed_objects, output_folder, max_objects, label, verbose)
        for bg_path, json_path, bg_name in bg_json_pairs
    ]

    success_count = 0
    with Pool(1) as pool:
        for idx, (bg_name, success) in enumerate(pool.imap(process_single_background, task_args), 1):
            if verbose >= 1:
                status = "✅" if success else "❌"
                print(f"[{idx}/{len(bg_json_pairs)}] {status} {bg_name}")
            if success:
                success_count += 1

    if verbose >= 1:
        print("\n" + "=" * 60)
        print("📊 处理完成！")
        print(f"总数量：{len(bg_json_pairs)}，成功：{success_count}")
        print(f"结果路径：{os.path.abspath(output_folder)}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="智能多边形标注合成工具")
    parser.add_argument("source_folder", nargs='?', default=None, help="源文件图片文件夹路径")
    parser.add_argument("bg_json_folder", nargs='?', default=None, help="带JSON的背景图文件夹路径")
    parser.add_argument("output_folder", nargs='?', default=None, help="输出结果文件夹路径")
    parser.add_argument("--max-objects", type=int, default=None, help="每张图最多添加几个物体 (默认1)")
    parser.add_argument("--max-size", type=int, default=350, help="物体最大尺寸像素 (默认350)")
    parser.add_argument("--model", choices=["small", "precise"], default=None, help="模型: small=轻量(快), precise=精准(慢) (默认small)")
    parser.add_argument("--verbose", type=int, default=1, help="详细程度 0-2 (默认1)")
    parser.add_argument("--cache-dir", type=str, default=".cache", help="缓存目录 (默认 .cache)")
    parser.add_argument("--clear-cache", action="store_true", help="运行时清除所有缓存")
    parser.add_argument("--cache-expire-days", type=int, default=15, help="缓存过期天数 (默认15天)")
    parser.add_argument("--label", type=str, default=None, help="标注标签（必填）")

    args = parser.parse_args()

    target_label = None  # 用于标注抠图的标签

    # 无参数时走交互输入
    if args.source_folder is None:
        args.source_folder = get_valid_folder_path("请输入源文件图片文件夹路径：")

        # 自动检测源文件夹中的标注标签
        labels, json_count = detect_label_in_source_folder(args.source_folder)
        target_label = None
        detected_label = None  # 检测到的标签，用于后续标注
        if json_count > 0:
            print(f"ℹ️  检测到 {json_count} 张图片有 JSON 标注")
            if len(labels) == 1:
                detected_label = list(labels)[0]
                print(f"   检测到唯一标签：'{detected_label}'（直接回车使用此标签）")
            else:
                print(f"   发现多种标签: {labels}（直接回车使用其中之一需手动输入）")
            while True:
                chosen = input(f"请输入要抠图的标签名称（默认：'{detected_label}'）: ").strip()
                if not chosen:
                    if detected_label:
                        target_label = detected_label
                        break
                    print(f"❌ 标签不能为空，请重新输入！")
                else:
                    target_label = chosen
                    break
        else:
            # 没有 JSON 时，要求用户输入标签
            target_label = get_label_input()

        args.bg_json_folder = get_valid_folder_path("请输入带JSON的背景图文件夹路径：")
        args.output_folder = get_valid_folder_path("请输入输出结果文件夹路径：")

        # 标注标签：优先使用检测到的标签，否则要求用户输入
        if detected_label:
            default_label = detected_label
            print(f"\nℹ️  合成标注标签默认使用：'{default_label}'")
            chosen = input(f"请输入合成后的标注标签（直接回车使用：'{default_label}'）: ").strip()
            args.label = chosen if chosen else default_label
        else:
            args.label = get_label_input()

        args.max_objects = get_int_input("每张图最多添加几个物体", 1, 10, 3)
        max_size = get_int_input("物体最大尺寸（像素）", 100, 800, 350)
        args.model = get_model_choice()
    else:
        max_size = args.max_size
        # 命令行模式：label 必填
        if args.label is None:
            parser.error("--label 参数必填，请指定标签（如 cat、dog、car 等）")

    if args.max_objects is None:
        args.max_objects = 1
    if args.model is None:
        args.model = "small"

    # 处理缓存目录
    cache_dir = os.path.abspath(args.cache_dir)

    # 清理缓存
    if args.clear_cache and os.path.exists(cache_dir):
        if args.verbose >= 1:
            print(f"🧹 清除所有缓存：{cache_dir}")
        shutil.rmtree(cache_dir, ignore_errors=True)
        os.makedirs(cache_dir, exist_ok=True)
    elif args.cache_expire_days > 0:
        clean_expired_cache(cache_dir, args.cache_expire_days, args.verbose)

    print_welcome_message()
    print(f"\n⚠️  依赖安装：pip install shapely opencv-python pillow rembg numpy\n")

    max_object_size = (max_size, max_size)
    batch_process(args.source_folder, args.bg_json_folder, args.output_folder,
                  args.max_objects, max_object_size, args.model, cache_dir, args.label, target_label, args.verbose)


if __name__ == "__main__":
    main()
