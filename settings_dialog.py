"""
设置对话框 + .env 读写

- SettingsDialog: PySide6 设置 UI（现代化样式 + 完整交互反馈）
- load_env() / save_env(): 读写 .env 文件

交互反馈要点：
  * 服务商卡片式选择，选中即高亮
  * 任何改动即时标记"未保存修改"（标题 + 徽章 + 标签页圆点）
  * 保存按钮 → 绿色"✓ 已保存"成功态 + Toast 提示
  * 测试连接在后台线程运行，按钮禁用 + 转圈动画 + 结果徽章
  * API Key 可一键显示/隐藏；输入校验失败红框提示
  * 配置来源指示：.env 未创建时明确警告用的是模板占位值
"""

import os
from pathlib import Path
from typing import Dict

import config

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

from ui_theme import GLOBAL_QSS, refresh_style

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"

PLACEHOLDER_KEY_HINT = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"


# ====== .env 读写 ======

def load_env() -> Dict[str, str]:
    """读取 .env 内容（dict），文件不存在返回空 dict"""
    if not ENV_FILE.exists():
        return {}
    if dotenv_values is None:
        # 退化方案：手动解析
        result = {}
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                result[k.strip()] = v.strip()
        return result
    return dict(dotenv_values(ENV_FILE))


def save_env(values: Dict[str, str]) -> None:
    """把 dict 写回 .env（保留注释和空行结构，简化处理：全量覆盖）"""
    lines = [
        "# AI-VedioToText 配置",
        "# 由设置面板自动生成，请勿手动修改格式",
        "",
    ]
    # 固定顺序，更易读
    keys_order = [
        "LLM_PROVIDER",
        "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_AUTO_START",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "LLM_TEMPERATURE", "LLM_CONCURRENCY",
        "ASR_BACKEND", "ASR_MODEL", "ASR_MODEL_DIR", "ASR_DEVICE", "ASR_USE_PUNC",
    ]
    for key in keys_order:
        if key in values:
            v = values[key]
            # 包含空格或特殊字符加引号
            if any(c in v for c in [' ', '#', '"']):
                v = '"' + v.replace('"', '\\"') + '"'
            lines.append(f"{key}={v}")

    # 任何额外 key
    extra = [k for k in values if k not in keys_order]
    if extra:
        lines.append("")
        lines.append("# 其他")
        for k in extra:
            lines.append(f"{k}={values[k]}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding='utf-8')


# ====== Qt 导入（顶层 try/except：无 Qt 环境时仅 .env 读写可用） ======

try:
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
        QLineEdit, QComboBox, QPushButton, QLabel, QCheckBox, QDoubleSpinBox,
        QMessageBox, QGroupBox, QSpinBox, QGraphicsOpacityEffect,
    )
    from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPropertyAnimation, QEasingCurve
except ImportError:  # 无 PySide6：load_env / save_env 仍可用
    QDialog = QVBoxLayout = QHBoxLayout = QFormLayout = QTabWidget = None
    QWidget = QLineEdit = QComboBox = QPushButton = QLabel = None
    QCheckBox = QDoubleSpinBox = QMessageBox = QGroupBox = QSpinBox = None
    QGraphicsOpacityEffect = None
    Qt = QTimer = QThread = Signal = QPropertyAnimation = QEasingCurve = None


def _get_qt():
    """返回 Qt 类字典（延迟导入包装，供 _SettingsDialogImpl 使用）"""
    return {
        'QDialog': QDialog, 'QVBoxLayout': QVBoxLayout, 'QHBoxLayout': QHBoxLayout,
        'QFormLayout': QFormLayout, 'QTabWidget': QTabWidget, 'QWidget': QWidget,
        'QLineEdit': QLineEdit, 'QComboBox': QComboBox, 'QPushButton': QPushButton,
        'QLabel': QLabel, 'QCheckBox': QCheckBox, 'QDoubleSpinBox': QDoubleSpinBox,
        'QMessageBox': QMessageBox, 'QGroupBox': QGroupBox, 'QSpinBox': QSpinBox,
        'Qt': Qt, 'QTimer': QTimer, 'QThread': QThread, 'Signal': Signal,
        'QPropertyAnimation': QPropertyAnimation, 'QEasingCurve': QEasingCurve,
        'QGraphicsOpacityEffect': QGraphicsOpacityEffect,
    }


class Toast(QLabel):
    """悬浮在对话框底部的轻提示"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setVisible(False)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim.setDuration(160)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def show_message(self, text, kind="info", duration=2400):
        self.setText(text)
        self.adjustSize()
        max_w = self.parent().width() - 60
        self.setFixedWidth(min(max_w, 560))
        self.adjustSize()
        x = (self.parent().width() - self.width()) // 2
        y = self.parent().height() - self.height() - 60
        self.move(max(x, 10), max(y, 10))
        self.setProperty("role", f"toast-{kind}")
        refresh_style(self)
        self.show()
        self.raise_()
        self._opacity.setOpacity(0.0)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(duration)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._opacity.opacity())
        self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect(self.hide)
        except (RuntimeError, TypeError):
            pass
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def reposition(self):
        """父窗口尺寸变化时重新定位"""
        if self.isVisible():
            x = (self.parent().width() - self.width()) // 2
            y = self.parent().height() - self.height() - 60
            self.move(max(x, 10), max(y, 10))


# ====== 测试连接后台线程 ======

class TestWorker(QThread):
    """在后台线程测试 LLM 连接，避免阻塞 UI"""
    result = Signal(bool, str)

    def __init__(self, cfg: Dict[str, str], parent=None):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        from llm_backend import LLMConfig, OllamaBackend, DeepSeekBackend
        try:
            is_ollama = self.cfg["LLM_PROVIDER"] == "ollama"
            llm_cfg = LLMConfig(
                provider=self.cfg["LLM_PROVIDER"],
                base_url=self.cfg["OLLAMA_BASE_URL"] if is_ollama else self.cfg["DEEPSEEK_BASE_URL"],
                api_key=self.cfg.get("DEEPSEEK_API_KEY") or None,
                model=self.cfg["OLLAMA_MODEL"] if is_ollama else self.cfg["DEEPSEEK_MODEL"],
                temperature=float(self.cfg.get("LLM_TEMPERATURE", "0.3")),
                timeout=15,  # 测试连接用短超时
            )
            backend = (OllamaBackend(llm_cfg, auto_start=False) if is_ollama
                       else DeepSeekBackend(llm_cfg))
            ok, msg = backend.test_connection()
        except Exception as e:
            ok, msg = False, f"✗ {type(e).__name__}: {e}"
        self.result.emit(ok, msg)


# ====== 对话框基类（处理未保存关闭确认） ======

class SettingsDialogBase(QDialog):
    """带 closeEvent 拦截的 QDialog，用于未保存修改提示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._impl = None  # 由 _SettingsDialogImpl 注入

    def showEvent(self, event):
        super().showEvent(event)
        if self._impl is not None:
            self._impl._center_dialog()

    def closeEvent(self, event):
        impl = self._impl
        if impl and impl.is_dirty():
            action = impl.ask_discard()
            if action == "save":
                impl._on_save()
                event.ignore()  # 保存成功后会自己 accept
                return
            if action == "discard":
                event.accept()
                return
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._impl and self._impl.toast:
            self._impl.toast.reposition()


# ====== 设置对话框 ======

class SettingsDialog:
    """工厂：创建并返回 QDialog 实例（避免模块顶层 import Qt）"""
    @staticmethod
    def create(parent=None) -> "QDialog":
        if QDialog is None:
            raise RuntimeError("PySide6 未安装，无法打开设置面板")
        impl = _SettingsDialogImpl(parent)
        return impl.dlg  # 返回真正的 QDialog 实例


class _SettingsDialogImpl:
    """实际实现（构造并填充 QDialog）"""

    def __init__(self, parent=None):
        qt = _get_qt()
        self.dlg = SettingsDialogBase(parent)
        self.dlg.setWindowTitle("设置")
        self.dlg.setMinimumSize(620, 480)
        self.dlg.resize(700, 560)
        self.dlg.setStyleSheet(GLOBAL_QSS)
        self.dlg._impl = self

        self._qt = qt
        self._current = load_env()
        self._env_exists = ENV_FILE.exists()
        if not self._current:
            # 没 .env 就从 .env.example 读默认值
            if ENV_EXAMPLE_FILE.exists() and dotenv_values is not None:
                self._current = dict(dotenv_values(ENV_EXAMPLE_FILE))

        self._dirty = False
        self._dirty_tabs = {0: False, 1: False}
        self._saving = False
        self._spin_idx = 0

        self._build_ui()
        self._sync_provider_ui()
        self._update_dirty_ui()
        self._fit_and_center()

    def _fit_and_center(self):
        """按内容自适应对话框高度（避免文字挤压），居中并确保标题栏在屏幕内"""
        try:
            # 1. 让布局完成计算，取真实需要的高度
            layout = self.dlg.layout()
            if layout is not None:
                layout.activate()
            hint_h = self.dlg.sizeHint().height()
            # 2. 高度上限 = 屏幕可用高度 - 标题栏/边框
            titlebar = 40
            screen = self.dlg.screen()
            max_h = hint_h
            if screen is not None:
                sg = screen.availableGeometry()
                max_h = sg.height() - titlebar
            target_h = min(max(hint_h, self.dlg.minimumSizeHint().height()), max_h)
            target_h = max(target_h, 500)  # 下限，避免小屏完全放不下
            self.dlg.resize(700, target_h)
            # 3. 居中：优先可见父窗口，否则屏幕
            parent = self.dlg.parentWidget()
            if parent is not None and parent.isVisible():
                pg = parent.geometry()
                x = pg.x() + (pg.width() - self.dlg.width()) // 2
                y = pg.y() + (pg.height() - self.dlg.height()) // 2
            else:
                if screen is None:
                    return
                sg = screen.availableGeometry()
                x = sg.x() + (sg.width() - self.dlg.width()) // 2
                y = sg.y() + (sg.height() - self.dlg.height()) // 2
            x = max(x, 0)
            y = max(y, 0)
            self.dlg.move(x, y)
        except Exception:
            pass

    def _center_dialog(self):
        """显示前兜底：居中 + 确保标题栏在屏幕内可拖拽"""
        self._fit_and_center()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        qt = self._qt
        layout = qt['QVBoxLayout'](self.dlg)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        # ---- 顶部标题 ----
        header = qt['QHBoxLayout'](self.dlg)
        title = qt['QLabel']("⚙️  设置")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        header.addWidget(title)
        self.source_badge = qt['QLabel']("")
        header.addWidget(self.source_badge)
        header.addStretch()
        layout.addLayout(header)

        # ---- 标签页 ----
        tabs = qt['QTabWidget']()
        layout.addWidget(tabs, 1)
        self.tabs = tabs

        # ===== LLM 服务 标签页 =====
        llm_tab = qt['QWidget']()
        llm_layout = qt['QVBoxLayout'](llm_tab)
        llm_layout.setSpacing(8)

        # 服务商卡片选择
        provider_label = qt['QLabel']("选择 LLM 服务商")
        provider_label.setStyleSheet("font-weight: 600; color: #374151;")
        llm_layout.addWidget(provider_label)

        cards = qt['QHBoxLayout'](llm_tab)
        cards.setSpacing(12)
        self.ollama_card = qt['QPushButton']("🤖  Ollama（本地）\n本地部署 · 免费 · 隐私")
        self.ollama_card.setCheckable(True)
        self.ollama_card.setProperty("role", "card")
        self.ollama_card.setMinimumHeight(48)
        self.deepseek_card = qt['QPushButton']("☁️  DeepSeek（云端）\nAPI 调用 · 无需 GPU · 更强模型")
        self.deepseek_card.setCheckable(True)
        self.deepseek_card.setProperty("role", "card")
        self.deepseek_card.setMinimumHeight(48)
        cards.addWidget(self.ollama_card, 1)
        cards.addWidget(self.deepseek_card, 1)
        llm_layout.addLayout(cards)
        self.ollama_card.toggled.connect(lambda on: self._on_card_toggled(self.ollama_card, self.deepseek_card, on))
        self.deepseek_card.toggled.connect(lambda on: self._on_card_toggled(self.deepseek_card, self.ollama_card, on))

        # 当前生效 provider 徽章
        self.provider_badge = qt['QLabel']("")
        self.provider_badge.setProperty("role", "badge-neutral")
        llm_layout.addWidget(self.provider_badge)

        # Ollama 配置
        self.ollama_group = qt['QGroupBox']("Ollama 配置")
        og_layout = qt['QFormLayout'](self.ollama_group)
        og_layout.setHorizontalSpacing(14)
        og_layout.setVerticalSpacing(4)
        self.ollama_url = qt['QLineEdit'](self._current.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        self.ollama_url.setPlaceholderText("http://localhost:11434")
        self.ollama_model = qt['QLineEdit'](self._current.get("OLLAMA_MODEL", "qwen2.5:7b"))
        self.ollama_model.setPlaceholderText("qwen2.5:7b")
        self.ollama_auto = qt['QCheckBox']("启动时自动拉起 ollama serve")
        self.ollama_auto.setChecked(self._current.get("OLLAMA_AUTO_START", "true").lower() in ("true", "1", "yes"))
        og_layout.addRow("Base URL:", self.ollama_url)
        og_layout.addRow("模型:", self.ollama_model)
        og_layout.addRow("", self.ollama_auto)
        llm_layout.addWidget(self.ollama_group)

        # DeepSeek 配置
        self.deepseek_group = qt['QGroupBox']("DeepSeek 配置")
        dg_layout = qt['QFormLayout'](self.deepseek_group)
        dg_layout.setHorizontalSpacing(14)
        dg_layout.setVerticalSpacing(4)
        key_row = qt['QHBoxLayout'](self.deepseek_group)
        key_row.setSpacing(6)
        self.deepseek_key = qt['QLineEdit'](self._current.get("DEEPSEEK_API_KEY", ""))
        self.deepseek_key.setEchoMode(qt['QLineEdit'].EchoMode.Password)
        self.deepseek_key.setPlaceholderText("sk-...")
        self.eye_btn = qt['QPushButton']("👁")
        self.eye_btn.setCheckable(True)
        self.eye_btn.setFixedSize(32, 30)
        self.eye_btn.setToolTip("显示 / 隐藏 API Key")
        self.eye_btn.setProperty("role", "ghost")
        self.eye_btn.toggled.connect(
            lambda on: self.deepseek_key.setEchoMode(
                qt['QLineEdit'].EchoMode.Normal if on else qt['QLineEdit'].EchoMode.Password
            ))
        key_row.addWidget(self.deepseek_key, 1)
        key_row.addWidget(self.eye_btn)
        self.deepseek_url = qt['QLineEdit'](self._current.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        self.deepseek_url.setPlaceholderText("https://api.deepseek.com")
        self.deepseek_model = qt['QComboBox']()
        self.deepseek_model.setEditable(True)
        # DeepSeek V4 系列（deepseek-chat / deepseek-reasoner 2026-07-24 已下线）
        self.deepseek_model.addItems([
            "deepseek-v4-flash",        # 284B/13B 激活，免费，主力
            "deepseek-v4-pro",          # 1.6T/49B 激活，付费，强推理
            "deepseek-v4-pro-max",      # 1.6T，max 推理模式，最强
        ])
        current_ds_model = self._current.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        idx = self.deepseek_model.findText(current_ds_model)
        if idx >= 0:
            self.deepseek_model.setCurrentIndex(idx)
        else:
            self.deepseek_model.setCurrentText(current_ds_model)
        dg_layout.addRow("API Key:", key_row)
        dg_layout.addRow("Base URL:", self.deepseek_url)
        dg_layout.addRow("模型:", self.deepseek_model)
        llm_layout.addWidget(self.deepseek_group)

        # 行为参数
        behavior_group = qt['QGroupBox']("行为")
        bg_layout = qt['QFormLayout'](behavior_group)
        bg_layout.setHorizontalSpacing(14)
        bg_layout.setVerticalSpacing(4)
        self.temperature = qt['QDoubleSpinBox']()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setDecimals(1)
        self.temperature.setValue(float(self._current.get("LLM_TEMPERATURE", "0.3")))
        self.concurrency = qt['QSpinBox']()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(int(self._current.get("LLM_CONCURRENCY", "2")))
        bg_layout.addRow("温度 (0-2):", self.temperature)
        bg_layout.addRow("翻译并发 (1-8):", self.concurrency)
        llm_layout.addWidget(behavior_group)

        # 测试连接区域
        test_area = qt['QHBoxLayout'](llm_tab)
        test_area.setSpacing(8)
        self.test_btn = qt['QPushButton']("测试连接")
        self.test_btn.setToolTip("用当前填写的内容尝试连接并回复一条消息")
        self.spinner = qt['QLabel']("")
        self.spinner.setFixedWidth(20)
        self.spinner.setStyleSheet("color: #3b82f6; font-size: 15px;")
        self.spinner.hide()
        self.status_badge = qt['QLabel']("")
        self.status_badge.setProperty("role", "badge-neutral")
        self.status_badge.setText("尚未测试")
        test_area.addWidget(self.test_btn)
        test_area.addWidget(self.spinner)
        test_area.addWidget(self.status_badge, 1)
        llm_layout.addLayout(test_area)

        llm_hint = qt['QLabel']("💡 LLM 配置保存后立即生效；保存前可先点“测试连接”验证。")
        llm_hint.setProperty("role", "hint")
        llm_hint.setWordWrap(True)
        llm_layout.addWidget(llm_hint)
        llm_layout.addStretch()

        self.test_btn.clicked.connect(self._on_test)

        # ===== 语音识别 标签页 =====
        asr_tab = qt['QWidget']()
        asr_layout = qt['QVBoxLayout'](asr_tab)
        asr_layout.setSpacing(8)
        asr_group = qt['QGroupBox']("语音识别 (FunASR Paraformer)")
        ag_layout = qt['QFormLayout'](asr_group)
        ag_layout.setHorizontalSpacing(14)
        ag_layout.setVerticalSpacing(4)
        self.asr_backend = qt['QComboBox']()
        self.asr_backend.addItems(["funasr", "faster-whisper"])
        self.asr_backend.setCurrentText(self._current.get("ASR_BACKEND", "funasr"))
        self.asr_model = qt['QComboBox']()
        self.asr_model.addItems(["offline"])
        current_asr = self._current.get("ASR_MODEL", "offline")
        idx = self.asr_model.findText(current_asr)
        if idx >= 0:
            self.asr_model.setCurrentIndex(idx)
        else:
            self.asr_model.setCurrentText(current_asr)
        self.asr_use_punc = qt['QCheckBox']("启用标点恢复 (CT-PUNC)")
        self.asr_use_punc.setChecked(self._current.get("ASR_USE_PUNC", "true") not in ("false", "False", "0", ""))
        self.asr_device = qt['QComboBox']()
        self.asr_device.addItems(["auto", "cuda", "cpu"])
        self.asr_device.setCurrentText(self._current.get("ASR_DEVICE", "auto"))
        ag_layout.addRow("后端:", self.asr_backend)
        ag_layout.addRow("模型:", self.asr_model)
        ag_layout.addRow("设备:", self.asr_device)
        ag_layout.addRow("", self.asr_use_punc)
        asr_layout.addWidget(asr_group)

        asr_hint = qt['QLabel'](
            "ℹ️  说明\n"
            "• 基石模型由 download.py 下载到 model/ 目录（已存在自动跳过）\n"
            "• offline = Paraformer + VAD + 标点（唯一后端，中文高精度）\n"
            "• VAD 负责过滤静音/切句，标点负责断句，实时识别同样适用\n"
            "• faster-whisper 为可选后端，需自行下载模型\n"
            "⚠️  ASR 配置保存后需重启应用生效"
        )
        asr_hint.setProperty("role", "callout")
        asr_hint.setWordWrap(True)
        asr_layout.addWidget(asr_hint)
        asr_layout.addStretch()

        # 将两个标签页挂入 QTabWidget（必须，否则子树会被回收）
        tabs.addTab(llm_tab, "LLM 服务")
        tabs.addTab(asr_tab, "语音识别")

        # ---- 底部按钮 ----
        bottom = qt['QHBoxLayout'](self.dlg)
        bottom.setSpacing(10)
        self.dirty_label = qt['QLabel']("")
        self.dirty_label.setProperty("role", "badge-warning")
        bottom.addWidget(self.dirty_label)
        bottom.addStretch()
        self.cancel_btn = qt['QPushButton']("取消")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.save_btn = qt['QPushButton']("保存设置")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self._on_save)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        layout.addLayout(bottom)

        # Toast
        self.toast = Toast(self.dlg)

        # 注册所有字段的 dirty 监听
        self._bind_dirty(self.ollama_card, "toggled")
        self._bind_dirty(self.deepseek_card, "toggled")
        self._bind_dirty(self.ollama_url, "textChanged")
        self._bind_dirty(self.ollama_model, "textChanged")
        self._bind_dirty(self.ollama_auto, "toggled")
        self._bind_dirty(self.deepseek_key, "textChanged")
        self._bind_dirty(self.deepseek_url, "textChanged")
        self._bind_dirty(self.deepseek_model, "editTextChanged")
        self._bind_dirty(self.temperature, "valueChanged")
        self._bind_dirty(self.concurrency, "valueChanged")
        self._bind_dirty(self.asr_backend, "currentIndexChanged")
        self._bind_dirty(self.asr_model, "currentIndexChanged")
        self._bind_dirty(self.asr_device, "currentIndexChanged")
        self._bind_dirty(self.asr_use_punc, "toggled")

        # 输入时清除非法标记
        for w in (self.ollama_url, self.ollama_model, self.deepseek_key, self.deepseek_url):
            w.textChanged.connect(lambda _: self._clear_invalid(w))
        self.deepseek_model.editTextChanged.connect(lambda _: self._clear_invalid(self.deepseek_model))

        # 转圈动画
        self._spin_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spin_timer = qt['QTimer'](self.dlg)
        self._spin_timer.timeout.connect(self._spin_tick)

        self._update_source_badge()

    # ---------- 交互 ----------

    def _on_card_toggled(self, card, other, on):
        if on:
            other.setChecked(False)
            self._sync_provider_ui()
            self._mark_dirty(0)

    def _sync_provider_ui(self):
        is_ollama = self.ollama_card.isChecked()
        self.ollama_group.setEnabled(is_ollama)
        self.deepseek_group.setEnabled(not is_ollama)
        provider_name = "ollama" if is_ollama else "deepseek"
        model = (self.ollama_model.text().strip() or "-") if is_ollama \
            else (self.deepseek_model.currentText().strip() or "-")
        self.provider_badge.setText(f"当前生效：{provider_name} / {model}")
        refresh_style(self.provider_badge)

    def _bind_dirty(self, widget, signal_name):
        sig = getattr(widget, signal_name)
        tab = 0 if widget in (self.ollama_card, self.deepseek_card, self.ollama_url, self.ollama_model,
                              self.ollama_auto, self.deepseek_key, self.deepseek_url, self.deepseek_model,
                              self.temperature, self.concurrency) else 1
        sig.connect(lambda *_: self._mark_dirty(tab))

    def _mark_dirty(self, tab=0):
        if self._saving:
            return
        self._dirty = True
        self._dirty_tabs[tab] = True
        self._update_dirty_ui()

    def _update_dirty_ui(self):
        dirty = self._dirty
        self.dlg.setWindowTitle("设置" + (" · 未保存修改" if dirty else ""))
        self.dirty_label.setVisible(dirty)
        self.dirty_label.setText("● 有未保存的修改")
        # 标签页圆点
        titles = {0: "LLM 服务", 1: "语音识别"}
        for i, t in titles.items():
            prefix = "● " if self._dirty_tabs[i] else ""
            if self.tabs.tabText(i) != prefix + t:
                self.tabs.setTabText(i, prefix + t)

    def _update_source_badge(self):
        """指示配置来源：.env 存在 / 回退到模板占位值"""
        if self._env_exists:
            self.source_badge.setText("已加载 .env 配置")
            self.source_badge.setProperty("role", "badge-success")
        else:
            self.source_badge.setText("未创建 .env · 当前为模板默认值")
            self.source_badge.setProperty("role", "badge-warning")
            self.source_badge.setToolTip("点击“保存设置”后才会生成 .env 文件")
        refresh_style(self.source_badge)

    # ---------- 校验 ----------

    def _set_invalid(self, widget, flag=True):
        widget.setProperty("invalid", flag)
        refresh_style(widget)

    def _clear_invalid(self, widget):
        if widget.property("invalid"):
            self._set_invalid(widget, False)

    def _validate(self):
        """返回 (错误信息, 出错的控件)；无错返回 (None, None)"""
        if self.ollama_card.isChecked():
            if not self.ollama_url.text().strip():
                return ("请填写 Ollama Base URL", self.ollama_url)
            if not self.ollama_model.text().strip():
                return ("请填写 Ollama 模型名", self.ollama_model)
        else:
            if not self.deepseek_key.text().strip():
                return ("请填写 DeepSeek API Key", self.deepseek_key)
            if not self.deepseek_url.text().strip():
                return ("请填写 DeepSeek Base URL", self.deepseek_url)
            if not self.deepseek_model.currentText().strip():
                return ("请选择或填写 DeepSeek 模型", self.deepseek_model)
            if self.deepseek_key.text().strip() == PLACEHOLDER_KEY_HINT:
                return ("检测到占位符 Key（sk-xxxx…），请粘贴真实 API Key", self.deepseek_key)
        return (None, None)

    # ---------- 测试连接 ----------

    def _on_test(self):
        cfg = self._collect_config()
        is_ollama = cfg["LLM_PROVIDER"] == "ollama"
        if is_ollama and not cfg["OLLAMA_BASE_URL"]:
            self._show_test_result(False, "✗ 请先填写 Ollama Base URL")
            return
        if not is_ollama:
            if not cfg["DEEPSEEK_API_KEY"]:
                self._show_test_result(False, "✗ 请先填写 DeepSeek API Key")
                return
            if cfg["DEEPSEEK_API_KEY"] == PLACEHOLDER_KEY_HINT:
                self._show_test_result(False, "✗ 这是示例占位 Key，请粘贴真实 API Key")
                return

        # 启动后台测试
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中…")
        self.spinner.show()
        self._spin_idx = 0
        self._spin_timer.start(90)
        self.status_badge.setText("正在连接，请稍候…")
        self.status_badge.setProperty("role", "badge-neutral")
        refresh_style(self.status_badge)
        self._test_worker = TestWorker(cfg, self.dlg)
        self._test_worker.result.connect(self._on_test_done)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_worker.start()

    def _spin_tick(self):
        self.spinner.setText(self._spin_frames[self._spin_idx % len(self._spin_frames)])
        self._spin_idx += 1

    def _on_test_done(self, ok, msg):
        self._spin_timer.stop()
        self.spinner.hide()
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        self._show_test_result(ok, msg)

    def _show_test_result(self, ok, msg):
        self.status_badge.setText(msg)
        self.status_badge.setProperty("role", "badge-success" if ok else "badge-error")
        refresh_style(self.status_badge)
        self.toast.show_message(msg, "success" if ok else "error", duration=2200)

    # ---------- 保存 / 取消 ----------

    def _collect_config(self) -> Dict[str, str]:
        is_ollama = self.ollama_card.isChecked()
        return {
            "LLM_PROVIDER": "ollama" if is_ollama else "deepseek",
            "OLLAMA_BASE_URL": self.ollama_url.text().strip(),
            "OLLAMA_MODEL": self.ollama_model.text().strip(),
            "OLLAMA_AUTO_START": "true" if self.ollama_auto.isChecked() else "false",
            "DEEPSEEK_API_KEY": self.deepseek_key.text().strip(),
            "DEEPSEEK_BASE_URL": self.deepseek_url.text().strip(),
            "DEEPSEEK_MODEL": self.deepseek_model.currentText().strip(),
            "LLM_TEMPERATURE": str(self.temperature.value()),
            "LLM_CONCURRENCY": str(self.concurrency.value()),
            "ASR_BACKEND": self.asr_backend.currentText().strip(),
            "ASR_MODEL": self.asr_model.currentText().strip(),
            "ASR_DEVICE": self.asr_device.currentText().strip(),
            "ASR_USE_PUNC": "true" if self.asr_use_punc.isChecked() else "false",
        }

    def _on_save(self):
        if self._saving:
            return
        err, widget = self._validate()
        if err:
            self._set_invalid(widget)
            widget.setFocus()
            self.toast.show_message(err, "error", 3200)
            return

        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("保存中…")
        self.dlg.repaint()

        cfg = self._collect_config()
        try:
            save_env(cfg)
        except Exception as e:
            self._saving = False
            self.save_btn.setEnabled(True)
            self.save_btn.setText("保存设置")
            self.toast.show_message(f"保存失败：{e}", "error", 4000)
            return

        # 成功：按钮变绿打勾 + Toast，稍后自动关闭
        self._dirty = False
        self._dirty_tabs = {0: False, 1: False}
        self._env_exists = True
        self.save_btn.setProperty("role", "success")
        refresh_style(self.save_btn)
        self.save_btn.setText("✓ 已保存")
        self.dirty_label.setVisible(False)
        self.tabs.setTabText(0, "LLM 服务")
        self.tabs.setTabText(1, "语音识别")
        self.dlg.setWindowTitle("设置")
        self._update_source_badge()
        self.toast.show_message("✓ 配置已写入 .env，LLM 立即生效；ASR 改动需重启", "success", 2600)
        qt = self._qt
        qt['QTimer'].singleShot(900, self.dlg.accept)

    def _on_cancel(self):
        action = self.ask_discard()
        if action == "save":
            self._on_save()
        elif action == "discard":
            self.dlg.reject()

    def is_dirty(self) -> bool:
        return self._dirty and not self._saving

    def ask_discard(self) -> str:
        """返回 'save' / 'discard' / 'cancel'"""
        if not self._dirty or self._saving:
            return "discard"
        qt = self._qt
        box = qt['QMessageBox'](self.dlg)
        box.setWindowTitle("未保存的修改")
        box.setText("有未保存的修改，要如何处理？")
        box.setInformativeText("保存后写入 .env 文件；不保存则放弃全部改动。")
        save_btn = box.addButton("保存", qt['QMessageBox'].ButtonRole.AcceptRole)
        discard_btn = box.addButton("不保存", qt['QMessageBox'].ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("取消", qt['QMessageBox'].ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            return "save"
        if clicked is discard_btn:
            return "discard"
        return "cancel"


def open_settings(parent=None):
    """便捷入口：弹出设置对话框"""
    return SettingsDialog.create(parent).exec()
