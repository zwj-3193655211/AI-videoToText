"""
LLM 后端抽象

- LLMBackend: 抽象基类
- OllamaBackend: 本地 Ollama
- DeepSeekBackend: DeepSeek 云端 API（OpenAI 兼容）
- get_backend(config): 工厂方法
"""

from __future__ import annotations

import os
import re
import time
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

import requests


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str                # ollama / deepseek
    base_url: str
    api_key: Optional[str]       # ollama 不需要
    model: str
    temperature: float = 0.3
    timeout: int = 600           # 单次请求超时（秒）


class LLMBackend(ABC):
    """LLM 后端抽象基类"""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        """
        同步调用 LLM，返回完整响应
        :return: 响应文本，失败返回 None
        """
        raise NotImplementedError

    def test_connection(self) -> Tuple[bool, str]:
        """
        测试连接是否可用
        :return: (success, message)
        """
        try:
            resp = self.chat("回复 OK", temperature=0.0)
            if resp and len(resp) > 0:
                return True, f"✓ {self.config.provider}/{self.config.model} 连接正常"
            return False, "✗ 返回为空"
        except Exception as e:
            return False, f"✗ {type(e).__name__}: {e}"

    def __repr__(self):
        return f"<{self.__class__.__name__} provider={self.config.provider} model={self.config.model}>"


class OllamaBackend(LLMBackend):
    """本地 Ollama 后端"""

    def __init__(self, config: LLMConfig, auto_start: bool = True):
        super().__init__(config)
        if auto_start:
            self._ensure_running()

    def _ensure_running(self, wait_seconds: int = 30):
        """确保 Ollama 服务在跑，没跑就启动"""
        # 检查
        try:
            r = requests.get(f"{self.config.base_url}/api/tags", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        # 启动
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except FileNotFoundError:
            raise RuntimeError("找不到 ollama 命令，请先安装 Ollama: https://ollama.com")

        # 等待
        for _ in range(wait_seconds):
            try:
                r = requests.get(f"{self.config.base_url}/api/tags", timeout=1)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError(f"Ollama 启动超时（{wait_seconds}s）")

    def list_models(self) -> list:
        """列出本地可用的模型"""
        try:
            r = requests.get(f"{self.config.base_url}/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            r = requests.post(
                f"{self.config.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.config.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature if temperature is not None else self.config.temperature,
                    },
                },
                timeout=self.config.timeout,
            )
            r.raise_for_status()
            text = r.json()["message"]["content"].strip()
            # 移除 ollama/qwen 的 <think> 标签
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            return text
        except Exception as e:
            return None


class DeepSeekBackend(LLMBackend):
    """DeepSeek 云端 API 后端（OpenAI 兼容）"""

    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        if not self.config.api_key:
            return None  # 配置缺失直接返回 None，不抛错

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            r = requests.post(
                f"{self.config.base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model,
                    "messages": messages,
                    "temperature": temperature if temperature is not None else self.config.temperature,
                    "stream": False,
                },
                timeout=self.config.timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return None


def make_config_from_env() -> LLMConfig:
    """从 config（基于 .env）构造 LLMConfig"""
    import config
    if config.LLM_PROVIDER == "deepseek":
        return LLMConfig(
            provider="deepseek",
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=config.DEEPSEEK_API_KEY,
            model=config.DEEPSEEK_MODEL,
            temperature=config.LLM_TEMPERATURE,
        )
    return LLMConfig(
        provider="ollama",
        base_url=config.OLLAMA_BASE_URL,
        api_key=None,
        model=config.OLLAMA_MODEL,
        temperature=config.LLM_TEMPERATURE,
    )


def get_backend(auto_start_ollama: bool = True) -> LLMBackend:
    """工厂方法：按 config 选 backend"""
    cfg = make_config_from_env()
    if cfg.provider == "deepseek":
        return DeepSeekBackend(cfg)
    return OllamaBackend(cfg, auto_start=auto_start_ollama)


if __name__ == "__main__":
    # 简单自检
    b = get_backend(auto_start_ollama=False)
    print(f"Backend: {b}")
    ok, msg = b.test_connection()
    print(f"Test: {msg}")
