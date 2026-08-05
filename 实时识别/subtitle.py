import os
import html as _html
from PySide6.QtWidgets import (QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QSlider,
                             QDialog, QApplication, QTextEdit, QDoubleSpinBox)
from PySide6.QtCore import Qt, QPoint, Signal, QRect, QTimer
from PySide6.QtGui import QMouseEvent, QCursor, QFont
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QIcon
from settings_manager import SettingsManager

class SettingsDialog(QDialog):
    """设置对话框"""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("字幕设置")
        self.setFixedSize(300, 180)     # 设置固定大小
        app_icon = QIcon("AI视频转文字.ico")
        self.setWindowIcon(app_icon)
        
        # 获取设置管理器实例
        self.settings_manager = SettingsManager()
        
        # 保存父窗口的原始设置
        self.original_opacity = parent.windowOpacity()
        self.original_font_size = parent.subtitle_text.font().pointSize()
        
        # 创建垂直布局
        layout = QVBoxLayout()
        
        # 创建透明度滑块
        self.opacity_label = QLabel("窗口透明度:")
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setMinimum(10)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(int(self.original_opacity * 100))
        
        # 创建字体大小滑块
        self.font_size_label = QLabel("字体大小:")
        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setMinimum(12)
        self.font_size_slider.setMaximum(72)
        self.font_size_slider.setValue(self.original_font_size)
        
        # 创建缓冲区大小设置
        buffer_layout = QHBoxLayout()
        self.buffer_label = QLabel("缓冲区大小(秒):")
        self.buffer_spin = QDoubleSpinBox()
        self.buffer_spin.setRange(1.0, 10.0)
        self.buffer_spin.setValue(self.settings_manager.get_buffer_duration())
        self.buffer_spin.setSingleStep(0.5)
        self.buffer_spin.setFixedWidth(80)
        buffer_layout.addWidget(self.buffer_label)
        buffer_layout.addWidget(self.buffer_spin)
        buffer_layout.addStretch()
        
        # 创建按钮布局
        button_layout = QHBoxLayout()
        
        # 创建确定和取消按钮
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")
        
        # 连接按钮信号
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        # 添加按钮到布局
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        # 添加控件到主布局
        layout.addWidget(self.opacity_label)
        layout.addWidget(self.opacity_slider)
        layout.addWidget(self.font_size_label)
        layout.addWidget(self.font_size_slider)
        layout.addLayout(buffer_layout)
        layout.addStretch()  # 添加弹性空间
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def on_buffer_changed(self, value):
        """缓冲区大小改变时的处理"""
        # 获取主窗口实例
        main_window = self.parent().parent()
        if main_window and hasattr(main_window, 'audio_thread') and main_window.audio_thread and main_window.audio_thread.isRunning():
            main_window.audio_thread.set_buffer_duration(value)
            main_window.update_status(f"缓冲区大小已调整为 {value} 秒")
    
    def accept(self):
        """确定按钮点击事件"""
        if self.parent():
            # 更新窗口设置
            opacity = self.opacity_slider.value() / 100.0
            font_size = self.font_size_slider.value()
            buffer_duration = self.buffer_spin.value()
            
            # 更新设置管理器
            self.settings_manager.update_settings(
                buffer_duration=buffer_duration,
                opacity=opacity,
                font_size=font_size,
                window_type='subtitle'
            )
            
            # 应用设置到窗口
            self.parent().setWindowOpacity(opacity)
            font = self.parent().subtitle_text.font()
            font.setPointSize(font_size)
            self.parent().subtitle_text.setFont(font)
            
            # 更新缓冲区大小
            self.on_buffer_changed(buffer_duration)
            
        super().accept()
    
    def reject(self):
        """取消按钮点击事件"""
        if self.parent():
            self.parent().setWindowOpacity(self.original_opacity)
            # 恢复原始字体大小
            font = self.parent().subtitle_text.font()
            font.setPointSize(self.original_font_size)
            self.parent().subtitle_text.setFont(font)
        super().reject()

class SubtitleWindow(QWidget):
    """字幕窗口（统一：仅原文 / 仅翻译 / 原文+翻译）"""
    # 定义调整大小的区域大小
    RESIZE_MARGIN = 5
    
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._setup_window()
        self._connect_signals()
        
        # 初始化拖动相关变量
        self._drag_position = None
        self._is_dragging = False
        self._resize_edge = None
        self._resize_start_pos = None
        self._resize_start_geometry = None
        
        # 显示模式与最近内容（原文/翻译配对）
        self._display_mode = SettingsManager().get_display_mode()  # original / translation / both
        self._last_original = ""
        self._last_translation = ""
        
        # 设置默认透明度
        self.setWindowOpacity(self.settings_manager.get_opacity('subtitle'))
        
        # 设置最小窗口大小
        self.setMinimumSize(400, 60)
        
        # 设置初始窗口大小
        self.resize(1300, 90)
        
        # 设置窗口位置到屏幕底部
        screen = QApplication.primaryScreen().geometry()
        window_width = self.width()
        x = (screen.width() - window_width) // 2  # 水平居中
        y = screen.height() - self.height() - 50  # 距离底部50像素
        self.move(x, y)
        
        # 设置默认鼠标样式
        self.setCursor(Qt.ArrowCursor)
        
        # 初始化标题栏显示控制
        self._title_bar_visible = True
        self._title_bar_timer = QTimer(self)
        self._title_bar_timer.setSingleShot(True)
        self._title_bar_timer.timeout.connect(self._hide_title_bar)
        
        # 默认隐藏标题栏
        self._hide_title_bar()
        # 初始按模式渲染
        self._render()
    
    def _init_ui(self):
        """初始化UI"""
        # 加载UI文件
        ui_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subtitle.ui")
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        
        # 获取控件引用
        self.title_bar = self.ui.findChild(QWidget, "titleBar")
        self.title_label = self.ui.findChild(QLabel, "titleLabel")
        self.settings_button = self.ui.findChild(QPushButton, "settingsButton")
        self.close_button = self.ui.findChild(QPushButton, "closeButton")
        self.subtitle_text = self.ui.findChild(QTextEdit,"subtitle")

        # 设置QTextEdit
        self.subtitle_text.setReadOnly(True)  # 设置为只读
        self.subtitle_text.setFrameStyle(QTextEdit.NoFrame)  # 移除边框
        self.subtitle_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏垂直滚动条
        self.subtitle_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏水平滚动条
        self.subtitle_text.setText("字幕将在这里显示")
        # 设置默认字体
        font = QFont()
        self.settings_manager = SettingsManager()
        font.setPointSize(self.settings_manager.get_font_size())  #从设置管理器获取字体大小
        font.setBold(True)     # 设置粗体
        self.subtitle_text.setFont(font)
        
        self.subtitle_text.setStyleSheet("""
            QTextEdit {
                color: white;
                background-color: transparent;
                selection-background-color: rgba(255, 255, 255, 0.3);
                selection-color: white;
            }
        """)
        
        # 设置文本居中对齐
        self.subtitle_text.setAlignment(Qt.AlignCenter)
        
        # 设置布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.ui)
        self.setLayout(main_layout)
    
    def _setup_window(self):
        """设置窗口属性"""
        # 设置窗口标志
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # 设置窗口样式
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                color: white;
                border: none;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            #titleBar {
                background-color: rgba(0, 0, 0, 0.5);
            }
        """)
    
    def _connect_signals(self):
        """连接信号"""
        self.settings_button.clicked.connect(self._show_settings)
        self.close_button.clicked.connect(self.hide)  # 改为隐藏而不是关闭
    
    def _show_settings(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Rejected:
            # 如果用户取消，恢复原始透明度
            self.setWindowOpacity(dialog.original_opacity)
    
    def _get_resize_edge(self, pos):
        """获取调整大小的边缘"""
        width = self.width()
        height = self.height()
        
        # 检查是否在调整大小的边缘区域
        if pos.x() <= self.RESIZE_MARGIN:
            if pos.y() <= self.RESIZE_MARGIN:
                return 'topleft'
            elif pos.y() >= height - self.RESIZE_MARGIN:
                return 'bottomleft'
            return 'left'
        elif pos.x() >= width - self.RESIZE_MARGIN:
            if pos.y() <= self.RESIZE_MARGIN:
                return 'topright'
            elif pos.y() >= height - self.RESIZE_MARGIN:
                return 'bottomright'
            return 'right'
        elif pos.y() <= self.RESIZE_MARGIN:
            return 'top'
        elif pos.y() >= height - self.RESIZE_MARGIN:
            return 'bottom'
        return None
    
    def _update_cursor(self, edge):
        """更新鼠标指针样式"""
        if self._is_dragging:
            self.setCursor(Qt.CrossCursor)
        elif edge:
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
    
    def _show_title_bar(self):
        """显示标题栏"""
        if not self._title_bar_visible:
            self._title_bar_visible = True
            self.title_bar.show()
      
    
    def _hide_title_bar(self):
        """隐藏标题栏"""
        if self._title_bar_visible:
            self._title_bar_visible = False
            self.title_bar.hide()

    
    def enterEvent(self, event):
        """鼠标进入窗口事件"""
        self._show_title_bar()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开窗口事件"""
        # 检查鼠标是否真的离开了整个窗口
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._hide_title_bar()
        super().leaveEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            # 检查是否在调整大小的边缘
            edge = self._get_resize_edge(event.pos())
            if edge:
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
            else:
                # 如果不在边缘，则进行窗口拖动
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._is_dragging = True
                # 拖动时显示十字架
                self.setCursor(Qt.CrossCursor)
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            # 处理窗口拖动
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        elif self._resize_edge and event.buttons() == Qt.LeftButton:
            # 处理窗口大小调整
            self._handle_resize(event.globalPosition().toPoint())
            event.accept()
        else:
            # 更新鼠标指针样式
            edge = self._get_resize_edge(event.pos())
            self._update_cursor(edge)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            self._resize_edge = None
            self._resize_start_pos = None
            self._resize_start_geometry = None
            # 恢复鼠标样式
            self._update_cursor(event.pos())
            event.accept()
    
    def _handle_resize(self, pos):
        """处理窗口大小调整"""
        if not self._resize_start_pos or not self._resize_start_geometry:
            return
        
        delta = pos - self._resize_start_pos
        new_geometry = QRect(self._resize_start_geometry)
        
        # 根据不同的边缘调整窗口大小
        if 'right' in self._resize_edge:
            new_geometry.setWidth(max(self.minimumWidth(), new_geometry.width() + delta.x()))
        if 'bottom' in self._resize_edge:
            new_geometry.setHeight(max(self.minimumHeight(), new_geometry.height() + delta.y()))
        if 'left' in self._resize_edge:
            new_width = max(self.minimumWidth(), new_geometry.width() - delta.x())
            new_geometry.setLeft(new_geometry.right() - new_width)
        if 'top' in self._resize_edge:
            new_height = max(self.minimumHeight(), new_geometry.height() - delta.y())
            new_geometry.setTop(new_geometry.bottom() - new_height)
        
        self.setGeometry(new_geometry)
    
    def set_mode(self, mode: str):
        """设置显示模式：original(仅原文) / translation(仅翻译) / both(原文+翻译)"""
        if mode not in ("original", "translation", "both"):
            return
        self._display_mode = mode
        SettingsManager().set_display_mode(mode)  # 持久化
        # 双行模式需要更高窗口
        self.setMinimumHeight(120 if mode == "both" else 60)
        self._render()

    def get_mode(self) -> str:
        return self._display_mode

    def update_original(self, text: str):
        """更新原文字幕（只存最近一段，与翻译配对显示）"""
        self._last_original = text
        self._render()

    def update_translation(self, text: str):
        """更新翻译字幕（异步到达后刷新显示）"""
        self._last_translation = text
        self._render()

    def _render(self):
        """按显示模式渲染字幕（原文白色，翻译金色）"""
        orig = _html.escape(self._last_original)
        trans = _html.escape(self._last_translation)
        mode = self._display_mode
        if mode == "translation":
            body = f'<div style="text-align:center; color:#ffd54f;">{trans}</div>'
        elif mode == "both":
            body = (f'<div style="text-align:center; color:#ffffff;">{orig}</div>'
                    f'<div style="text-align:center; color:#ffd54f; margin-top:6px;">{trans}</div>')
        else:  # original
            body = f'<div style="text-align:center; color:#ffffff;">{orig}</div>'
        self.subtitle_text.setHtml(body)
        self.subtitle_text.setAlignment(Qt.AlignCenter)

    def update_subtitle(self, text: str):
        """兼容旧接口：更新原文字幕"""
        self.update_original(text) 