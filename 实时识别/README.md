# 实时语音识别系统（实时识别子项目）

基于 Paraformer-Offline 的实时字幕工具：捕获系统音频 → 实时识别 → 字幕显示 → 可选实时翻译。

## 项目简介

复用项目根目录的统一 ASR 后端（Paraformer + VAD + 标点）与 LLM 翻译后端（Ollama / DeepSeek），
与主程序共用同一套 `.env` 配置。

## 主要功能

- 实时系统音频捕获（soundcard，16kHz 默认）
- 实时语音识别（Paraformer-Offline + VAD 过滤静音 + 标点恢复）
- 统一字幕窗口（仅原文 / 仅翻译 / 原文+翻译 三种显示模式，可随时切换）
- 实时翻译（复用根目录 `llm_backend.py`：跟随 `.env` 的 `LLM_PROVIDER`）
- 目标语言运行中可随时切换（中/英/日/韩/法/西）
- 字幕窗口：透明度 / 字体大小 / 缓冲区大小可调
- 字幕窗口无按钮干扰，只显示字幕；控制按钮全部在主窗口

## 运行前提

1. 安装依赖（与主项目共用环境）：
   ```bash
   pip install -r ../requirements.txt
   ```
2. 下载基石模型（若缺失，启动时会提示）：
   ```bash
   python ../download.py
   ```
3. （可选）配置翻译服务商：复制根目录 `.env.example` 为 `.env`，设置 `LLM_PROVIDER` 与对应 Key

## 使用说明

```bash
python 实时识别.py
```

### 主界面控制

| 控件 | 说明 |
|---|---|
| 采样率 | 音频采样率（默认 16000） |
| 目标语言 | 翻译目标语言，运行中可切换 |
| 字幕显示 | 仅原文 / 仅翻译 / 原文+翻译 |
| 显示字幕 | 勾选=显示字幕窗口，取消=隐藏 |
| 字幕设置 | 透明度 / 字体大小 / 缓冲区大小 |
| 开始 / 停止 | 控制识别 |
| 生成总结 | 对本次识别内容生成总结 |

### 字幕窗口

- 仅显示字幕内容（原文白色、翻译金色）
- **拖动**：按住窗口任意位置拖动
- **调整大小**：拖动窗口边缘
- 无任何按钮，设置/隐藏均由主窗口控制

## 输出文件（固定路径，不随启动目录变化）

- `原文/transcript_时间戳.txt` — 识别原文
- `翻译/translation_时间戳.txt` — 翻译结果
- `总结/summary_时间戳.txt` — 生成的总结

## 文件结构

- `实时识别.py` — 主程序（音频捕获 + 识别线程 + 主窗口）
- `subtitle.py` — 字幕窗口（三种显示模式）+ 字幕设置对话框
- `translator.py` — 翻译引擎（复用根目录 llm_backend，Ollama / DeepSeek）
- `settings_manager.py` — 字幕设置持久化（subtitle_settings.json）
- `subtitle.ui` — 字幕窗口 UI 定义

## 注意事项

1. 识别模型（Paraformer + VAD + 标点）缺失时会提示下载，约 1.5GB
2. 翻译跟随根目录 `.env` 配置：`LLM_PROVIDER=deepseek` 走 DeepSeek 云端（需真实 API Key），`ollama` 走本地 Ollama
3. 确保系统音频设备正常工作（扬声器/耳机可被捕获）
4. 建议使用耳机或外接音箱获得更清晰的识别效果
