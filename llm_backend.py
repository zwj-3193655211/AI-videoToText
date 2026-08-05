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


# ===== LLM 输出清洗（翻译/总结等生成结果的后处理） =====

# 模型"卡壳"话术：命中即视为无效输出（应触发重试）
_FALLBACK_PATTERNS = [
    r"需要更多的?上下文",
    r"请提供[^。\n]{0,20}(更多|完整|具体|原文|信息)",
    r"无法(翻译|完成|提供|确认|判断)",
    r"作为(一个|名)?(AI|人工智能|语言模型|助手|大模型)",
    r"(不确定|不清楚|无法确认|不太确定)",
    r"请(发送|输入|粘贴|提供)[^。\n]{0,15}(原文|内容|文本|资料)",
    r"翻译(失败|出错|不了|错误)",
    r"没有(提供|收到|看到)[^。\n]{0,15}(文本|内容|原文)",
    r"^(抱歉|对不起|不好意思|很遗憾)",
]

# markdown 行首标记（标题/引用/列表）
_MD_LINE_PREFIX = re.compile(r"^\s*(#{1,6}|>|[-*+])\s*", re.MULTILINE)

# 预编译卡壳话术（非捕获组包裹，避免 pattern 内 | 干扰整体匹配）
_FALLBACK_RE = re.compile("(?:" + "|".join(_FALLBACK_PATTERNS) + ")")


# 加粗标记：**内容** → 内容（跨行也匹配）
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# 独立的斜体标记：*内容*（前后不是星号，避免和加粗重叠）
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")


def clean_llm_output(text: Optional[str]) -> Optional[str]:
    """
    清洗 LLM 生成结果（翻译/总结），返回清洗后的纯文本；无效则返回 None。

    处理：
    1. 去除 <think> 与 HTML 标签
    2. 去除 markdown 加粗/斜体标记（**内容** → 内容）与反引号
    3. 去除行首 markdown 标记（#、>、列表符号）
    4. 检测模型"卡壳"话术（如：**需要更多上下文**、请提供原文…），
       命中即视为该次输出无效（返回 None，由上层触发重试）
    """
    if not text:
        return None
    # 1. 去 think / HTML 标签
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    # 2. 检测卡壳话术（在去 markdown 前，** 包裹的关键词也在命中范围）
    if _FALLBACK_RE.search(text):
        return None
    # 3. 去 markdown 强调标记（**粗** 与 *斜* → 保留内容去星号）
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = re.sub(r"`", "", text)
    # 4. 去行首 markdown 标记
    text = _MD_LINE_PREFIX.sub("", text)
    text = text.strip()
    return text or None


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str                # ollama / deepseek
    base_url: str
    api_key: Optional[str]       # ollama 不需要
    model: str
    temperature: float = 0.3
    max_tokens: int = 4096       # 单次最大输出 token
    timeout: int = 600           # 单次请求超时（秒）


class LLMBackend(ABC):
    """LLM 后端抽象基类"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.last_error: Optional[Exception] = None  # 最近一次请求的错误详情

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
        if self.config.provider == "deepseek" and not self.config.api_key:
            return False, "✗ 未配置 DeepSeek API Key"
        if self.config.provider == "deepseek" and self.config.api_key.startswith("sk-xxxx"):
            return False, "✗ 当前是示例占位 Key（sk-xxxx…），请粘贴真实 API Key"
        try:
            t0 = time.time()
            resp = self.chat("回复 OK", temperature=0.0)
            elapsed = time.time() - t0
            if resp and len(resp.strip()) > 0:
                return True, f"✓ 连接正常 · {self.config.model}（{elapsed:.1f}s）"
            detail = f"：{self.last_error}" if self.last_error else ""
            if self.config.provider == "ollama":
                return False, f"✗ Ollama 未响应，请确认服务已启动{detail}"
            return False, f"✗ API 返回为空，请检查 Key / Base URL / 模型名{detail}"
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
        max_tokens: Optional[int] = None,
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
                        "num_predict": max_tokens if max_tokens is not None else self.config.max_tokens,
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
            self.last_error = e
            return None


class DeepSeekBackend(LLMBackend):
    """DeepSeek 云端 API 后端（OpenAI 兼容）"""

    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
                    "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
                    "stream": False,
                },
                timeout=self.config.timeout,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self.last_error = e
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
