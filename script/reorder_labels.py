import json
import os

def reorder_shapes(json_path):
    """重新排序shapes，把station移到最前面，数字标签在station上面"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    shapes = data.get('shapes', [])

    # 分离station和其他标签
    station_shapes = [s for s in shapes if s.get('label') == 'station']
    other_shapes = [s for s in shapes if s.get('label') != 'station']

    # 重新排序：station在最前面（底层），其他标签在station上面
    data['shapes'] = station_shapes + other_shapes

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"已处理: {json_path}")

def process_directory(directory):
    """处理目录下的所有JSON文件"""
    for filename in os.listdir(directory):
        if filename.endswith('.json'):
            json_path = os.path.join(directory, filename)
            reorder_shapes(json_path)

if __name__ == '__main__':
    directory = input("请输入JSON文件所在目录路径: ").strip()
    if not directory:
        print("路径不能为空！")
    elif not os.path.isdir(directory):
        print(f"目录不存在: {directory}")
    else:
        process_directory(directory)
        print("完成！")
