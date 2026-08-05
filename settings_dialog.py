"""
设置对话框 + .env 读写

- SettingsDialog: PySide6 设置 UI
- load_env() / save_env(): 读写 .env 文件
"""

import os
from pathlib import Path
from typing import Dict

import config

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"


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


# ====== PySide6 设置对话框 ======

def _get_qt():
    """延迟导入 Qt"""
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
        QLineEdit, QComboBox, QPushButton, QLabel, QCheckBox, QDoubleSpinBox,
        QMessageBox, QGroupBox, QSpinBox,
    )
    from PySide6.QtCore import Qt
    return {
        'QDialog': QDialog, 'QVBoxLayout': QVBoxLayout, 'QHBoxLayout': QHBoxLayout,
        'QFormLayout': QFormLayout, 'QTabWidget': QTabWidget, 'QWidget': QWidget,
        'QLineEdit': QLineEdit, 'QComboBox': QComboBox, 'QPushButton': QPushButton,
        'QLabel': QLabel, 'QCheckBox': QCheckBox, 'QDoubleSpinBox': QDoubleSpinBox,
        'QMessageBox': QMessageBox, 'QGroupBox': QGroupBox, 'QSpinBox': QSpinBox,
        'Qt': Qt,
    }


class SettingsDialog:
    """工厂：创建并返回 QDialog 实例（避免模块顶层 import Qt）"""
    @staticmethod
    def create(parent=None) -> "QDialog":
        impl = _SettingsDialogImpl(parent)
        return impl.dlg  # 返回真正的 QDialog 实例


class _SettingsDialogImpl:
    """实际实现（构造并填充 QDialog）"""

    def __init__(self, parent=None):
        qt = _get_qt()
        self.dlg = qt['QDialog'](parent)
        self.dlg.setWindowTitle("设置")
        self.dlg.setMinimumSize(500, 400)

        self._qt = qt
        self._current = load_env()
        if not self._current:
            # 没 .env 就从 .env.example 读默认值
            example = PROJECT_ROOT / ".env.example"
            if example.exists() and dotenv_values is not None:
                self._current = dict(dotenv_values(example))

        self._build_ui()

    def _build_ui(self):
        qt = self._qt
        layout = qt['QVBoxLayout'](self.dlg)
        tabs = qt['QTabWidget']()
        layout.addWidget(tabs)

        # ---- LLM 标签页 ----
        llm_tab = qt['QWidget']()
        llm_layout = qt['QVBoxLayout'](llm_tab)

        # 服务商选择
        provider_group = qt['QGroupBox']("LLM 服务商")
        pg_layout = qt['QHBoxLayout'](provider_group)
        self.provider_combo = qt['QComboBox']()
        self.provider_combo.addItems(["ollama (本地)", "deepseek (云端 API)"])
        current_provider = self._current.get("LLM_PROVIDER", "ollama")
        if current_provider == "deepseek":
            self.provider_combo.setCurrentIndex(1)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        pg_layout.addWidget(qt['QLabel']("当前:"))
        pg_layout.addWidget(self.provider_combo)
        pg_layout.addStretch()
        llm_layout.addWidget(provider_group)

        # Ollama 配置
        self.ollama_group = qt['QGroupBox']("Ollama 配置")
        og_layout = qt['QFormLayout'](self.ollama_group)
        self.ollama_url = qt['QLineEdit'](self._current.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        self.ollama_model = qt['QLineEdit'](self._current.get("OLLAMA_MODEL", "qwen2.5:7b"))
        self.ollama_auto = qt['QCheckBox']("启动时自动拉起 ollama serve")
        self.ollama_auto.setChecked(self._current.get("OLLAMA_AUTO_START", "true").lower() in ("true", "1", "yes"))
        og_layout.addRow("Base URL:", self.ollama_url)
        og_layout.addRow("模型:", self.ollama_model)
        og_layout.addRow("", self.ollama_auto)
        llm_layout.addWidget(self.ollama_group)

        # DeepSeek 配置
        self.deepseek_group = qt['QGroupBox']("DeepSeek 配置")
        dg_layout = qt['QFormLayout'](self.deepseek_group)
        self.deepseek_key = qt['QLineEdit'](self._current.get("DEEPSEEK_API_KEY", ""))
        self.deepseek_key.setEchoMode(qt['QLineEdit'].EchoMode.Password)
        self.deepseek_key.setPlaceholderText("sk-...")
        self.deepseek_url = qt['QLineEdit'](self._current.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
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
        dg_layout.addRow("API Key:", self.deepseek_key)
        dg_layout.addRow("Base URL:", self.deepseek_url)
        dg_layout.addRow("模型:", self.deepseek_model)
        llm_layout.addWidget(self.deepseek_group)

        # 行为参数
        behavior_group = qt['QGroupBox']("行为")
        bg_layout = qt['QFormLayout'](behavior_group)
        self.temperature = qt['QDoubleSpinBox']()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(float(self._current.get("LLM_TEMPERATURE", "0.3")))
        self.concurrency = qt['QSpinBox']()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(int(self._current.get("LLM_CONCURRENCY", "2")))
        bg_layout.addRow("温度 (0-2):", self.temperature)
        bg_layout.addRow("翻译并发 (1-8):", self.concurrency)
        llm_layout.addWidget(behavior_group)

        # 测试连接 + 提示
        btn_layout = qt['QHBoxLayout']()
        self.test_btn = qt['QPushButton']("测试连接")
        self.test_btn.clicked.connect(self._on_test)
        self.status_label = qt['QLabel']("")
        btn_layout.addWidget(self.test_btn)
        btn_layout.addWidget(self.status_label, 1)
        llm_layout.addLayout(btn_layout)

        llm_layout.addStretch()
        tabs.addTab(llm_tab, "LLM 服务")

        # ---- ASR 标签页 ----
        asr_tab = qt['QWidget']()
        asr_layout = qt['QVBoxLayout'](asr_tab)
        asr_group = qt['QGroupBox']("语音识别 (FunASR Paraformer)")
        ag_layout = qt['QFormLayout'](asr_group)
        self.asr_backend = qt['QComboBox']()
        self.asr_backend.addItems(["funasr", "faster-whisper"])
        self.asr_backend.setCurrentText(self._current.get("ASR_BACKEND", "funasr"))
        self.asr_model = qt['QComboBox']()
        self.asr_model.addItems(["offline", "streaming"])
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
            "提示：\n"
            "• 基石模型由 download.py 下载到 model/ 目录（已存在自动跳过）\n"
            "• offline = Paraformer + VAD + 标点（默认，中文高精度）\n"
            "• streaming = 流式 Paraformer（预留，供实时识别）\n"
            "• faster-whisper 为可选后端，需自行下载模型"
        )
        asr_hint.setStyleSheet("color: gray; font-size: 11px;")
        asr_hint.setWordWrap(True)
        asr_layout.addWidget(asr_hint)
        asr_layout.addStretch()
        tabs.addTab(asr_tab, "语音识别")

        # ---- 底部按钮 ----
        bottom = qt['QHBoxLayout']()
        bottom.addStretch()
        self.save_btn = qt['QPushButton']("保存")
        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn = qt['QPushButton']("取消")
        self.cancel_btn.clicked.connect(self.dlg.reject)
        bottom.addWidget(self.save_btn)
        bottom.addWidget(self.cancel_btn)
        layout.addLayout(bottom)

        self._on_provider_changed()

    def _on_provider_changed(self):
        is_ollama = self.provider_combo.currentIndex() == 0
        self.ollama_group.setEnabled(is_ollama)
        self.deepseek_group.setEnabled(not is_ollama)

    def _on_test(self):
        # 临时构造配置测试
        cfg = self._collect_config()
        from llm_backend import LLMConfig, OllamaBackend, DeepSeekBackend
        llm_cfg = LLMConfig(
            provider=cfg["LLM_PROVIDER"],
            base_url=cfg["OLLAMA_BASE_URL"] if cfg["LLM_PROVIDER"] == "ollama" else cfg["DEEPSEEK_BASE_URL"],
            api_key=cfg.get("DEEPSEEK_API_KEY") if cfg["LLM_PROVIDER"] == "deepseek" else None,
            model=cfg["OLLAMA_MODEL"] if cfg["LLM_PROVIDER"] == "ollama" else cfg["DEEPSEEK_MODEL"],
            temperature=cfg["LLM_TEMPERATURE"],
        )
        backend = OllamaBackend(llm_cfg, auto_start=False) if cfg["LLM_PROVIDER"] == "ollama" else DeepSeekBackend(llm_cfg)
        self.status_label.setText("测试中...")
        self.dlg.repaint()
        ok, msg = backend.test_connection()
        self.status_label.setText(msg)
        color = "green" if ok else "red"
        self.status_label.setStyleSheet(f"color: {color};")

    def _collect_config(self) -> Dict[str, str]:
        is_ollama = self.provider_combo.currentIndex() == 0
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
        cfg = self._collect_config()
        try:
            save_env(cfg)
            QMessageBox = self._qt['QMessageBox']
            QMessageBox.information(self.dlg, "已保存", "配置已写入 .env，下次启动生效。")
            self.dlg.accept()
        except Exception as e:
            QMessageBox = self._qt['QMessageBox']
            QMessageBox.critical(self.dlg, "保存失败", str(e))

    def show(self):
        return self.dlg.exec()


def open_settings(parent=None):
    """便捷入口：弹出设置对话框"""
    return SettingsDialog.create(parent).exec()
