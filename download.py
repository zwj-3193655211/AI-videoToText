"""
模型下载模块

本模块用于下载语音识别所需的模型文件，包括：
1. VAD模型：用于语音活动检测
2. SenseVoice模型：用于语音识别
"""

import os
from modelscope.hub.snapshot_download import snapshot_download
import sys

def download_model(model_id, cache_dir, model_name):
    """下载模型文件"""
    try:
        print(f"正在下载{model_name}...")
        model_dir = snapshot_download(
            model_id,
            cache_dir=cache_dir,
            revision='master'
        )
        print(f"✅ {model_name}已下载至: {model_dir}")
        return True
    except Exception as e:
        print(f"❌ {model_name}下载失败: {str(e)}")
        return False

def main():
    """主函数"""
    # 创建模型目录
    os.makedirs('model', exist_ok=True)
    
    # 下载VAD模型
    vad_success = download_model(
        'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        'model/vad',
        '语音活动检测模型'
    )
    
    # 下载SenseVoice模型
    sensevoice_success = download_model(
        'iic/SenseVoiceSmall',
        'model/sensevoice',
        'SenseVoice模型'
    )
    
    # 检查下载结果
    if not vad_success or not sensevoice_success:
        print("\n❌ 部分模型下载失败，请检查错误信息并重试")
        sys.exit(1)
    
    print("\n✅ 所有模型下载完成！")

if __name__ == "__main__":
    main()