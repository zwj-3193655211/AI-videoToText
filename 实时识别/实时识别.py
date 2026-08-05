import os
import sys
import soundcard as sc
import numpy as np
import logging
from datetime import datetime
import torch
# 复用项目根目录的统一 ASR 后端（路径/GPU/VAD/标点全部由 asr_backend 管理）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# 本目录优先，避免与根目录同名模块（translator.py）歧义
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from asr_backend import FunASRBackend
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QTextEdit, QLabel,
                               QComboBox, QSpinBox, QMessageBox, QDoubleSpinBox,
                               QCheckBox, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
import subtitle as _subtitle_mod
SubtitleWindow = _subtitle_mod.SubtitleWindow
import threading
from PySide6.QtGui import QIcon
from translator import TranslationWorker, TranslationManager
from queue import Queue
import time
import re
from settings_manager import SettingsManager
import requests

class AudioBuffer:
    """音频数据缓冲区类"""

    def __init__(self, data, timestamp, sequence):
        self.data = data
        self.timestamp = timestamp
        self.sequence = sequence


class AudioCaptureThread(QThread):
    """音频捕获线程"""
    status_signal = Signal(str)
    error_signal = Signal(str)
    buffer_ready = Signal(AudioBuffer)  # 新增信号，用于通知缓冲区就绪

    def __init__(self, sample_rate=16000):
        super().__init__()
        self.sample_rate = sample_rate
        self.running = False
        self.buffer = np.array([], dtype=np.float32)
        self.buffer_size = int(sample_rate * 0.1)  # 100ms 缓冲区
        self.sequence = 0  # 添加序号计数器

        # 获取设置管理器实例
        self.settings_manager = SettingsManager()
        self.buffer_duration = self.settings_manager.get_buffer_duration()

        self._buffer_lock = threading.Lock()  # 添加线程锁

    def set_buffer_duration(self, duration):
        """设置缓冲区时长"""
        with self._buffer_lock:
            self.buffer_duration = duration
            # 如果当前缓冲区超过新的时长，清空缓冲区
            max_samples = int(self.sample_rate * duration)
            if len(self.buffer) > max_samples:
                self.buffer = np.array([], dtype=np.float32)
            # 更新设置管理器中的值
            self.settings_manager.update_settings(buffer_duration=duration)
            self.status_signal.emit(f"缓冲区大小已调整为 {duration} 秒")

    def run(self):
        try:
            self.running = True
            self.status_signal.emit("正在初始化音频捕获...")

            # 获取默认扬声器
            default_speaker = sc.default_speaker()
            self.loopback = sc.get_microphone(
                id=str(default_speaker.id),
                include_loopback=True
            )

            self.status_signal.emit(f"已初始化环回设备: {default_speaker.name}")

            with self.loopback.recorder(samplerate=self.sample_rate) as mic:
                while self.running:
                    try:
                        # 捕获音频数据
                        audio_data = mic.record(numframes=self.buffer_size)

                        # 转换为单声道并归一化
                        if audio_data.ndim > 1:
                            audio_data = np.mean(audio_data, axis=1)
                        audio_data = audio_data.astype(np.float32)

                        # 添加到缓冲区
                        with self._buffer_lock:
                            self.buffer = np.append(self.buffer, audio_data)

                            # 当缓冲区达到设定大小时发送数据
                            max_samples = int(self.sample_rate * self.buffer_duration)
                            if len(self.buffer) >= max_samples:
                                # 创建缓冲区对象并发送信号
                                buffer_obj = AudioBuffer(
                                    self.buffer.copy(),  # 使用copy避免数据竞争
                                    datetime.now(),
                                    self.sequence
                                )
                                self.buffer_ready.emit(buffer_obj)

                                # 清空缓冲区并更新序号
                                self.buffer = np.array([], dtype=np.float32)
                                self.sequence += 1

                    except Exception as e:
                        self.error_signal.emit(f"音频捕获错误: {e}")
                        time.sleep(0.1)

        except Exception as e:
            self.error_signal.emit(f"音频捕获线程异常: {e}")
        finally:
            self.running = False

    def stop(self):
        """停止音频捕获"""
        self.running = False


class TranscriptionThread(QThread):
    """转录线程"""
    text_signal = Signal(str)
    translation_signal = Signal(str)
    status_signal = Signal(str)
    error_signal = Signal(str)
    has_content_signal = Signal(bool)  # 添加新信号

    def __init__(self, output_file=None):
        super().__init__()
        self.running = False
        self.audio_queue = Queue()  # 新增音频数据队列
        self.last_sequence = -1  # 用于跟踪处理顺序

        # 设置输出文件路径（固定存到实时识别目录下，与启动目录无关）
        if output_file is None:
            # 创建原文目录
            output_dir = os.path.join(_THIS_DIR, "原文")
            os.makedirs(output_dir, exist_ok=True)
            # 使用时间戳创建文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_file = os.path.join(output_dir, f"transcript_{timestamp}.txt")
            # 创建输出目录
            output_dir = os.path.join(_THIS_DIR, "翻译")
            os.makedirs(output_dir, exist_ok=True)
            self.translation_file = os.path.join(output_dir, f"translation_{timestamp}.txt")
        else:
            self.output_file = output_file
            base_name = os.path.splitext(output_file)[0]
            self.translation_file = f"{base_name}_translation.txt"

        self.subtitle_index = 1
        self.last_text = ""  # 用于存储上一段文本
        self.model = None
        self.asr = None
        self.buffer_text = ""  # 用于存储待发送的文本
        self.target_language = "zh"  # 默认目标语言为中文
        self.enable_translation = False  # 默认不启用翻译
        self.translation_manager = None
        self._stop_event = threading.Event()  # 添加停止事件
        self.has_content = False  # 添加标志，用于跟踪是否有实际内容

    def set_target_language(self, language):
        """设置目标语言"""
        self.target_language = language
        if self.enable_translation:
            self.translation_manager = TranslationManager()

    def set_enable_translation(self, enable):
        """设置是否启用翻译"""
        self.enable_translation = enable
        if enable:
            self.translation_manager = TranslationManager()
        else:
            self.translation_manager = None

    def process_audio_buffer(self, buffer_obj):
        """处理音频缓冲区数据"""
        try:
            # 检查序号是否连续
            if buffer_obj.sequence != self.last_sequence + 1:
                self.error_signal.emit(f"音频数据序号不连续: 期望 {self.last_sequence + 1}, 实际 {buffer_obj.sequence}")
                return

            # 使用 Paraformer 模型进行转录（offline: VAD 过滤静音 + 标点恢复）
            res = self.asr.model.generate(
                input=buffer_obj.data,
                **self.asr._gen_kwargs
            )

            if res and len(res) > 0:
                text = str(res[0].get("text", ""))
                # 兜底清理 <|...|> 标签（SenseVoice 风格，Paraformer 一般没有）
                text = re.sub(r"<\|[^|]+\|>", "", text).strip()
                if text:
                    # 去除表情符号
                    text = re.sub(r'[\U0001F000-\U0001F9FF]', '', text)
                    # 去除多余的换行符
                    text = re.sub(r'\n+', '\n', text).strip()

                    # 检查是否需要分割句子（上一段是未完成的续句）
                    if self.last_text and not text.startswith(('，', '。', '！', '？', '；', '：', '、')):
                        text = self.last_text + text
                        self.last_text = ""

                    # 发送到界面
                    self.text_signal.emit(text)

                    # 如果启用了翻译，发送翻译请求
                    if self.enable_translation and self.translation_manager:
                        def translation_callback(translated_text):
                            try:
                                # 检查翻译结果是否为空
                                if not translated_text or not translated_text.strip():
                                    logging.warning("翻译结果为空，跳过显示")
                                    return

                                # 去除多余的换行符
                                translated_text = re.sub(r'\n+', '\n', translated_text).strip()
                                # 发送翻译信号
                                self.translation_signal.emit(translated_text)
                            except Exception as e:
                                self.error_signal.emit(f"处理翻译结果失败: {e}")

                        self.translation_manager.translate(
                            text,
                            self.target_language,
                            translation_callback,
                            lambda x: self.error_signal.emit(f"翻译错误: {x}")
                        )

                    # 标记有实际内容
                    self.has_content = True
                    self.has_content_signal.emit(True)

                    # 保存到文件
                    with open(self.output_file, 'a', encoding='utf-8') as f:
                        f.write(text + "\n")

                    self.subtitle_index += 1
                else:
                    # 如果当前文本为空，保存上一段文本
                    self.last_text = text

            # 更新最后处理的序号
            self.last_sequence = buffer_obj.sequence

        except Exception as e:
            self.error_signal.emit(f"处理音频数据失败: {e}")

    def run(self):
        try:
            self.running = True
            self._stop_event.clear()  # 清除停止事件
            self.status_signal.emit("正在初始化转录模型...")

            # 初始化 Paraformer 模型（复用项目统一 ASR 后端：offline + VAD + 标点）
            model_root = os.path.join(_PROJECT_ROOT, "model")
            self.asr = FunASRBackend(
                model_name="offline",
                model_root=model_root,
                disable_update=True,
            )

            self.status_signal.emit("转录模型初始化完成")

            # 创建输出文件
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

            while self.running and not self._stop_event.is_set():
                try:
                    # 从队列获取音频数据
                    if not self.audio_queue.empty():
                        buffer_obj = self.audio_queue.get()
                        self.process_audio_buffer(buffer_obj)
                    else:
                        time.sleep(0.1)  # 避免CPU占用过高

                except Exception as e:
                    self.error_signal.emit(f"转录错误: {e}")
                    time.sleep(0.1)

        except Exception as e:
            self.error_signal.emit(f"转录线程异常: {e}")
        finally:
            self.running = False
            self._stop_event.set()  # 确保停止事件被设置
            self.status_signal.emit("转录已停止")

            # 如果没有实际内容，删除空文件
            if not self.has_content:
                try:
                    if os.path.exists(self.output_file):
                        os.remove(self.output_file)
                    if os.path.exists(self.translation_file):
                        os.remove(self.translation_file)
                except Exception as e:
                    self.error_signal.emit(f"删除空文件失败: {e}")

    def on_buffer_ready(self, buffer_obj):
        """处理缓冲区就绪信号"""
        self.audio_queue.put(buffer_obj)

    def stop(self):
        """停止转录线程"""
        try:
            self.running = False
            self._stop_event.set()  # 设置停止事件
            self.status_signal.emit("正在停止转录...")

            # 清空队列
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except:
                    pass

            # 等待线程结束
            self.wait(1000)  # 等待最多1秒

            # 检查是否有内容可以生成总结
            if self.has_content and os.path.exists(self.output_file):
                self.has_content_signal.emit(True)
            else:
                self.has_content_signal.emit(False)


        except Exception as e:
            error_msg = f"停止转录线程时出错: {str(e)}"
            logging.error(error_msg)
            self.error_signal.emit(error_msg)


class TranslationThread(QThread):
    """翻译线程"""

    def __init__(self, text_queue, target_language, callback, error_callback):
        super().__init__()
        self.text_queue = text_queue
        self.target_language = target_language
        self.callback = callback
        self.error_callback = error_callback
        self.running = True

    def run(self):
        while self.running:
            try:
                # 从队列获取文本
                if not self.text_queue.empty():
                    text = self.text_queue.get()
                    # 创建翻译工作线程
                    translation_worker = TranslationWorker(
                        text,
                        "auto",
                        self.target_language,
                        self.callback,
                        self.error_callback
                    )
                    translation_worker.start()
                    translation_worker.join()  # 等待翻译完成
                else:
                    time.sleep(0.1)  # 避免CPU占用过高
            except Exception as e:
                self.error_callback(f"翻译错误: {str(e)}")

    def stop(self):
        self.running = False


class SummaryThread(QThread):
    """总结线程"""
    status_signal = Signal(str)
    error_signal = Signal(str)
    finished_signal = Signal(str)  # 用于通知总结完成

    def __init__(self, content, target_lang, output_file):
        super().__init__()
        self.content = content
        self.target_lang = target_lang
        self.output_file = output_file

    def run(self):
        try:
            self.status_signal.emit("正在生成总结...")
            # 调用千问模型生成总结
            try:
                response = requests.post(
                    "http://localhost:1234/v1/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "qwen3-0.6b",
                        "messages": [
                            {
                                "role": "system",
                                "content": f"你是一个专业的文本总结助手。请仔细分析以下文本，思考其核心内容和关键信息，然后生成一个全面而准确的总结。请用{self.target_lang}总结以下文本的主要内容，使用简洁的语言，分行列出要点或概述内容大意。只返回总结结果，不要包含原文，不要添加任何额外的说明或标记。"
                            },
                            {
                                "role": "user",
                                "content": self.content
                            }
                        ],
                        "temperature": 0.3,
                        "max_tokens": -1,
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    summary = result["choices"][0]["message"]["content"].strip()
                    # 移除<think>标签及其内容
                    summary = re.sub(r'<think>.*?</think>', '', summary, flags=re.DOTALL)
                    # 移除其他<>包围的标签
                    summary = re.sub(r'<[^>]+>', '', summary)
                    # 去除多余的换行符
                    summary = re.sub(r'\n+', '\n', summary).strip()
                else:
                    raise Exception("调用模型失败")

            except Exception as e:
                error_msg = f"调用模型生成总结失败：{str(e)}"
                logging.error(error_msg)
                self.error_signal.emit(error_msg)
                return

            # 生成总结文件内容
            summary_content = f"=== 转录内容总结 ===\n\n"
            summary_content += f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            summary_content += f"总字数：{len(self.content)}\n"
            summary_content += f"总行数：{len(self.content.splitlines())}\n\n"
            summary_content += "=== 内容总结 ===\n\n"
            summary_content += summary + "\n\n"
            summary_content += "=== 总结结束 ==="

            # 保存总结文件
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(summary_content)
            self.status_signal.emit(f"总结已生成并保存到：{self.output_file}")
            self.finished_signal.emit(self.output_file)

        except Exception as e:
            error_msg = f"生成总结时出错：{str(e)}"
            logging.error(error_msg)
            self.error_signal.emit(error_msg)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时字幕生成器")
        self.setMinimumSize(300, 150)  # 减小窗口大小

        # 设置窗口图标
        window_icon = QIcon("AI视频转文字.ico")
        self.setWindowIcon(window_icon)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)  # 设置边距
        layout.setSpacing(10)  # 设置间距

        # 创建控制面板
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)

        # 采样率选择
        self.sample_rate_label = QLabel("采样率:")
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["8000", "16000", "44100", "48000"])
        self.sample_rate_combo.setCurrentText("16000")
        self.sample_rate_combo.setFixedWidth(80)  # 固定宽度

        # 添加语言选择
        self.language_label = QLabel("目标语言:")
        self.language_combo = QComboBox()
        self.language_combo.addItems(["中文", "英文", "日文", "韩文", "法文", "西班牙文"])
        self.language_combo.setCurrentText("中文")
        self.language_combo.setFixedWidth(100)
        self.language_combo.currentTextChanged.connect(self.on_language_changed)

        # 识别模型：固定使用 Paraformer-Offline（+ VAD + 标点），准确优先

        # 字幕显示模式（统一窗口：仅原文 / 仅翻译 / 原文+翻译）
        self.mode_label = QLabel("字幕显示:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["仅原文", "仅翻译", "原文+翻译"])
        saved_mode = SettingsManager().get_display_mode()
        self.mode_combo.setCurrentIndex({"original": 0, "translation": 1, "both": 2}.get(saved_mode, 0))
        self.mode_combo.setFixedWidth(110)
        self.mode_combo.currentIndexChanged.connect(self.on_display_mode_changed)

        # 开始/停止按钮
        self.start_button = QPushButton("开始")
        self.start_button.setFixedWidth(80)  # 固定宽度
        self.start_button.clicked.connect(self.start_capture)
        self.stop_button = QPushButton("停止")
        self.stop_button.setFixedWidth(80)  # 固定宽度
        self.stop_button.clicked.connect(self.stop_capture)
        self.stop_button.setEnabled(False)

        # 添加生成总结按钮
        self.summary_button = QPushButton("生成总结")
        self.summary_button.setFixedWidth(80)  # 固定宽度
        self.summary_button.clicked.connect(self.generate_summary)
        self.summary_button.setEnabled(False)  # 初始状态禁用

        # 添加控件到控制面板
        control_layout.addWidget(self.sample_rate_label)
        control_layout.addWidget(self.sample_rate_combo)
        control_layout.addWidget(self.language_label)
        control_layout.addWidget(self.language_combo)
        control_layout.addWidget(self.mode_label)
        control_layout.addWidget(self.mode_combo)
        control_layout.addStretch()  # 添加弹性空间
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.summary_button)

        # 创建状态显示区域
        status_layout = QVBoxLayout()
        status_layout.setSpacing(5)

        # 状态标签
        status_label = QLabel("状态:")
        status_label.setStyleSheet("font-weight: bold;")

        # 状态文本框
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMinimumHeight(60)  # 设置最小高度
        self.status_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # 设置大小策略
        self.status_text.setStyleSheet("""
            QTextEdit {
                border-radius: 4px;
                padding: 5px;
            }
        """)

        # 添加状态组件到状态布局
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.status_text)

        # 添加所有部件到主布局
        layout.addLayout(control_layout)
        layout.addLayout(status_layout)

        # 设置布局的拉伸因子
        layout.setStretch(0, 0)  # 控制面板不拉伸
        layout.setStretch(1, 1)  # 状态区域可以拉伸

        # 初始化线程
        self.audio_thread = None
        self.transcription_thread = None
        self.is_stopping = False

        # 初始化字幕窗口（统一窗口，显示模式由下拉决定）
        self.subtitle_window = None
        self._create_subtitle_windows()

        # 添加变量跟踪是否有可用的转录内容
        self.has_available_content = False

    def _create_subtitle_windows(self):
        """创建字幕窗口（统一窗口，不再单独创建翻译窗口）"""
        # 如果窗口已存在，先关闭它
        if self.subtitle_window:
            self.subtitle_window.close()

        # 创建新的字幕窗口（模式从下拉同步）
        self.subtitle_window = SubtitleWindow()
        self.subtitle_window.set_mode(["original", "translation", "both"][self.mode_combo.currentIndex()])
        self.subtitle_window.show()

    def on_language_changed(self, language):
        """处理语言选择改变（运行中可随时切换，后续翻译立即用新语言）"""
        if self.transcription_thread:
            self.transcription_thread.set_target_language(language)

    def on_display_mode_changed(self, index):
        """处理字幕显示模式改变：仅原文(不翻译) / 仅翻译 / 原文+翻译"""
        mode = ["original", "translation", "both"][index]
        if self.subtitle_window:
            self.subtitle_window.set_mode(mode)
        # 翻译开关跟随模式：仅原文不需要翻译
        need_translation = mode != "original"
        if self.transcription_thread:
            self.transcription_thread.set_enable_translation(need_translation)

    def start_capture(self):
        """开始捕获音频"""
        try:
            # 重置停止状态
            self.is_stopping = False
            self.has_available_content = False  # 重置内容状态
            self.summary_button.setEnabled(False)  # 初始禁用总结按钮

            # 确保字幕窗口存在
            if not self.subtitle_window or not self.subtitle_window.isVisible():
                self._create_subtitle_windows()

            # 创建并启动音频捕获线程
            self.audio_thread = AudioCaptureThread(
                sample_rate=int(self.sample_rate_combo.currentText())
            )
            self.audio_thread.status_signal.connect(self.update_status)
            self.audio_thread.error_signal.connect(self.show_error)
            self.audio_thread.start()

            # 创建并启动转录线程（Paraformer-Offline + VAD + 标点）
            need_translation = self.mode_combo.currentIndex() != 0  # 仅原文不翻译
            self.transcription_thread = TranscriptionThread()
            self.transcription_thread.set_target_language(self.get_language_code())
            self.transcription_thread.set_enable_translation(need_translation)
            self.transcription_thread.text_signal.connect(self.update_subtitle)
            self.transcription_thread.translation_signal.connect(self.update_translation)
            self.transcription_thread.status_signal.connect(self.update_status)
            self.transcription_thread.error_signal.connect(self.show_error)
            self.transcription_thread.has_content_signal.connect(self.on_content_available)

            # 连接音频缓冲区信号
            self.audio_thread.buffer_ready.connect(self.transcription_thread.on_buffer_ready)

            self.transcription_thread.start()

            # 更新按钮状态（语言/字幕模式保持可切换，采样率需停止后改）
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.summary_button.setEnabled(True)  # 启用生成总结按钮
            self.sample_rate_combo.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动失败: {str(e)}")
            # 发生错误时重置按钮状态
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.summary_button.setEnabled(False)
            self.sample_rate_combo.setEnabled(True)

    def get_language_code(self):
        """获取语言代码"""
        selected_lang = self.language_combo.currentText()
        logging.info(f"选择的目标语言: {selected_lang}")
        return selected_lang

    def stop_capture(self):
        """停止捕获音频"""
        if self.is_stopping:
            return

        self.is_stopping = True
        self.stop_button.setEnabled(False)

        try:
            if self.audio_thread:
                self.audio_thread.stop()
                self.audio_thread.wait(1000)

            if self.transcription_thread:
                self.transcription_thread.stop()
                self.transcription_thread.wait(1000)

            # 重置按钮状态
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.sample_rate_combo.setEnabled(True)

            # 检查是否可以生成总结
            if self.transcription_thread and self.transcription_thread.has_content:
                self.summary_button.setEnabled(True)
                logging.info("可以生成总结")
            else:
                self.summary_button.setEnabled(False)
                logging.info("没有可用的转录内容，无法生成总结")

        except Exception as e:
            self.show_error(f"停止捕获时出错: {str(e)}")
        finally:
            self.is_stopping = False

    def update_subtitle(self, text):
        """更新原文字幕显示（统一窗口）"""
        if self.subtitle_window:
            self.subtitle_window.update_original(text)

    def update_translation(self, text):
        """更新翻译字幕显示（统一窗口，异步到达后刷新）"""
        if self.subtitle_window:
            self.subtitle_window.update_translation(text)

    def update_status(self, text):
        """更新状态显示"""
        self.status_text.append(text)

    def show_error(self, text):
        """显示错误信息"""
        QMessageBox.warning(self, "错误", text)

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.stop_capture()
        self.subtitle_window.close()  # 关闭字幕窗口
        event.accept()

    def resizeEvent(self, event):
        """处理窗口大小改变事件"""
        super().resizeEvent(event)
        # 更新状态文本框的大小
        self.status_text.setMinimumHeight(max(60, self.height() // 4))  # 至少60像素高，或窗口高度的1/4

    def on_content_available(self, has_content):
        """处理转录内容可用状态变化"""
        self.has_available_content = has_content
        self.summary_button.setEnabled(has_content)

    def generate_summary(self):
        """生成总结"""
        try:
            # 获取当前转录的文本
            if not self.transcription_thread or not self.transcription_thread.has_content:
                QMessageBox.warning(self, "警告", "没有可用的转录内容来生成总结")
                return

            # 创建总结目录（固定存到实时识别目录下）
            summary_dir = os.path.join(_THIS_DIR, "总结")
            os.makedirs(summary_dir, exist_ok=True)

            # 使用时间戳创建文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_file = os.path.join(summary_dir, f"summary_{timestamp}.txt")

            # 读取转录文件内容
            with open(self.transcription_thread.output_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 获取当前选择的目标语言名称
            target_lang = self.language_combo.currentText()

            # 创建并启动总结线程
            self.summary_thread = SummaryThread(content, target_lang, summary_file)
            self.summary_thread.status_signal.connect(self.update_status)
            self.summary_thread.error_signal.connect(self.show_error)
            self.summary_thread.finished_signal.connect(self.on_summary_finished)
            self.summary_thread.start()

            # 禁用总结按钮，防止重复点击
            self.summary_button.setEnabled(False)
            logging.info("总结线程已启动")

        except Exception as e:
            error_msg = f"启动总结线程时出错：{str(e)}"
            logging.error(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
            self.show_error(error_msg)

    def on_summary_finished(self, summary_file):
        """总结完成后的处理"""
        self.has_available_content = False
        self.summary_button.setEnabled(False)
        QMessageBox.information(self, "成功", f"总结已生成并保存到：{summary_file}")
        logging.info("总结生成完成")


def main():
    # 创建 QApplication 实例
    app = QApplication(sys.argv)

    # 设置应用程序图标
    app_icon = QIcon("AI视频转文字.ico")
    app.setWindowIcon(app_icon)

    # 设置应用属性以优化兼容性
    try:
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception as e:
        logging.warning(f"设置应用属性时出错: {e}")

    window = MainWindow()
    window.show()

    # 进入应用事件循环
    result = app.exec()

    sys.exit(result)


if __name__ == "__main__":
    main()