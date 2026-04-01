import os
import shutil

# 支持的图片文件扩展名
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
# 关联的文件扩展名（JSON）
ASSOCIATED_EXTENSIONS = {'.json'}
# 所有需要处理的扩展名
ALL_EXTENSIONS = IMAGE_EXTENSIONS.union(ASSOCIATED_EXTENSIONS)


def get_valid_directory(prompt: str) -> str:
    """
    提示用户输入一个有效的目录路径，如果目录不存在，提示重新输入（除非是目标目录且允许创建）。
    """
    while True:
        dir_path = input(prompt).strip()
        if not dir_path:
            print("❌ 路径不能为空，请重新输入。")
            continue
        if os.path.isdir(dir_path):
            return dir_path
        else:
            print(f"❌ 目录不存在：'{dir_path}'，请检查路径后重新输入。")


def get_prefix() -> str:
    """
    提示用户输入要添加到文件名前的前缀，不能包含非法字符，也不能为空。
    """
    while True:
        prefix = input("请输入要添加到文件名前的前缀（如 'new_'、'vacation_'，不能留空）: ").strip()
        if not prefix:
            print("❌ 前缀不能为空，请重新输入。")
        elif any(c in prefix for c in r'\/:*?"<>|'):
            print("❌ 前缀中不能包含以下字符：\\ / : * ? \" < > | ，请重新输入。")
        else:
            return prefix


def get_associated_files(file_path: str) -> list:
    """
    获取与指定文件同名的所有关联文件（如JSON文件）
    """
    associated_files = []
    file_dir, file_name = os.path.split(file_path)
    name_without_ext, _ = os.path.splitext(file_name)

    # 遍历目录下所有同名的关联文件
    for ext in ASSOCIATED_EXTENSIONS:
        associated_file_name = f"{name_without_ext}{ext}"
        associated_file_path = os.path.join(file_dir, associated_file_name)
        if os.path.isfile(associated_file_path):
            associated_files.append(associated_file_path)

    return associated_files


def process_files_and_rename(source_dir: str, target_dir: str, prefix: str):
    """
    从源目录中找到所有图片和关联的JSON文件，在文件名前添加前缀，复制到目标目录。
    """
    processed_count = {
        'images': 0,
        'json': 0
    }

    # 如果目标目录不存在，则创建
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"✅ 已创建目标目录：{target_dir}")

    print("\n🔍 开始扫描并处理文件...\n")

    # 记录已经处理过的文件（避免重复处理JSON）
    processed_files = set()

    for filename in os.listdir(source_dir):
        file_path = os.path.join(source_dir, filename)

        # 只处理文件，跳过目录
        if os.path.isfile(file_path) and file_path not in processed_files:
            name, ext = os.path.splitext(filename)
            ext_lower = ext.lower()

            # 处理图片文件
            if ext_lower in IMAGE_EXTENSIONS:
                # 重命名并复制图片文件
                new_filename = f"{prefix}{filename}"
                new_file_path = os.path.join(target_dir, new_filename)
                shutil.copy2(file_path, new_file_path)
                print(f"📸 已复制并重命名: {filename} → {new_filename}")
                processed_count['images'] += 1
                processed_files.add(file_path)

                # 查找并处理关联的JSON文件
                associated_files = get_associated_files(file_path)
                for assoc_file_path in associated_files:
                    assoc_filename = os.path.basename(assoc_file_path)
                    new_assoc_filename = f"{prefix}{assoc_filename}"
                    new_assoc_file_path = os.path.join(target_dir, new_assoc_filename)
                    shutil.copy2(assoc_file_path, new_assoc_file_path)
                    print(f"📄 已复制并重命名: {assoc_filename} → {new_assoc_filename}")
                    processed_count['json'] += 1
                    processed_files.add(assoc_file_path)

            # 单独处理JSON文件（如果没有对应的图片）
            elif ext_lower in ASSOCIATED_EXTENSIONS:
                new_filename = f"{prefix}{filename}"
                new_file_path = os.path.join(target_dir, new_filename)
                shutil.copy2(file_path, new_file_path)
                print(f"📄 已复制并重命名: {filename} → {new_filename}")
                processed_count['json'] += 1
                processed_files.add(file_path)

    print(f"\n🎉 处理完成！")
    print(f"📸 共处理了 {processed_count['images']} 张图片")
    print(f"📄 共处理了 {processed_count['json']} 个JSON文件")
    print(f"📁 重命名后的文件已保存到目录：{target_dir}")


def main():
    print("=" * 60)
    print("🖼️  📄 图片&JSON批量重命名工具")
    print("=" * 60)
    print("本工具用于：")
    print("1. 选择一个含有图片/JSON的文件夹（源目录）")
    print("2. 指定一个新的文件夹（目标目录，用于存放重命名后的文件）")
    print("3. 给所有图片和JSON文件名前加上自定义前缀（如 'new_'、'2024_' 等）")
    print("4. 将重命名后的文件复制到新目录，原文件保持不变")
    print("5. 自动匹配同名的图片和JSON文件，一起重命名")
    print("=" * 60)

    # --- 交互式获取用户输入 ---
    source_directory = get_valid_directory("📂 请输入源文件目录路径（包含图片/JSON的文件夹）: ")

    target_directory = get_valid_directory("📂 请输入目标目录路径（存放重命名后文件的新文件夹，如不存在将自动创建）: ")

    # 特殊提示：如果目标目录和源目录一样，给出警告
    if os.path.abspath(source_directory) == os.path.abspath(target_directory):
        print("⚠️  警告：源目录和目标目录相同，重命名后的文件将覆盖原文件（如果文件名冲突）！")
        confirm = input("你确定要继续吗？(输入 y 继续，其他键退出): ").strip().lower()
        if confirm != 'y':
            print("❌ 操作已取消。")
            return

    custom_prefix = get_prefix()

    # --- 开始处理 ---
    print("\n" + "=" * 60)
    print("🚀 开始处理文件...")
    process_files_and_rename(source_directory, target_directory, custom_prefix)

    print("\n✅ 操作完成！你可以去目标目录查看重命名后的文件。")


if __name__ == "__main__":
    main()