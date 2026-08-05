# AI视频转文字工具

一个功能强大的视频/音频转文字工具，支持 B 站视频解析、本地文件转录、DeepSeek/Ollama 翻译总结、实时字幕识别。

## 功能特点

- **B 站视频解析**：自动获取 Cookie 提取音频，无需手动配置
- **本地文件转录**：支持视频/音频文件（mp4 / avi / mov / mp3 / m4a）
- **高精度语音识别**：FunASR Paraformer-Large + FSMN-VAD + CT-PUNC 标点（唯一后端，实时/离线通用）
- **翻译与总结独立勾选**：可选"生成翻译" / "生成总结" / 两者
- **LLM 双后端**：本地 Ollama 或云端 DeepSeek V4（跟随 `.env` 配置）
- **实时识别**：系统音频捕获 → 实时字幕 → 可选实时翻译（统一字幕窗口：仅原文 / 仅翻译 / 原文+翻译）
- **模型自动下载**：模型缺失时弹窗一键下载（约 1.5GB，下载后自动加载）
- **现代化 UI**：浅色主题、交互反馈（保存/测试/校验 Toast）、彩色日志、状态栏指示

## 安装说明

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 下载基石模型（VAD + 标点 + Paraformer-Offline，约 1.5GB）
python download.py
# 也可直接运行主程序，模型缺失时会弹窗询问一键下载
```

> 系统需安装 **ffmpeg**（视频转音频用）：https://ffmpeg.org/

## 配置（.env）

复制 `.env.example` 为 `.env` 并填写：

```ini
# LLM 服务商：ollama（本地）/ deepseek（云端）
LLM_PROVIDER=deepseek

# DeepSeek（https://platform.deepseek.com 申请）
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_MODEL=deepseek-v4-flash   # flash(免费)/ v4-pro / v4-pro-max

# Ollama（本地，LLM_PROVIDER=ollama 时生效）
OLLAMA_MODEL=qwen2.5:7b
```

也可以在应用内点击左下角 **⚙ 设置** 完成全部配置（保存后 LLM 立即生效）。

## 使用方法

### 主程序（转录 + 翻译 + 总结）

```bash
python main_window.py
```

1. **B站视频解析**：粘贴 B 站分享链接 → 选择目标语言 → 勾选翻译/总结 → 提交
2. **本地视频解析**：选择本地文件 → 同上
3. 结果输出：
   - 转录原文 → `原文/`
   - 翻译 → `output/{标题}_translation.txt`
   - 总结（单独勾选时）→ `output/{标题}_summary.txt`

### 实时识别（系统音频 → 实时字幕）

```bash
python 实时识别/实时识别.py
```

- 控制面板：采样率 / 目标语言 / 字幕显示模式（仅原文、仅翻译、原文+翻译）/ 显示字幕 / 字幕设置
- 输出目录：`实时识别/原文`、`实时识别/翻译`、`实时识别/总结`（固定路径，不随启动目录变化）

## 项目结构

```
AI-VedioToText/
├── main_window.py          # 主程序入口（转录/翻译/总结 GUI）
├── main.ui                 # 主窗口 UI 定义
├── asr_backend.py          # ASR 后端抽象（FunASR Paraformer + VAD + 标点）
├── transcription.py        # 转录兼容层（旧接口 LocalASR）
├── translator.py           # 翻译/总结（Ollama / DeepSeek）
├── llm_backend.py          # LLM 后端抽象（Ollama / DeepSeek）
├── settings_dialog.py      # 设置面板（.env 读写 + 交互反馈）
├── config.py               # 全局配置读取（.env）
├── ui_theme.py             # 统一 UI 主题（Fusion + 浅色 palette + QSS）
├── download.py             # 基石模型下载（VAD/PUNC/Paraformer）
├── GetBiliBiliVideo.py     # B站视频解析（自动获取 Cookie）
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板（复制为 .env 填写）
├── 实时识别/               # 实时字幕识别子项目
│   ├── 实时识别.py         # 实时识别主程序
│   ├── subtitle.py         # 字幕窗口（统一显示模式）
│   ├── translator.py       # 实时翻译（复用 llm_backend）
│   └── settings_manager.py # 字幕设置持久化
├── model/                  # 模型目录（download.py 下载）
│   ├── vad/                # FSMN-VAD 语音活动检测
│   ├── punc/               # CT-PUNC 标点恢复
│   └── paraformer/         # Paraformer-Offline（唯一 ASR 后端）
├── 原文/                   # 转录原文输出
├── 音频/                   # 下载/转换的音频
└── output/                 # 翻译/总结结果
```

## 语音识别模型说明

- **Paraformer-Large（offline）**：唯一 ASR 后端。内部集成 FSMN-VAD（过滤静音/切句）+ CT-PUNC（标点恢复），中文高精度，实时与离线场景通用。
- 模型由 `download.py` 下载（ModelScope），首次运行自动检测，缺失可一键下载。
- 曾评估的 Paraformer-Streaming（流式）实测准确率/速度均劣于 offline，已移除。

## 常见问题

- **任务栏无图标**：确保使用真正的 ICO 文件（项目已内置），且以 `python main_window.py` 正常启动
- **翻译无结果**：检查 `.env` 中 `DEEPSEEK_API_KEY` 是否真实（非 `sk-xxx` 占位符），可在 ⚙ 设置里"测试连接"
- **运行环境**：建议使用独立 conda/venv 环境（本项目在 `avtt` 环境验证通过，Python 3.10）

## 许可证

本项目仅供学习和研究使用，请勿用于商业用途。
