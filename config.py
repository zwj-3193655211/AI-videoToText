"""
全局配置管理

从项目根目录的 .env 文件读取配置，提供简单的 get() 接口。
约定：
  - .env.example 入库当模板
  - .env 由用户创建，已在 .gitignore 中
  - 找不到 .env 时回退到 .env.example 的默认值，保证开箱即跑
"""

import os
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import dotenv_values
except ImportError:  # 容错：没装 dotenv 时回退到 os.environ
    dotenv_values = None


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


def _load_env() -> dict:
    """优先读 .env，读不到再读 .env.example，再读不到用空 dict"""
    if dotenv_values is None:
        return dict(os.environ)
    if ENV_FILE.exists():
        return dotenv_values(ENV_FILE)
    if ENV_EXAMPLE_FILE.exists():
        return dotenv_values(ENV_EXAMPLE_FILE)
    return {}


_ENV = _load_env()


def get(key: str, default: Any = None, cast=None) -> Any:
    """
    读取配置项
    - 优先从 .env 取
    - 缺失则回退到系统环境变量
    - 再缺失则用 default

    cast: 可选类型转换，如 int / bool / float
    """
    raw = _ENV.get(key)
    if raw is None:
        raw = os.environ.get(key, default)
    if raw is None:
        return None
    if cast is bool:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if cast is not None:
        try:
            return cast(raw)
        except (ValueError, TypeError):
            return default
    return raw


# ===== LLM 服务商 =====
LLM_PROVIDER = get("LLM_PROVIDER", "ollama")  # ollama / deepseek

# Ollama
OLLAMA_BASE_URL = get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_AUTO_START = get("OLLAMA_AUTO_START", "true", bool)

# DeepSeek
DEEPSEEK_API_KEY = get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# LLM 行为
LLM_TEMPERATURE = get("LLM_TEMPERATURE", "0.3", float)
LLM_CONCURRENCY = get("LLM_CONCURRENCY", "2", int)

# ASR
# 后端：funasr（基石，默认）/ faster-whisper（可选，需自行下载模型）
ASR_BACKEND = get("ASR_BACKEND", "funasr")
# 模型：offline（默认，Paraformer+VAD+标点）/ streaming（流式，预留实时识别）
ASR_MODEL = get("ASR_MODEL", "offline")
# 模型根目录（download.py 下载到的位置，默认项目根 ./model）
ASR_MODEL_DIR = get("ASR_MODEL_DIR", "") or None
ASR_DEVICE = get("ASR_DEVICE", "auto")  # auto / cuda / cpu
# 是否启用 CT-PUNC 标点模型（仅 offline 生效）
ASR_USE_PUNC = get("ASR_USE_PUNC", "true", bool)
# faster-whisper 计算精度（仅该后端使用）
ASR_COMPUTE_TYPE = get("ASR_COMPUTE_TYPE", "float16")


def get_active_llm_config() -> dict:
    """根据 LLM_PROVIDER 返回当前生效的 LLM 配置"""
    if LLM_PROVIDER == "deepseek":
        return {
            "provider": "deepseek",
            "base_url": DEEPSEEK_BASE_URL,
            "api_key": DEEPSEEK_API_KEY,
            "model": DEEPSEEK_MODEL,
            "temperature": LLM_TEMPERATURE,
        }
    return {
        "provider": "ollama",
        "base_url": OLLAMA_BASE_URL,
        "api_key": None,
        "model": OLLAMA_MODEL,
        "temperature": LLM_TEMPERATURE,
    }


if __name__ == "__main__":
    # 快速自检
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"ENV_FILE exists: {ENV_FILE.exists()}")
    print(f"LLM_PROVIDER: {LLM_PROVIDER}")
    print(f"ASR_MODEL: {ASR_MODEL}")
    print(f"Active LLM: {get_active_llm_config()}")
