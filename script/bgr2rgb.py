import cv2
import os
import numpy as np

def convert_rgb_to_bgr_and_save(input_folder, output_folder):
    """
    读取输入文件夹中的所有图像，将RGB转换为BGR，并保存到输出文件夹
    
    Args:
        input_folder (str): 输入图像文件夹路径
        output_folder (str): 输出图像文件夹路径
    """
    # 检查输入文件夹是否存在
    if not os.path.exists(input_folder):
        print(f"错误：输入文件夹 '{input_folder}' 不存在")
        return
    
    # 创建输出文件夹（如果不存在）
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"创建输出文件夹: {output_folder}")
    
    # 支持的图片格式
    supported_formats = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif')
    
    # 获取输入文件夹中的所有文件
    files = os.listdir(input_folder)
    image_files = [f for f in files if f.lower().endswith(supported_formats)]
    
    if not image_files:
        print(f"在文件夹 '{input_folder}' 中未找到支持的图片文件")
        return
    
    print(f"找到 {len(image_files)} 个图片文件")
    
    # 处理每个图像文件
    for filename in image_files:
        input_path = os.path.join(input_folder, filename)
        
        try:
            # 使用OpenCV读取图像
            # 注意：OpenCV默认以BGR格式读取图像
            img = cv2.imread(input_path)
            
            if img is None:
                print(f"警告：无法读取图像 {filename}，跳过")
                continue
            
            # 如果图像是3通道的，进行RGB到BGR的转换
            # 注意：由于OpenCV默认读取为BGR，这里假设源图像实际上是RGB格式
            # 所以我们需要将BGR转回RGB，然后再转回BGR（这实际上等于原图）
            # 但根据需求，我们执行：RGB -> BGR 转换
            if len(img.shape) == 3 and img.shape[2] == 3:
                # 假设当前img是RGB格式（实际上OpenCV读取的是BGR）
                # 所以我们需要先假设它是RGB，然后转换为BGR
                # 但实际上更常见的场景是：从其他库读取的RGB图像需要转换为OpenCV的BGR格式
                # 这里我们按照题目要求：RGB -> BGR
                img_rgb = img  # 假设这是RGB格式
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            else:
                # 对于灰度图像或其他格式，直接保存
                img_bgr = img
            
            # 构建输出路径
            output_path = os.path.join(output_folder, filename)
            
            # 保存图像
            success = cv2.imwrite(output_path, img_bgr)
            
            if success:
                print(f"成功处理并保存: {filename}")
            else:
                print(f"错误：无法保存图像 {filename}")
                
        except Exception as e:
            print(f"处理图像 {filename} 时发生错误: {str(e)}")
    
    print("所有图像处理完成")

def main():
    # 在这里指定输入输出路径
    #input_folder = "/data/debug/20260226_grassland_error"   # 修改为你的输入文件夹路径
    #input_folder = "/data/error"   # 修改为你的输入文件夹路径
    input_folder = "D:/img_tool/select"  # 修改为你的输入文件夹路径
    #output_folder = "/data/debug/20260226_grassland_error_rgb" # 修改为你的输出文件夹路径
    #output_folder = "/data/error_rgb" # 修改为你的输出文件夹路径
    output_folder ="D:/img_tool/bad_img" # 修改为你的输出文件夹路径

    # 调用转换函数
    convert_rgb_to_bgr_and_save(input_folder, output_folder)

if __name__ == "__main__":
    main()
