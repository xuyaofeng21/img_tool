

import os
import shutil
from pathlib import Path
import imagehash
from PIL import Image


def compute_phash(img_path, hash_cache):
    """计算图片的感知哈希（带缓存）"""
    if img_path in hash_cache:
        return hash_cache[img_path]
    try:
        h = imagehash.phash(Image.open(img_path))
        hash_cache[img_path] = h
        return h
    except Exception as e:
        print(f"  [WARN] 无法处理 {img_path}: {e}")
        hash_cache[img_path] = None
        return None


def hamming_distance(h1, h2):
    """计算两个哈希的汉明距离"""
    return h1 - h2


def select_diverse_images(input_dir, output_dir, select_ratio=0.1, hamming_thresh=10):
    """
    从输入目录中选择场景多样的图片

    Args:
        input_dir: 包含所有 PNG 图片的目录
        output_dir: 精选图片的输出目录
        select_ratio: 精选比例（如 0.1 表示 10%）
        hamming_thresh: pHash 汉明距离阈值，超过此值才视为不同场景
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有 PNG 文件并按文件名排序（文件名即时间戳）
    png_files = sorted([f for f in input_dir.glob("*.png")])
    total = len(png_files)
    print(f"共找到 {total} 张图片")

    if total == 0:
        print("没有找到图片！")
        return

    target_count = max(1, int(total * select_ratio))
    print(f"按 {select_ratio*100:.0f}% 比例计算，目标精选 {target_count} 张")

    # Step 1: 计算所有图片的 pHash（带缓存）
    print("Step 1: 计算所有图片的感知哈希...")
    hash_cache = {}
    hashes = []
    for i, f in enumerate(png_files):
        h = compute_phash(f, hash_cache)
        hashes.append(h)
        if (i + 1) % 500 == 0:
            print(f"  已处理 {i + 1}/{total}")

    # 过滤掉计算失败的图片
    valid_files = [f for f, h in zip(png_files, hashes) if h is not None]
    valid_hashes = [h for h in hashes if h is not None]
    print(f"成功计算 {len(valid_hashes)} 个哈希")

    # Step 2: pHash 去重筛选
    print(f"Step 2: pHash 去重筛选 (阈值={hamming_thresh})...")
    selected_files = []
    selected_hashes = []

    for i, (f, h) in enumerate(zip(valid_files, valid_hashes)):
        if not selected_hashes:
            selected_files.append(f)
            selected_hashes.append(h)
        else:
            # 与已选图片逐一比较，取最小汉明距离
            min_dist = min(hamming_distance(h, sh) for sh in selected_hashes)
            if min_dist > hamming_thresh:
                selected_files.append(f)
                selected_hashes.append(h)

        if (i + 1) % 500 == 0:
            print(f"  已处理 {i + 1}/{len(valid_files)}, 当前选中 {len(selected_files)} 张")

    print(f"去重后初步选中 {len(selected_files)} 张")

    # Step 3: 时序均匀采样补足到 target_count
    print(f"Step 3: 时序均匀采样，目标 {target_count} 张...")

    if len(selected_files) >= target_count:
        # 从已选图片中均匀采样
        step = len(selected_files) / target_count
        final_files = [selected_files[int(i * step)] for i in range(target_count)]
    else:
        # 需要补充：从剩余图片中按时间均匀分布选择差异最大的
        selected_set = set(selected_files)
        remaining_files = [f for f in valid_files if f not in selected_set]

        # 将时间线均匀切分
        n_slots = target_count - len(selected_files)
        slot_size = len(remaining_files) / n_slots if n_slots > 0 else len(remaining_files)

        supplement = []
        supplement_hashes = []  # 缓存已选补充图片的哈希

        for slot in range(n_slots):
            start_idx = int(slot * slot_size)
            end_idx = int((slot + 1) * slot_size)
            slot_files = remaining_files[start_idx:end_idx]
            if not slot_files:
                continue

            # 在槽内选择与所有已选图片差异最大的
            best_file = None
            best_min_dist = -1
            all_candidate_hashes = selected_hashes + supplement_hashes
            for rf in slot_files:
                rh = compute_phash(rf, hash_cache)
                if rh is None:
                    continue
                min_dist = min(hamming_distance(rh, sh) for sh in all_candidate_hashes)
                if min_dist > best_min_dist:
                    best_min_dist = min_dist
                    best_file = rf

            if best_file:
                supplement.append(best_file)
                supplement_hashes.append(hash_cache[best_file])

        final_files = selected_files + supplement

    print(f"最终选中 {len(final_files)} 张图片")

    # Step 4: 复制到输出目录
    print("Step 4: 复制图片到输出目录...")
    for f in final_files:
        shutil.copy2(f, output_dir / f.name)

    print(f"完成！精选图片已保存到: {output_dir}")
    print(f"共复制 {len(final_files)} 张图片")


def main():
    input_dir = input("输入目录（包含PNG图片）: ").strip().strip('"').strip("'")
    output_dir = input("输出目录（精选图片保存位置）: ").strip().strip('"').strip("'")
    ratio_str = input("精选比例（默认0.1，即10%%）: ").strip()
    ratio = float(ratio_str) if ratio_str else 0.1
    hamming_str = input("pHash汉明距离阈值（默认10）: ").strip()
    hamming = int(hamming_str) if hamming_str else 10

    select_diverse_images(input_dir, output_dir, select_ratio=ratio, hamming_thresh=hamming)


if __name__ == "__main__":
    main()
