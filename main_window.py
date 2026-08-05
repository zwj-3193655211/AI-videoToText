import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QLineEdit, QPushButton,QWidget,
                               QTextEdit, QMessageBox, QComboBox, QTabWidget, QFileDialog, QCheckBox, QVBoxLayout, QSizePolicy)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QTimer, Qt, Signal, QObject, QMetaObject, Slot, QThread
import re
import GetBiliBiliVideo
from datetime import datetime
import transcription
import translator
import llm_backend
import settings_dialog
import subprocess
import uuid
import queue
from PySide6.QtGui import QIcon


class LogSignals(QObject):
    """用于发送日志信号的类"""
    log_signal = Signal(str, str, int)  # msg, level, tab


class ModelLoaderThread(QThread):
    """模型加载线程"""
    finished = Signal(object)  # 发送加载完成的模型
    error = Signal(str)  # 发送错误信息

    def run(self):
        try:
            model = transcription.LocalASR()
            self.finished.emit(model)
        except Exception as e:
            self.error.emit(str(e))


class LLMBackendInitThread(QThread):
    """LLM backend 初始化线程（避免 Ollama 启动阻塞 UI）"""
    finished = Signal(object)  # backend 实例
    error = Signal(str)

    def run(self):
        try:
            backend = llm_backend.get_backend()
            self.finished.emit(backend)
        except Exception as e:
            self.error.emit(str(e))


class LogWriterThread(QThread):
    """日志写入线程"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        self.running = True

    def run(self):
        while self.running:
            try:
                msg, level, tab = self.log_queue.get(timeout=1)
                self.log_queue.task_done()
                # 发送日志信号
                QApplication.instance().processEvents()
            except queue.Empty:
                continue

    def stop(self):
        self.running = False


class AudioProcessThread(QThread):
    """音频处理线程"""
    finished = Signal(str)  # 发送处理完成的文件路径
    error = Signal(str)     # 发送错误信息
    progress = Signal(str, str)  # 发送进度信息 (消息, 级别)

    def __init__(self, asr, audio_path, title, target_lang, need_summary, llm_backend=None):
        super().__init__()
        self.asr = asr
        self.audio_path = audio_path
        self.title = title
        self.target_lang = target_lang
        self.need_summary = need_summary
        self.llm_backend = llm_backend  # 可选；不传则 translator 内部默认

    def run(self):
        try:
            # 转录音频
            self.progress.emit("正在转录音频...", "info")
            transcript_path = self.asr.process_audio(self.audio_path, self.title)

            if not transcript_path:
                raise Exception("音频转录失败")

            self.progress.emit("音频转录完成！", "success")
            self.progress.emit(f"转录文件已保存至：{transcript_path}", "info")

            # 只有在需要时才进行翻译和总结
            if self.need_summary:
                self.progress.emit("正在翻译和总结...", "info")

                # 把 llm_backend 显式传给 translator（避免每次重新 get_backend 触发 Ollama 自动启动检查）
                translated_text, summary = translator.translate_and_summarize(
                    transcript_path,
                    self.target_lang,
                    backend=self.llm_backend,
                    progress_callback=lambda msg: self.progress.emit(msg, "info"),
                    log_callback=lambda msg, level: self.progress.emit(msg, level),
                )
                
                if translated_text:
                    # 保存翻译结果
                    output_dir = os.path.join(os.getcwd(), "output")
                    os.makedirs(output_dir, exist_ok=True)
                    
                    # 使用标题作为文件名
                    output_file = os.path.join(output_dir, f"{self.title}_translation.txt")
                    
                    # 检查文件是否已存在，如果存在则添加序号
                    counter = 1
                    base_name = output_file
                    while os.path.exists(output_file):
                        output_file = f"{os.path.splitext(base_name)[0]}_{counter}.txt"
                        counter += 1
                    
                    # 写入翻译结果，添加适当的换行
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write("=== 翻译结果 ===\n\n")
                        # 按段落分割并添加换行
                        paragraphs = translated_text.split('\n\n')
                        for para in paragraphs:
                            if para.strip():
                                f.write(para.strip() + "\n\n")
                        
                        if summary:
                            f.write("\n=== 总结 ===\n\n")
                            # 直接写入总结内容，不进行额外的分割处理
                            f.write(summary.strip() + "\n")
                    
                    self.progress.emit("翻译和总结完成！", "success")
                    self.progress.emit(f"结果已保存至：{output_file}", "info")
                else:
                    self.progress.emit("翻译失败", "error")

            self.finished.emit(transcript_path)

        except Exception as e:
            self.error.emit(str(e))




class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 加载UI文件
        ui_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.ui")
        try:
            if not os.path.isfile(ui_file):
                raise FileNotFoundError(f"UI文件不存在：{ui_file}")
            loader = QUiLoader()
            self.ui = loader.load(ui_file, self)
            self.ui.setWindowTitle("AI音视频转文本处理工具")
            
            # 设置窗口最小尺寸
            self.ui.setMinimumSize(400, 400)
            
            # 创建固定窗口按钮
            self.pin_button = QPushButton("📌", self.ui)
            self.pin_button.setFixedSize(30, 30)
            self.pin_button.setStyleSheet("""
                QPushButton {
                    border: none;
                    background-color: transparent;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border-radius: 15px;
                }
            """)
            self.pin_button.clicked.connect(self.toggle_window_pin)
            self.is_pinned = False

            # 创建设置按钮（左下角，与 pin 按钮对角）
            self.settings_button = QPushButton("⚙", self.ui)
            self.settings_button.setFixedSize(30, 30)
            self.settings_button.setStyleSheet("""
                QPushButton {
                    border: none;
                    background-color: transparent;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border-radius: 15px;
                }
            """)
            self.settings_button.setToolTip("设置（LLM 服务 / ASR 模型）")
            self.settings_button.clicked.connect(self.open_settings)
            self.llm_backend = None  # 启动后异步初始化
            
            # 创建日志队列和线程
            self.log_queue = queue.Queue()
            self.log_writer = LogWriterThread(self.log_queue)
            self.log_writer.start()

            # 创建日志信号对象
            self.log_signals = LogSignals()
            self.log_signals.log_signal.connect(self._update_log)

            # 创建必要的输出目录
            self.output_dirs = {
                'audio': os.path.join(os.getcwd(), "音频"),
                'transcript': os.path.join(os.getcwd(), "原文"),
                'output': os.path.join(os.getcwd(), "output")
            }
            for dir_path in self.output_dirs.values():
                os.makedirs(dir_path, exist_ok=True)

            # 初始化Tab1控件（B站链接处理）
            self._init_tab1_controls()
            # 初始化Tab2控件（本地文件处理）
            self._init_tab2_controls()
            
            # 初始化语言选择框（Tab1、Tab2）
            self.init_language_combo(self.lang_combo1, tab=1)
            self.init_language_combo(self.lang_combo2, tab=2)

            # 绑定事件
            self.submit_button1.clicked.connect(self.process_bilibili)
            self.select_btn.clicked.connect(self.select_local_file)
            self.submit_button2.clicked.connect(self.process_local)

            # 启动模型加载线程
            self.model_loader = ModelLoaderThread()
            self.model_loader.finished.connect(self._on_model_loaded)
            self.model_loader.error.connect(self._on_model_error)
            self.model_loader.start()

            # 初始化 LLM backend（后台线程，避免 Ollama 启动阻塞 UI）
            self.llm_loader = LLMBackendInitThread()
            self.llm_loader.finished.connect(self._on_llm_loaded)
            self.llm_loader.error.connect(self._on_llm_error)
            self.llm_loader.start()

            self.log("正在加载语音识别模型，请稍候...", "info", 1)
            self.log("正在加载语音识别模型，请稍候...", "info", 2)

            self.ui.show()
        except FileNotFoundError as e:
            QMessageBox.critical(self, "错误", str(e))
            sys.exit(1)
        except RuntimeError as e:
            QMessageBox.critical(self, "错误", str(e))
            sys.exit(1)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"初始化失败: {str(e)}")
            sys.exit(1)

    def _init_tab1_controls(self):
        """初始化Tab1控件"""
        self.url_input = self.findChild(QLineEdit, "lineEdit_url")
        self.submit_button1 = self.findChild(QPushButton, "pushButton_submit")
        self.log_text_edit1 = self.findChild(QTextEdit, "textEdit_log")
        self.lang_combo1 = self.findChild(QComboBox, "comboBox_target_language")
        self.checkBox_summary = self.findChild(QCheckBox, "checkBox_2")

    def _init_tab2_controls(self):
        """初始化Tab2控件"""
        self.select_btn = self.findChild(QPushButton, "select")
        self.submit_button2 = self.findChild(QPushButton, "submit2")
        self.log_text_edit2 = self.findChild(QTextEdit, "textEdit_log_2")
        self.lang_combo2 = self.findChild(QComboBox, "comboBox_target_language_2")
        self.checkBox_summary2 = self.findChild(QCheckBox, "checkBox")

    def init_language_combo(self, combo_box, tab=1):
        """初始化语言选择下拉框"""
        if not combo_box:
            return
        languages = [
            "中文", "英文", "日文", "韩文", "法文", "西班牙文"
        ]
        combo_box.clear()
        for lang in languages:
            combo_box.addItem(lang)
        combo_box.setCurrentIndex(0)  # 默认中文
        self.log(f"Tab{tab} 默认语言: 中文", "info", tab)

    def get_lang_code(self, tab=1):
        """获取指定Tab的语言代码"""
        combo = self.lang_combo1 if tab == 1 else self.lang_combo2 if tab == 2  else None
        return combo.currentText() if combo else "中文"

    def log(self, msg, level="info", tab=1):
        """记录日志到指定Tab"""
        # 使用信号发送日志消息
        self.log_signals.log_signal.emit(msg, level, tab)

    @Slot(str, str, int)
    def _update_log(self, msg, level, tab):
        """更新日志显示（在主线程中执行）"""
        log_edit = self.log_text_edit1 if tab == 1 else self.log_text_edit2 if tab == 2  else None
        if log_edit:
            timestamp = datetime.now().strftime("%H:%M:%S")
            prefix = f"[{level.upper()}] {timestamp}"
            log_edit.append(f"{prefix} {msg}")
            # 滚动到底部
            log_edit.verticalScrollBar().setValue(log_edit.verticalScrollBar().maximum())
            # 立即更新UI
            QApplication.processEvents()

    def select_local_file(self):
        """选择本地媒体文件（Tab2）"""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self,
            '选择媒体文件',
            '',
            '媒体文件 (*.mp4 *.avi *.mov *.mp3 *.m4a)'
        )
        if file_path:
            try:
                # 获取文件名和扩展名
                file_name, file_ext = os.path.splitext(os.path.basename(file_path))
                file_ext = file_ext.lower()

                # 检查文件类型并显示转换信息
                if file_ext in ['.mp4', '.avi', '.mov']:
                    file_type = "视频"
                elif file_ext in ['.mp3', '.m4a']:
                    file_type = "音频"
                else:
                    raise ValueError("不支持的文件格式")

                self.log(f"已选择{file_type}文件: {file_name}{file_ext}", "info", tab=2)

                # 保存文件路径供后续处理使用
                self.current_file_path = file_path

            except Exception as e:
                self.log(f"\n❌ 选择文件时发生错误：{str(e)}", "error", tab=2)
                self.current_file_path = None

    def _set_buttons_state(self, tab, enabled=True):
        """设置指定标签页的按钮状态"""
        if tab == 1:
            self.submit_button1.setEnabled(enabled)
            self.url_input.setEnabled(enabled)
            self.lang_combo1.setEnabled(enabled)
        elif tab == 2:
            self.submit_button2.setEnabled(enabled)
            self.select_btn.setEnabled(enabled)
            self.lang_combo2.setEnabled(enabled)
    

    def process_bilibili(self):
        """处理B站视频链接（Tab1）"""
        url = self.url_input.text().strip()
        if not url:
            self.log("请输入B站视频链接", "error", tab=1)
            return

        try:
            # 禁用按钮
            self._set_buttons_state(1, False)
            self.log("开始处理B站视频...", "info", tab=1)

            # 获取音频文件
            mp3_filename, title = GetBiliBiliVideo.getvideo(
                url,
                self.output_dirs['audio'],
                lambda msg, level: self.log(msg, level, tab=1)
            )

            if not mp3_filename:
                raise Exception("获取音频文件失败")

            # 处理音频文件
            self._process_audio_file(
                os.path.join(self.output_dirs['audio'], mp3_filename),
                title,
                self.get_lang_code(1),
                self.checkBox_summary.isChecked(),
                tab=1
            )

        except Exception as e:
            self.log(f"处理失败：{str(e)}", "error", tab=1)
        finally:
            # 恢复按钮状态
            self._set_buttons_state(1, True)

    def process_local(self):
        """处理本地文件（Tab2）"""
        if not hasattr(self, 'current_file_path') or not self.current_file_path:
            self.log("请先选择文件", "error", tab=2)
            return

        try:
            # 禁用按钮
            self._set_buttons_state(2, False)
            self.log("开始处理本地文件...", "info", tab=2)

            # 获取文件信息
            file_name, file_ext = os.path.splitext(os.path.basename(self.current_file_path))
            file_ext = file_ext.lower()

            # 如果是视频文件，先转换为音频
            if file_ext in ['.mp4', '.avi', '.mov']:
                self.log("正在将视频转换为音频...", "info", tab=2)
                mp3_path = self._convert_video_to_audio(self.current_file_path)
                if not mp3_path:
                    raise Exception("视频转音频失败")
            else:
                mp3_path = self.current_file_path

            # 处理音频文件
            self._process_audio_file(
                mp3_path,
                file_name,
                self.get_lang_code(2),
                self.checkBox_summary2.isChecked(),
                tab=2
            )

        except Exception as e:
            self.log(f"处理失败：{str(e)}", "error", tab=2)
        finally:
            # 恢复按钮状态
            self._set_buttons_state(2, True)

    def _convert_video_to_audio(self, video_path):
        """将视频文件转换为音频文件"""
        try:
            # 生成唯一的输出文件名
            output_filename = f"{uuid.uuid4().hex}.m4a"
            output_path = os.path.join(self.output_dirs['audio'], output_filename)

            # 使用ffmpeg转换
            command = [
                'ffmpeg',
                '-i', video_path,
                '-vn',  # 不处理视频
                '-acodec', 'aac',  # 使用AAC编码
                '-b:a', '192k',  # 比特率192k
                output_path
            ]

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                raise Exception(f"转换失败：{stderr.decode()}")

            return output_path

        except Exception as e:
            self.log(f"视频转音频失败：{str(e)}", "error")
            return None

    def _process_audio_file(self, audio_path, title, target_lang, need_summary, tab):
        """处理音频文件：转录、翻译和总结"""
        try:
            if not hasattr(self, 'asr'):
                self.log("语音识别模型尚未加载完成，请稍候...", "error", tab)
                return

            # 创建并启动处理线程
            self.process_thread = AudioProcessThread(
                self.asr,
                audio_path,
                title,
                target_lang,
                need_summary,
                llm_backend=self.llm_backend,
            )
            
            # 连接信号
            self.process_thread.progress.connect(lambda msg, level: self.log(msg, level, tab))
            self.process_thread.error.connect(lambda msg: self.log(msg, "error", tab))
            self.process_thread.finished.connect(lambda _: self._set_buttons_state(tab, True))
            
            # 禁用按钮
            self._set_buttons_state(tab, False)
            
            # 启动线程
            self.process_thread.start()

        except Exception as e:
            self.log(f"处理失败：{str(e)}", "error", tab)
            self._set_buttons_state(tab, True)

    def _on_model_loaded(self, model):
        """模型加载完成的回调"""
        self.asr = model
        self.log("语音识别模型加载完成！", "success", 1)
        self.log("语音识别模型加载完成！", "success", 2)


    def _on_model_error(self, error_msg):
        """模型加载错误的回调"""
        self.log(f"模型加载失败：{error_msg}", "error", 1)
        self.log(f"模型加载失败：{error_msg}", "error", 2)
        QMessageBox.critical(self, "错误", f"模型加载失败：{error_msg}")

    # ====== LLM backend + 设置 ======

    def _on_llm_loaded(self, backend):
        self.llm_backend = backend
        self.log(f"LLM backend 就绪: {backend}", "info", 1)

    def _on_llm_error(self, error_msg):
        self.llm_backend = None
        self.log(f"LLM backend 初始化失败：{error_msg}", "error", 1)
        self.log("翻译/总结功能将不可用，修复后点击 ⚙ 重新设置", "warning", 1)

    def _reload_llm_backend_async(self):
        """设置保存后异步重建 backend"""
        self.llm_backend = None
        self.llm_loader = LLMBackendInitThread()
        self.llm_loader.finished.connect(self._on_llm_loaded)
        self.llm_loader.error.connect(self._on_llm_error)
        self.llm_loader.start()

    def open_settings(self):
        """弹出设置对话框；保存后立即重建 LLM backend（ASR 改动需重启）"""
        try:
            result = settings_dialog.open_settings(self)
            if result:  # 用户点了保存
                self._reload_llm_backend_async()
                self.log("设置已保存。LLM 立即生效，ASR 模型改动需重启。", "info", 1)
        except Exception as e:
            QMessageBox.critical(self, "打开设置失败", str(e))

    def closeEvent(self, event):
        """窗口关闭时的处理"""
        self.stop_realtime_transcription()
        self.log_writer.stop()
        self.log_writer.wait()
        super().closeEvent(event)

    def toggle_window_pin(self):
        """切换窗口固定状态"""
        self.is_pinned = not self.is_pinned
        if self.is_pinned:
            self.ui.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self.pin_button.setText("📍")
        else:
            self.ui.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.pin_button.setText("📌")
        self.ui.show()

    def resizeEvent(self, event):
        """处理窗口大小改变事件"""
        super().resizeEvent(event)
        # 更新固定按钮位置（右下）
        if hasattr(self, 'pin_button'):
            margin = 10
            self.pin_button.move(
                self.ui.width() - self.pin_button.width() - margin,
                self.ui.height() - self.pin_button.height() - margin
            )
        # 更新设置按钮位置（左下，与 pin 按钮对角）
        if hasattr(self, 'settings_button'):
            margin = 10
            self.settings_button.move(
                margin,
                self.ui.height() - self.settings_button.height() - margin
            )


def main():
    app = QApplication(sys.argv)
    # 设置应用程序图标
    app_icon = QIcon("AI视频转文字.ico")
    app.setWindowIcon(app_icon)
    window = MainWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
    