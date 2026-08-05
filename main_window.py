import sys
import os
import html
from PySide6.QtWidgets import (QApplication, QMainWindow, QLineEdit, QPushButton,QWidget,
                               QTextEdit, QMessageBox, QComboBox, QTabWidget, QFileDialog, QCheckBox, QVBoxLayout, QSizePolicy,
                               QLabel)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QTimer, Qt, Signal, QObject, QMetaObject, Slot, QThread, QEvent
import re
import GetBiliBiliVideo
from datetime import datetime
import transcription
import translator
import llm_backend
import settings_dialog
import ui_theme
import subprocess
import uuid
import queue
from PySide6.QtGui import QIcon


# 日志级别颜色映射
LOG_COLORS = {
    "error":   ("#dc2626", "✖"),
    "success": ("#16a34a", "✔"),
    "warning": ("#d97706", "⚠"),
    "info":    ("#6b7280", ""),
}


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


class ModelDownloadThread(QThread):
    """模型自动下载线程（复用 download.py 的下载逻辑）"""
    progress = Signal(str, str)  # msg, level
    finished_all = Signal(bool)  # 是否全部下载成功

    def run(self):
        try:
            # 延迟导入：modelscope import 较慢，避免拖慢应用启动
            import download
            from pathlib import Path
            ok = True
            for name, model_id, model_dir in download.MODELS:
                self.progress.emit(f"⏳ 正在下载 {name} ...", "info")
                try:
                    success = download.download_model(name, model_id, Path(model_dir))
                    ok = ok and success
                except Exception as e:
                    self.progress.emit(f"❌ {name} 下载失败：{e}", "error")
                    ok = False
            self.finished_all.emit(ok)
        except Exception as e:
            self.progress.emit(f"❌ 模型下载异常：{e}", "error")
            self.finished_all.emit(False)


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

    def __init__(self, asr, audio_path, title, target_lang, need_translation, need_summary, llm_backend=None):
        super().__init__()
        self.asr = asr
        self.audio_path = audio_path
        self.title = title
        self.target_lang = target_lang
        self.need_translation = need_translation
        self.need_summary = need_summary
        self.llm_backend = llm_backend  # 可选；不传则 translator 内部默认

    def _next_output_file(self, output_dir, title, suffix):
        """生成不重名的输出文件路径"""
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{title}_{suffix}.txt")
        counter = 1
        base_name = output_file
        while os.path.exists(output_file):
            output_file = f"{os.path.splitext(base_name)[0]}_{counter}.txt"
            counter += 1
        return output_file

    def run(self):
        try:
            # 转录音频
            self.progress.emit("正在转录音频...", "info")
            transcript_path = self.asr.process_audio(self.audio_path, self.title)

            if not transcript_path:
                raise Exception("音频转录失败")

            self.progress.emit("音频转录完成！", "success")
            self.progress.emit(f"转录文件已保存至：{transcript_path}", "info")

            output_dir = os.path.join(os.getcwd(), "output")

            # ===== 翻译（可选）=====
            translated_text = None
            summary = None
            if self.need_translation:
                self.progress.emit("正在翻译...", "info")
                # 把 llm_backend 显式传给 translator（避免每次重新 get_backend 触发 Ollama 自动启动检查）
                translated_text, summary = translator.translate_and_summarize(
                    transcript_path,
                    self.target_lang,
                    backend=self.llm_backend,
                    progress_callback=lambda msg: self.progress.emit(msg, "info"),
                    log_callback=lambda msg, level: self.progress.emit(msg, level),
                    with_summary=self.need_summary,
                )

                if translated_text:
                    # 保存翻译结果（勾选总结时，总结段一并写入翻译文件）
                    output_file = self._next_output_file(output_dir, self.title, "translation")
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write("=== 翻译结果 ===\n\n")
                        paragraphs = translated_text.split('\n\n')
                        for para in paragraphs:
                            if para.strip():
                                f.write(para.strip() + "\n\n")
                        if summary:
                            f.write("\n=== 总结 ===\n\n")
                            f.write(summary.strip() + "\n")
                    if summary:
                        self.progress.emit("翻译和总结完成！", "success")
                    else:
                        self.progress.emit("翻译完成！", "success")
                    self.progress.emit(f"结果已保存至：{output_file}", "info")
                else:
                    self.progress.emit("翻译失败", "error")

            # ===== 总结（可选，且未勾选翻译时基于原文）=====
            if self.need_summary and not translated_text:
                self.progress.emit("正在生成总结...", "info")
                try:
                    with open(transcript_path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                    summary = translator.generate_summary(
                        raw_text,
                        self.target_lang,
                        backend=self.llm_backend,
                        log_callback=lambda msg, level: self.progress.emit(msg, level),
                    )
                except Exception as e:
                    self.progress.emit(f"读取转录内容失败：{e}", "error")
                    summary = None

                if summary:
                    output_file = self._next_output_file(output_dir, self.title, "summary")
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write("=== 总结 ===\n\n")
                        f.write(summary.strip() + "\n")
                    self.progress.emit("总结完成！", "success")
                    self.progress.emit(f"总结已保存至：{output_file}", "info")
                else:
                    self.progress.emit("生成总结失败", "error")

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
            # 不带 parent 加载：self.ui 必须是独立顶层窗口，否则作为 owned window 不显示在任务栏
            self.ui = loader.load(ui_file)
            self.ui.setWindowTitle("AI音视频转文本处理工具")
            # 给实际显示的窗口设置图标（任务栏图标取自顶层窗口，而非 app）
            self.ui.setWindowIcon(QIcon(_app_icon_path()))
            
            # 设置窗口最小尺寸
            self.ui.setMinimumSize(400, 400)
            
            # 创建固定窗口按钮（右下角）
            self.pin_button = QPushButton("📌", self.ui)
            self.pin_button.setFixedSize(32, 32)
            self.pin_button.setCursor(Qt.PointingHandCursor)
            self.pin_button.setStyleSheet("""
                QPushButton {
                    border: 1px solid #d0d5dc;
                    border-radius: 16px;
                    background-color: #ffffff;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #eff6ff;
                    border-color: #3b82f6;
                }
                QPushButton:pressed {
                    background-color: #dbeafe;
                }
            """)
            self.pin_button.clicked.connect(self.toggle_window_pin)
            self.is_pinned = False

            # 创建设置按钮（左下角，与 pin 按钮对角）——做成明显的圆角按钮，方便用户发现
            self.settings_button = QPushButton("⚙  设置", self.ui)
            self.settings_button.setFixedSize(72, 32)
            self.settings_button.setCursor(Qt.PointingHandCursor)
            self.settings_button.setStyleSheet("""
                QPushButton {
                    border: 1px solid #d0d5dc;
                    border-radius: 16px;
                    background-color: #ffffff;
                    font-size: 13px;
                    color: #1f2329;
                    padding: 0 10px;
                }
                QPushButton:hover {
                    background-color: #eff6ff;
                    border-color: #3b82f6;
                    color: #1d4ed8;
                }
                QPushButton:pressed {
                    background-color: #dbeafe;
                }
            """)
            self.settings_button.setToolTip("设置（LLM 服务 / ASR 模型）")
            self.settings_button.clicked.connect(self.open_settings)
            self.llm_backend = None  # 启动后异步初始化

            # 应用全局主题（Fusion 风格 + QSS），幂等
            app = QApplication.instance()
            if app is not None:
                ui_theme.apply_theme(app)

            # 状态栏指示器（模型 / LLM 状态）
            self.status_model = QLabel("⏳ 模型加载中…")
            self.status_model.setStyleSheet("color: #d97706; padding: 0 6px;")
            self.status_llm = QLabel("⏳ LLM 初始化中…")
            self.status_llm.setStyleSheet("color: #d97706; padding: 0 6px;")
            status_bar = self.ui.statusBar()
            if status_bar is not None:
                status_bar.addPermanentWidget(self.status_model)
                status_bar.addPermanentWidget(self.status_llm)

            # Tab2 顶部插入“已选择文件”标签
            self.file_label = QLabel("尚未选择文件")
            self.file_label.setProperty("role", "badge-neutral")
            self.file_label.setMinimumHeight(30)
            tab2_layout = self.ui.findChild(QVBoxLayout, "verticalLayout_tab2")
            if tab2_layout is not None:
                tab2_layout.insertWidget(0, self.file_label)
            
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
            # 定位悬浮按钮（show 后布局尺寸才确定）
            self.ui.installEventFilter(self)
            self._position_floating_buttons()
            QTimer.singleShot(50, self._position_floating_buttons)
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
        self.url_input = self.ui.findChild(QLineEdit, "lineEdit_url")
        self.submit_button1 = self.ui.findChild(QPushButton, "pushButton_submit")
        self.log_text_edit1 = self.ui.findChild(QTextEdit, "textEdit_log")
        if self.log_text_edit1 is not None:
            self.log_text_edit1.setReadOnly(True)
        self.lang_combo1 = self.ui.findChild(QComboBox, "comboBox_target_language")
        self.checkBox_translate = self.ui.findChild(QCheckBox, "checkBox_translate")
        self.checkBox_summary = self.ui.findChild(QCheckBox, "checkBox_summary")

    def _init_tab2_controls(self):
        """初始化Tab2控件"""
        self.select_btn = self.ui.findChild(QPushButton, "select")
        self.submit_button2 = self.ui.findChild(QPushButton, "submit2")
        self.log_text_edit2 = self.ui.findChild(QTextEdit, "textEdit_log_2")
        if self.log_text_edit2 is not None:
            self.log_text_edit2.setReadOnly(True)
        self.lang_combo2 = self.ui.findChild(QComboBox, "comboBox_target_language_2")
        self.checkBox_translate2 = self.ui.findChild(QCheckBox, "checkBox_translate_2")
        self.checkBox_summary2 = self.ui.findChild(QCheckBox, "checkBox_summary_2")

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
        """更新日志显示（在主线程中执行，按级别着色）"""
        log_edit = self.log_text_edit1 if tab == 1 else self.log_text_edit2 if tab == 2  else None
        if log_edit:
            timestamp = datetime.now().strftime("%H:%M:%S")
            key = str(level).lower()
            color, icon = LOG_COLORS.get(key, LOG_COLORS["info"])
            safe_msg = html.escape(str(msg))
            icon_html = f"{icon} " if icon else ""
            tag_color = color if key != "info" else "#9ca3af"
            log_edit.append(
                f'<span style="color:{tag_color}; font-weight:600;">{icon_html}[{key.upper()}]</span> '
                f'<span style="color:#9ca3af;">{timestamp}</span> '
                f'<span style="color:#1f2329;">{safe_msg}</span>'
            )
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

                self.log(f"已选择{file_type}文件: {file_name}{file_ext}", "success", tab=2)

                # 保存文件路径供后续处理使用
                self.current_file_path = file_path
                # 顶部标签反馈
                self.file_label.setText(f"📎 {file_name}{file_ext}")
                self.file_label.setProperty("role", "badge-success")
                self.file_label.setToolTip(file_path)
                ui_theme.refresh_style(self.file_label)

            except Exception as e:
                self.log(f"\n❌ 选择文件时发生错误：{str(e)}", "error", tab=2)
                self.current_file_path = None
                self.file_label.setText("❌ 不支持的文件格式")
                self.file_label.setProperty("role", "badge-error")
                ui_theme.refresh_style(self.file_label)

    def _set_buttons_state(self, tab, enabled=True):
        """设置指定标签页的按钮状态（禁用时同步显示“处理中”文案，给出反馈）"""
        if tab == 1:
            self.submit_button1.setEnabled(enabled)
            self.submit_button1.setText("提交" if enabled else "⏳ 处理中…")
            self.url_input.setEnabled(enabled)
            self.lang_combo1.setEnabled(enabled)
        elif tab == 2:
            self.submit_button2.setEnabled(enabled)
            self.submit_button2.setText("提交" if enabled else "⏳ 处理中…")
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
                self.checkBox_translate.isChecked(),
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
                self.checkBox_translate2.isChecked(),
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

    def _process_audio_file(self, audio_path, title, target_lang, need_translation, need_summary, tab):
        """处理音频文件：转录 + 可选翻译 / 可选总结"""
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
                need_translation,
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
        self.status_model.setText("🟢 ASR 就绪")
        self.status_model.setStyleSheet("color: #16a34a; padding: 0 6px;")

    def _on_model_error(self, error_msg):
        """模型加载错误的回调；模型缺失时询问是否自动下载"""
        self.log(f"模型加载失败：{error_msg}", "error", 1)
        self.log(f"模型加载失败：{error_msg}", "error", 2)
        self.status_model.setText("🔴 ASR 加载失败")
        self.status_model.setStyleSheet("color: #dc2626; padding: 0 6px;")

        # 模型缺失类错误 → 询问自动下载（约 1.5GB，需联网）
        if "缺失" in str(error_msg) or "请运行 python download.py" in str(error_msg):
            box = QMessageBox(self)
            box.setWindowTitle("语音识别模型缺失")
            box.setText("检测到语音识别模型未安装，是否立即自动下载？")
            box.setInformativeText(
                "将下载 3 个基石模型（Paraformer + VAD + 标点，约 1.5GB）\n"
                "下载完成后自动加载，无需手动操作。"
            )
            yes_btn = box.addButton("立即下载", QMessageBox.ButtonRole.AcceptRole)
            no_btn = box.addButton("暂不下载", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(yes_btn)
            box.exec()
            if box.clickedButton() is yes_btn:
                self._start_model_download()
                return
            QMessageBox.warning(
                self, "提示",
                "模型未下载，语音识别功能不可用。\n"
                "后续可运行 python download.py 手动下载。"
            )
            return

        QMessageBox.critical(self, "错误", f"模型加载失败：{error_msg}")

    def _start_model_download(self):
        """启动后台模型下载线程"""
        self.log("开始自动下载语音识别模型（约 1.5GB），请稍候...", "info", 1)
        self.status_model.setText("⏳ 正在下载模型…")
        self.status_model.setStyleSheet("color: #d97706; padding: 0 6px;")
        self.download_thread = ModelDownloadThread()
        self.download_thread.progress.connect(
            lambda msg, level: self.log(msg, level, 1))
        self.download_thread.progress.connect(
            lambda msg, level: self.log(msg, level, 2))
        self.download_thread.finished_all.connect(self._on_download_finished)
        self.download_thread.start()

    def _on_download_finished(self, ok):
        """模型下载完成后的回调：成功则自动重新加载"""
        if ok:
            self.log("模型下载完成，正在自动加载...", "success", 1)
            self.log("模型下载完成，正在自动加载...", "success", 2)
            self.status_model.setText("⏳ 模型加载中…")
            self.status_model.setStyleSheet("color: #d97706; padding: 0 6px;")
            self.model_loader = ModelLoaderThread()
            self.model_loader.finished.connect(self._on_model_loaded)
            self.model_loader.error.connect(self._on_model_error)
            self.model_loader.start()
        else:
            self.status_model.setText("🔴 模型下载失败")
            self.status_model.setStyleSheet("color: #dc2626; padding: 0 6px;")
            QMessageBox.critical(
                self, "错误",
                "模型下载失败，请检查网络后重试。\n"
                "或运行 python download.py 手动下载。"
            )

    # ====== LLM backend + 设置 ======

    def _on_llm_loaded(self, backend):
        self.llm_backend = backend
        self.log(f"LLM backend 就绪: {backend}", "success", 1)
        try:
            provider = getattr(backend.config, "provider", "?")
            model = getattr(backend.config, "model", "?")
            self.status_llm.setText(f"🟢 LLM: {provider}/{model}")
        except Exception:
            self.status_llm.setText("🟢 LLM 就绪")
        self.status_llm.setStyleSheet("color: #16a34a; padding: 0 6px;")

    def _on_llm_error(self, error_msg):
        self.llm_backend = None
        self.log(f"LLM backend 初始化失败：{error_msg}", "error", 1)
        self.log("翻译/总结功能将不可用，修复后点击 ⚙ 重新设置", "warning", 1)
        self.status_llm.setText("🔴 LLM 不可用")
        self.status_llm.setStyleSheet("color: #dc2626; padding: 0 6px;")

    def _reload_llm_backend_async(self):
        """设置保存后异步重建 backend"""
        self.llm_backend = None
        self.status_llm.setText("⏳ LLM 重建中…")
        self.status_llm.setStyleSheet("color: #d97706; padding: 0 6px;")
        self.llm_loader = LLMBackendInitThread()
        self.llm_loader.finished.connect(self._on_llm_loaded)
        self.llm_loader.error.connect(self._on_llm_error)
        self.llm_loader.start()

    def open_settings(self):
        """弹出设置对话框；保存后立即重建 LLM backend（ASR 改动需重启）

        注意：parent 必须传可见的 self.ui（不是 self），否则对话框定位到屏幕外无法拖拽。
        """
        try:
            result = settings_dialog.open_settings(self.ui)
            if result:  # 用户点了保存
                self._reload_llm_backend_async()
                self.log("设置已保存。LLM 立即生效，ASR 模型改动需重启。", "success", 1)
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

    def _position_floating_buttons(self):
        """定位右下角固定按钮 + 左下角设置按钮（监听 self.ui 的 Resize 事件）"""
        if not hasattr(self, 'ui') or self.ui is None:
            return
        margin = 10
        if hasattr(self, 'pin_button'):
            self.pin_button.move(
                self.ui.width() - self.pin_button.width() - margin,
                self.ui.height() - self.pin_button.height() - margin
            )
        if hasattr(self, 'settings_button'):
            self.settings_button.move(
                margin,
                self.ui.height() - self.settings_button.height() - margin
            )

    def eventFilter(self, obj, event):
        """监听 self.ui 的尺寸变化，保持悬浮按钮贴在角落"""
        if obj is self.ui and event.type() == QEvent.Type.Resize:
            self._position_floating_buttons()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """处理窗口大小改变事件（MainWindow 自身；self.ui 的变化走 eventFilter）"""
        super().resizeEvent(event)
        self._position_floating_buttons()


def _app_icon_path() -> str:
    """返回应用图标绝对路径（不依赖当前工作目录）"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "AI视频转文字.ico")


def main():
    app = QApplication(sys.argv)
    # 应用统一主题（Fusion + 浅色 palette + QSS）
    ui_theme.apply_theme(app)
    # 设置应用程序图标（绝对路径 + 真 ICO 格式，确保任务栏显示）
    icon_path = _app_icon_path()
    app_icon = QIcon(icon_path)
    app.setWindowIcon(app_icon)
    window = MainWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
    