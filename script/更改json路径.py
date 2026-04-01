import json
import os
import sys
import multiprocessing as mp
from tqdm import tqdm
from pathlib import Path


def process_single_json(args):
    """单文件处理函数（供多进程调用）：用JSON文件名匹配图片，更新imagePath"""
    json_path, image_folder_path, image_files, relative_image_path, image_extensions = args
    try:
        # 读取JSON文件
        with open(json_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                return f"❌ {json_path.name} 格式错误: {str(e)}"

        modified = False
        new_image_name = ""  # 初始化变量，避免未定义错误
        # 关键修改：用JSON文件名（去掉扩展名）作为匹配关键词
        json_base_name = json_path.stem  # 例如：clr_20251023-021535974_1.json → clr_20251023-021535974_1

        # 递归更新字典/列表中的imagePath字段（内部函数）
        def update_image_path(obj):
            nonlocal modified, new_image_name  # 声明为非局部变量，外部可访问
            if isinstance(obj, dict):
                for key, value in obj.items():
                    # 只关注imagePath字段（可根据需要添加其他字段，如'image'）
                    if key.lower() == 'imagepath' and isinstance(value, str):
                        # 用JSON基名匹配图片（忽略扩展名和大小写）
                        matching_imgs = [
                            img for img in image_files
                            if os.path.splitext(img)[0].lower() == json_base_name.lower()
                        ]
                        if matching_imgs:
                            # 取第一个匹配的图片，生成新的相对路径
                            new_image_name = matching_imgs[0]
                            new_image_path = os.path.normpath(
                                os.path.join(relative_image_path, new_image_name)
                            ).replace(os.sep, '/')  # 统一正斜杠
                            if value != new_image_path:
                                obj[key] = new_image_path
                                modified = True
                    # 递归处理嵌套结构
                    elif isinstance(value, (dict, list)):
                        update_image_path(value)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        update_image_path(item)

        # 执行更新
        update_image_path(data)

        # 保存修改后的文件
        if modified:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return f"✅ {json_path.name} → 更新为: {new_image_name}"
        else:
            # 两种情况：1. 没找到对应图片；2. imagePath已经是正确路径
            matching_imgs = [
                img for img in image_files
                if os.path.splitext(img)[0].lower() == json_base_name.lower()
            ]
            if not matching_imgs:
                return f"⚠️ {json_path.name} → 未找到对应图片（需同名：{json_base_name}.*）"
            else:
                return f"ℹ️ {json_path.name} → imagePath已正确（无需修改）"

    except Exception as e:
        return f"❌ {json_path.name} 处理失败: {str(e)}"


def update_image_paths_in_json(json_folder_path, image_folder_path):
    """多进程批量更新JSON文件中的图片路径（JSON文件名匹配图片名）"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
    json_folder = Path(json_folder_path).resolve()
    image_folder = Path(image_folder_path).resolve()

    # 验证目录有效性
    if not json_folder.is_dir():
        print(f"错误：JSON文件夹 '{json_folder}' 不存在或不是有效目录")
        return
    if not image_folder.is_dir():
        print(f"错误：图片文件夹 '{image_folder}' 不存在或不是有效目录")
        return

    # 获取所有JSON文件（绝对路径）
    try:
        json_files = [f for f in json_folder.glob("*.json") if f.is_file()]
    except Exception as e:
        print(f"读取JSON文件夹失败: {e}")
        return

    # 获取所有图片文件（仅文件名，用于匹配）
    try:
        image_files = [f.name for f in image_folder.glob("*")
                       if f.is_file() and f.suffix.lower() in image_extensions]
    except Exception as e:
        print(f"读取图片文件夹失败: {e}")
        return

    if not json_files:
        print("未找到任何JSON文件")
        return

    # 计算JSON到图片文件夹的相对路径（全局统一）
    relative_image_path = os.path.relpath(image_folder, json_folder).replace(os.sep, '/')
    print(f"JSON文件夹: {json_folder}")
    print(f"图片文件夹: {image_folder}")
    print(f"相对路径: {relative_image_path}")
    print(f"找到 {len(json_files)} 个JSON文件，{len(image_files)} 个图片文件")
    print(f"匹配规则：JSON文件名（不含扩展名）→ 图片文件名（不含扩展名）\n")

    # 准备多进程任务参数
    task_args = [
        (json_file, image_folder, image_files, relative_image_path, image_extensions)
        for json_file in json_files
    ]

    # 多进程处理
    cpu_count = mp.cpu_count()
    print(f"使用 {cpu_count} 个进程处理...")

    with mp.Pool(processes=cpu_count) as pool:
        results = list(tqdm(pool.imap(process_single_json, task_args), total=len(json_files)))

    # 打印处理结果汇总
    print("\n处理结果：")
    for res in results:
        print(res)

    print("\n🎉 全部处理完成")


if __name__ == "__main__":
    # 解决Windows多进程兼容问题
    if sys.platform.startswith('win'):
        mp.set_start_method('spawn', force=True)

    # 命令行参数或交互式输入
    if len(sys.argv) == 3:
        json_folder = sys.argv[1]
        image_folder = sys.argv[2]
    else:
        print("请输入JSON文件目录和图片文件目录")
        json_folder = input("JSON文件目录: ").strip()
        image_folder = input("图片文件目录: ").strip()

    update_image_paths_in_json(json_folder, image_folder)
    '''1112'''