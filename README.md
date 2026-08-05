# AI视频转文字工具

一个功能强大的视频音频转文字工具，支持B站视频下载、语音识别、文本处理等功能。

## 功能特点

- **B站视频下载**：自动从B站视频链接提取音频，无需手动输入cookie
- **语音识别**：支持多种语音识别模型
  - Paraformer-large 离线版 + VAD + 标点（中文优化，高精度带标点）
  - Paraformer 流式版（实时场景）
- **批量处理**：支持批量处理音频文件
- **实时识别**：支持实时语音识别功能
- **文本处理**：自动分段、格式化转录结果
- **多语言支持**：支持中文、英文等多种语言

## 安装说明

1. 克隆或下载本项目到本地
2. 安装依赖包：
   ```
   pip install -r requirements.txt
   ```
3. 下载基石模型（已存在会自动跳过）：
   ```
   python download.py
   ```

## 使用方法

### B站视频下载

使用`GetBiliBiliVideo.py`从B站下载视频音频：

```python
from GetBiliBiliVideo import getvideo

# 下载B站视频音频
mp3_file, title = getvideo("https://www.bilibili.com/video/BV1xx411c79H", "./音频")
```

### 语音识别

使用`transcription.py`进行语音识别：

```python
# 命令行运行
python transcription.py
# 按提示输入音频文件路径
```

或者使用Paraformer-large模型：

```python
# 命令行运行
python transcription_paraformer.py
# 按提示输入音频文件路径
```

### 实时识别

使用`实时识别`目录下的工具进行实时语音识别：

```python
# 进入实时识别目录
cd 实时识别
# 运行实时识别程序
python 实时识别.py
```

## 项目结构

```
AI-VedioToText/
├── GetBiliBiliVideo.py     # B站视频下载模块
├── download.py             # 基石模型下载（已有自动跳过）
├── transcription.py        # 语音识别模块（Paraformer）
├── main_window.py          # 主窗口界面
├── translator.py           # 翻译模块
├── model/                  # 模型目录（基石）
│   ├── vad/                # VAD 语音活动检测
│   ├── punc/               # CT-PUNC 标点恢复
│   └── paraformer/         # Paraformer 离线版 / 流式版
├── 实时识别/                # 实时识别功能目录
├── 原文/                   # 识别结果保存目录
└── 音频/                   # 音频文件保存目录
```

## 模型说明

本项目使用了多种语音识别模型：

1. **SenseVoice模型**：默认使用的语音识别模型，适合一般场景
2. **Paraformer-large模型**：高精度语音识别模型，适合需要更高准确度的场景
3. **Paraformer-zh模型**：中文优化语音识别模型，带标点符号
4. **VAD模型**：用于语音活动检测，提高识别准确性

## 注意事项

- 首次运行时会自动下载所需模型，请确保网络连接正常
- B站视频下载功能会自动获取cookie，无需手动配置
- 音频文件支持格式：.wav, .mp3, .m4a, .flac
- 识别结果保存在"原文"目录下

## 许可证

本项目仅供学习和研究使用，请勿用于商业用途。

## 贡献

欢迎提交问题和改进建议，共同完善本项目。
