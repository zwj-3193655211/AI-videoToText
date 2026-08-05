"""
语音识别（ASR）后端抽象与实现

- ASRBackend: 抽象基类
- FasterWhisperBackend: faster-whisper 实现（多语种首选）

设计原则：
  - 不依赖 UI，可在子线程运行
  - 长任务通过 progress_callback 回调进度（callback 必须线程安全，只用来发信号）
  - 转录结果用 dataclass 封装，方便序列化
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import config


@dataclass
class Segment:
    """单段识别结果"""
    start: float
    end: float
    text: str


@dataclass
class TranscribeResult:
    """完整识别结果"""
    text: str                       # 全文（拼接后）
    segments: List[Segment] = field(default_factory=list)
    language: str = ""              # 检测/指定的语言代码
    language_probability: float = 0.0
    duration: float = 0.0           # 音频总时长（秒）


# 进度回调签名：callback(current_seconds, total_seconds, message)
ProgressCallback = Optional[Callable[[float, float, str], None]]


class ASRBackend(ABC):
    """ASR 后端抽象基类"""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        progress_callback: ProgressCallback = None,
    ) -> TranscribeResult:
        """
        转录音频文件
        :param audio_path: 音频文件路径
        :param language: 强制指定语言（None=自动检测）
        :param beam_size: beam search 宽度（越大越准越慢，1-10）
        :param vad_filter: 是否用 VAD 过滤静音段
        :param progress_callback: 进度回调
        """
        raise NotImplementedError


class FasterWhisperBackend(ASRBackend):
    """
    faster-whisper (CTranslate2 优化版 Whisper) 后端

    优势：
      - 速度比原版 Whisper 快 4-5 倍
      - 内存占用低
      - 支持 CPU/CUDA，自动调度
      - 99 种语言

    模型选择（按推荐度排序）：
      - Systran/faster-distil-whisper-large-v3  (推荐, ~750MB, 速度+准确度平衡)
      - Systran/faster-whisper-large-v3          (~1.5GB, 准确度最高)
      - Systran/faster-whisper-medium            (~1.5GB, 折中)
      - Systran/faster-whisper-small             (~460MB, 速度快)
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        download_root: Optional[str] = None,
    ):
        # 延迟导入：避免主程序不切到这个后端时白白加载 ctranslate2
        from faster_whisper import WhisperModel

        model_name = model_name or config.ASR_MODEL
        device = device or config.ASR_DEVICE
        compute_type = compute_type or config.ASR_COMPUTE_TYPE

        # device=auto 时自动判断
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # CPU 不支持 float16，自动降级
        if device == "cpu" and compute_type == "float16":
            compute_type = "int8"

        self._device = device
        self._compute_type = compute_type
        self._model_name = model_name

        # 解析模型路径：本地不存在就尝试从 ModelScope 拉（国内源快）
        resolved = self._resolve_model_path(model_name, download_root or config.ASR_MODEL_DIR)

        self.model = WhisperModel(
            resolved,
            device=device,
            compute_type=compute_type,
        )

    @staticmethod
    def _resolve_model_path(model_name: str, download_root: Optional[str]) -> str:
        """
        解析模型路径：
          1. 如果是本地路径且存在，直接用
          2. 否则先看 HF 缓存里有没有
          3. 都没有就通过 ModelScope 拉（国内源快）
        """
        # 1. 本地路径直接存在
        if os.path.isdir(model_name) and os.path.exists(os.path.join(model_name, "model.bin")):
            return model_name

        # 2. 看用户指定的 download_root
        if download_root:
            candidate = os.path.join(download_root, model_name)
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "model.bin")):
                return candidate

        # 3. 通过 ModelScope 拉（速度快，国内源）
        print(f"[ASR] 本地未找到模型 {model_name}，尝试从 ModelScope 拉取...")
        try:
            from modelscope import snapshot_download
            cache = download_root or "model/whisper"
            local_dir = snapshot_download(
                model_name,
                cache_dir=cache,
            )
            # snapshot_download 返回的是 snapshots 目录，需要取里面的 model.bin
            model_bin = os.path.join(local_dir, "model.bin")
            if os.path.exists(model_bin):
                print(f"[ASR] 模型已就绪: {local_dir}")
                return local_dir
        except Exception as e:
            print(f"[ASR] ModelScope 拉取失败: {e}")

        # 4. fallback：让 faster-whisper 自己走 HF 拉（可能很慢/失败）
        print(f"[ASR] 回退到 faster-whisper 默认下载流程")
        return model_name

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        progress_callback: ProgressCallback = None,
    ) -> TranscribeResult:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        # faster-whisper 内部是分段迭代器，segment 生成时即可回调进度
        segments_iter, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters={
                "min_silence_duration_ms": 500,  # 静音超过 500ms 切段
            } if vad_filter else None,
            condition_on_previous_text=True,
        )

        if progress_callback:
            progress_callback(0.0, info.duration, f"开始识别（语言={info.language}）")

        segments: List[Segment] = []
        text_parts: List[str] = []
        for seg in segments_iter:
            segments.append(Segment(start=seg.start, end=seg.end, text=seg.text))
            text_parts.append(seg.text)
            if progress_callback:
                progress_callback(seg.end, info.duration, f"[{seg.start:.1f}s-{seg.end:.1f}s]")

        full_text = "".join(text_parts).strip()
        # 去除明显噪声
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        if progress_callback:
            progress_callback(
                info.duration, info.duration,
                f"识别完成，共 {len(segments)} 段，{len(full_text)} 字"
            )

        return TranscribeResult(
            text=full_text,
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
        )


def get_default_backend() -> ASRBackend:
    """工厂方法：按 config 选默认后端（目前只有 faster-whisper）"""
    return FasterWhisperBackend()


if __name__ == "__main__":
    # 简单自检
    import sys
    print("FasterWhisperBackend 配置:")
    print(f"  model: {config.ASR_MODEL}")
    print(f"  device: {config.ASR_DEVICE}")
    print(f"  compute_type: {config.ASR_COMPUTE_TYPE}")
    if len(sys.argv) > 1:
        backend = FasterWhisperBackend()
        result = backend.transcribe(sys.argv[1], progress_callback=lambda c, t, m: print(f"[{c:.1f}/{t:.1f}] {m}"))
        print("\n=== 识别结果 ===")
        print(f"语言: {result.language} ({result.language_probability:.2%})")
        print(f"时长: {result.duration:.1f}s")
        print(f"文本: {result.text[:200]}{'...' if len(result.text) > 200 else ''}")
