"""
统一 UI 主题：全局 QSS 样式 + 颜色常量
被 settings_dialog.py / main_window.py 共用
"""
from __future__ import annotations

# ===== 调色板 =====
COLORS = {
    "bg":          "#f5f6f8",   # 窗口背景
    "surface":     "#ffffff",   # 卡片/输入框背景
    "border":      "#d9dee3",   # 边框
    "border_soft": "#e5e8ec",   # 弱边框
    "text":        "#1f2329",   # 主文本
    "text_muted":  "#6b7280",   # 次要文本
    "accent":      "#3b82f6",   # 主色
    "accent_hover":"#2563eb",
    "accent_press":"#1d4ed8",
    "success":     "#16a34a",
    "warning":     "#d97706",
    "error":       "#dc2626",
}

# ===== 全局样式表 =====
GLOBAL_QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {COLORS['bg']};
}}
QLabel {{
    color: {COLORS['text']};
    background: transparent;
}}
QLabel[muted="true"] {{
    color: {COLORS['text_muted']};
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['surface']};
    border: 1px solid #d0d5dc;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #bfdbfe;
    selection-color: {COLORS['text']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {COLORS['accent']};
    background-color: #fdfeff;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: #f1f3f5;
    color: #9ca3af;
    border-color: #e5e8ec;
}}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{
    border: 1px solid {COLORS['error']};
    background-color: #fef2f2;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['surface']};
    border: 1px solid #d0d5dc;
    border-radius: 6px;
    selection-background-color: #eff6ff;
    selection-color: #1d4ed8;
    outline: none;
    padding: 4px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background-color: {COLORS['surface']};
    border: 1px solid #d0d5dc;
    border-radius: 6px;
    padding: 6px 16px;
    color: {COLORS['text']};
}}
QPushButton:hover {{
    background-color: #f3f4f6;
    border-color: #b6bcc6;
}}
QPushButton:pressed {{
    background-color: #e5e7eb;
}}
QPushButton:disabled {{
    color: #9ca3af;
    background-color: #f1f3f5;
    border-color: #e5e8ec;
}}
/* 主按钮 */
QPushButton[role="primary"] {{
    background-color: {COLORS['accent']};
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 7px 20px;
}}
QPushButton[role="primary"]:hover {{ background-color: {COLORS['accent_hover']}; }}
QPushButton[role="primary"]:pressed {{ background-color: {COLORS['accent_press']}; }}
QPushButton[role="primary"]:disabled {{ background-color: #93c5fd; color: #ffffff; }}
/* 成功态（保存完成） */
QPushButton[role="success"] {{
    background-color: {COLORS['success']};
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 7px 20px;
}}
QPushButton[role="success"]:hover {{ background-color: #15803d; }}
/* 幽灵按钮（图标类） */
QPushButton[role="ghost"] {{
    background: transparent;
    border: none;
    font-size: 15px;
    padding: 2px;
}}
QPushButton[role="ghost"]:hover {{ background-color: #f3f4f6; border-radius: 6px; }}
QPushButton[role="ghost"]:pressed {{ background-color: #e5e7eb; }}
/* 服务商卡片 */
QPushButton[role="card"] {{
    background-color: {COLORS['surface']};
    border: 1px solid #d9dee3;
    border-radius: 10px;
    padding: 12px 14px;
    text-align: left;
}}
QPushButton[role="card"]:hover {{
    border-color: #93c5fd;
    background-color: #f8fbff;
}}
QPushButton[role="card"]:checked {{
    border: 2px solid {COLORS['accent']};
    background-color: #eff6ff;
}}
QPushButton[role="card"]:pressed {{ background-color: #e0edff; }}

/* ---------- 分组框 ---------- */
QGroupBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border_soft']};
    border-radius: 10px;
    margin-top: 10px;
    padding: 8px 10px 6px 10px;
    font-weight: 600;
    color: #374151;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    top: 0px;
    padding: 0 6px;
    background-color: {COLORS['surface']};
    color: #374151;
}}
QGroupBox:disabled {{ color: #9ca3af; }}
QGroupBox:disabled::title {{ color: #9ca3af; }}

/* ---------- 标签页 ---------- */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    padding: 8px 18px;
    border-bottom: 2px solid transparent;
    color: {COLORS['text_muted']};
}}
QTabBar::tab:selected {{
    color: {COLORS['text']};
    font-weight: 600;
    border-bottom: 2px solid {COLORS['accent']};
}}
QTabBar::tab:hover:!selected {{
    color: #374151;
    border-bottom: 2px solid #d1d5db;
}}

/* ---------- 状态徽章 ---------- */
QLabel[role="badge-success"] {{
    color: #15803d;
    background-color: #dcfce7;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
}}
QLabel[role="badge-error"] {{
    color: #b91c1c;
    background-color: #fee2e2;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
}}
QLabel[role="badge-warning"] {{
    color: #b45309;
    background-color: #fef3c7;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
}}
QLabel[role="badge-neutral"] {{
    color: #374151;
    background-color: #e5e7eb;
    border-radius: 6px;
    padding: 4px 10px;
}}

/* ---------- 提示/说明框 ---------- */
QLabel[role="callout"] {{
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 10px 12px;
    color: #1e40af;
    font-size: 12px;
}}
QLabel[role="hint"] {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}

/* ---------- Toast ---------- */
QLabel[role="toast-info"] {{
    background-color: #1f2937;
    color: #f9fafb;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 12px;
}}
QLabel[role="toast-success"] {{
    background-color: #065f46;
    color: #d1fae5;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 12px;
}}
QLabel[role="toast-error"] {{
    background-color: #7f1d1d;
    color: #fee2e2;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 12px;
}}

/* ---------- 日志区 ---------- */
QTextEdit {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border_soft']};
    border-radius: 8px;
    padding: 6px;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
}}
QTextEdit:focus {{ border: 1px solid #d0d5dc; }}

/* ---------- 状态栏 ---------- */
QStatusBar {{
    background-color: {COLORS['surface']};
    border-top: 1px solid {COLORS['border_soft']};
    color: {COLORS['text_muted']};
}}
QStatusBar::item {{ border: none; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #c8cdd4; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #aab1ba; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #c8cdd4; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: #aab1ba; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- 提示气泡 ---------- */
QToolTip {{
    background-color: #111827;
    color: #f9fafb;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
    font-size: 12px;
}}
"""


def apply_theme(app) -> None:
    """对 QApplication 应用 Fusion 风格 + 强制浅色 palette + 全局 QSS（幂等，重复调用安全）

    注意：部分环境（如 Windows 深色模式）下 Qt 默认 palette 为深色（白字/深底），
    必须显式设置浅色 palette，否则 QSS 未覆盖的控件会白底白字。
    """
    try:
        if app.style().objectName().lower() != "fusion":
            app.setStyle("Fusion")
    except Exception:
        pass

    # ---- 强制浅色 palette（覆盖深色系统主题） ----
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    c = COLORS
    pal.setColor(QPalette.ColorRole.Window, QColor(c["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f3f4f6"))
    pal.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9ca3af"))
    pal.setColor(QPalette.ColorRole.Button, QColor(c["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Link, QColor(c["accent"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#f9fafb"))
    pal.setColor(QPalette.ColorRole.Light, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Midlight, QColor("#f3f4f6"))
    pal.setColor(QPalette.ColorRole.Mid, QColor("#d0d5dc"))
    pal.setColor(QPalette.ColorRole.Dark, QColor("#b6bcc6"))
    pal.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
    # 禁用态
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9ca3af"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#9ca3af"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9ca3af"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor("#f1f3f5"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#f1f3f5"))
    app.setPalette(pal)

    if not app.styleSheet():
        app.setStyleSheet(GLOBAL_QSS)


def refresh_style(widget) -> None:
    """属性变化后刷新样式（unpolish + polish）"""
    style = widget.style()
    if style:
        style.unpolish(widget)
        style.polish(widget)
