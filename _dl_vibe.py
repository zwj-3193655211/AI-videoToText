"""拉 B 站音频到 output/comparison/，仅音频"""
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, r"D:\Desktop_Archive\AI-VedioToText")
from GetBiliBiliVideo import get_video_audio

URL = "https://www.bilibili.com/video/BV1VC7g6vE9f"
OUT = r"D:\Desktop_Archive\AI-VedioToText\output\comparison"

def log(msg, level="info"):
    print(f"[{level.upper()}] {msg}", flush=True)

audio, video, title = get_video_audio(URL, OUT, fetch_type="audio", log_callback=log)
if not audio:
    sys.exit(1)

src = os.path.join(OUT, audio)
print(f"\n下载完成: {src}  ({os.path.getsize(src)/1024/1024:.1f} MB)")
print(f"标题: {title}")
