"""重新下载 VAD 模型给 SenseVoice 用"""
import os
from modelscope import snapshot_download

# 用临时目录下载，避免 funasr 路径冲突
vad_dir = snapshot_download(
    "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    cache_dir=r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS\funasr_cache",
)
print(f"VAD model: {vad_dir}")
print(f"files: {os.listdir(vad_dir)[:5]}")
