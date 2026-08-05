"""
语音识别（ASR）后端抽象与实现

- ASRBackend: 抽象基类
- FunASRBackend: FunASR / Paraformer 实现（项目基石，唯一后端）
  - paraformer-offline + FSMN-VAD + CT-PUNC（中文 ASR，带标点，实时/离线通用）
- FasterWhisperBackend: faster-whisper 实现（可选，需自行下载 whisper 模型）

设计原则：
  - 不依赖 UI，可在子线程运行
  - 长任务通过 progress_callback 回调进度（callback 必须线程安全，只用来发信号）
  - 转录结果用 dataclass 封装，方便序列化
"""

from __future__ import annotations

import os
# 必须在 import torch/ctranslate2 之前设置，否则 conda + faster-whisper 会有 OpenMP 重复加载问题
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
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


def _probe_duration(audio_path: str) -> float:
    """用 ffprobe 探测音频时长（秒），失败返回 0"""
    try:
        import json
        import subprocess
        p = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30,
        )
        return float(json.loads(p.stdout)["format"]["duration"])
    except Exception:
        return 0.0


class FunASRBackend(ASRBackend):
    """
    FunASR / Paraformer 后端（项目基石）

    - offline（唯一）: Paraformer-Large + FSMN-VAD + CT-PUNC
        - 中文 ASR 高精度，输出带标点
        - 模型位置由 config.ASR_MODEL_DIR 指定，默认 ./model
        - VAD（语音活动检测/切句）与 PUNC（标点恢复）内置，实时与离线场景通用

    模型路径结构（download.py 下载的基石）:
      model/vad/  model/punc/  model/paraformer/paraformer-offline/
    """

    # 默认模型目录结构（相对 ASR_MODEL_DIR）
    _MODEL_REL = {
        "vad": Path("vad") / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "punc": Path("punc") / "punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
        "offline": Path("paraformer") / "paraformer-offline" / "iic"
                   / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        use_punc: Optional[bool] = None,
        model_root: Optional[str] = None,
        disable_update: bool = True,
    ):
        # 延迟导入：避免不切换后端时白白加载 funasr
        from funasr import AutoModel

        model_name = model_name or config.ASR_MODEL          # 兼容旧值，仅 offline 生效
        device = device or config.ASR_DEVICE                 # auto / cuda / cpu
        use_punc = config.ASR_USE_PUNC if use_punc is None else use_punc
        model_root = Path(model_root or config.ASR_MODEL_DIR or "model")

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # 解析模型路径
        offline_dir = model_root / self._MODEL_REL["offline"]
        vad_dir = model_root / self._MODEL_REL["vad"]
        punc_dir = model_root / self._MODEL_REL["punc"]

        self._device = device
        self._model_name = "offline"
        self._use_punc = use_punc

        # offline（唯一后端）：VAD + 可选 PUNC
        assert offline_dir.exists(), f"离线模型缺失: {offline_dir}（请运行 python download.py）"
        assert (vad_dir / "model.pt").exists(), f"VAD 模型缺失: {vad_dir}（请运行 python download.py）"
        print(f"[ASR] 加载 Paraformer-Offline + FSMN-VAD" + (" + CT-PUNC" if use_punc else "") + f" @ {device}")
        kwargs = dict(
            model=str(offline_dir),
            vad_model=str(vad_dir),
            vad_kwargs={"max_single_segment_time": 30000},
            device=device,
            disable_update=disable_update,
        )
        if use_punc:
            assert (punc_dir / "model.pt").exists(), f"标点模型缺失: {punc_dir}（请运行 python download.py）"
            kwargs["punc_model"] = str(punc_dir)
        self.model = AutoModel(**kwargs)
        self._gen_kwargs = dict(batch_size_s=60)

    @property
    def device(self) -> str:
        return self._device

    @property
    def model_name(self) -> str:
        return self._model_name

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

        duration = _probe_duration(audio_path)
        if progress_callback:
            progress_callback(0.0, duration, "开始识别（FunASR Paraformer）")

        gen_kwargs = dict(self._gen_kwargs)
        gen_kwargs["input"] = audio_path
        gen_kwargs["cache"] = {}
        # offline 带 VAD 时输出含标点；语言自动
        if language:
            gen_kwargs["language"] = language
        # 字级时间戳（Paraformer LFR-6，帧索引，每帧=60ms）
        gen_kwargs["pred_timestamp"] = True

        result = self.model.generate(**gen_kwargs)
        if progress_callback:
            progress_callback(duration, duration, "解码完成，整理结果...")

        raw = ""
        if result and isinstance(result, list):
            raw = result[0].get("text", "")

        # 去 SenseVoice 类特殊标签（Paraformer 一般没有，兜底处理）
        full_text = re.sub(r"<\|[^|]+\|>", "", raw).strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()

        # FunASR 返回字级时间戳（offline 时）：[start_ms, end_ms]，单位毫秒（实测 1ms/帧）
        # 按标点切句，把字级时间戳聚合成句级 Segment
        segments: List[Segment] = []
        ts = result[0].get("timestamp") if result and isinstance(result, list) else None
        if ts and isinstance(ts, list) and len(ts) > 1 and all(
            isinstance(x, (list, tuple)) and len(x) == 2 for x in ts
        ):
            try:
                # 按标点切句（含末尾标点）
                sentence_parts = re.split(r"(?<=[。？！；.!?；])", full_text)
                sentence_parts = [s for s in sentence_parts if s.strip()]
                # 时间戳逐字对应文本；英文单词/标点会多占位置，用字符比例对齐
                # 简单稳妥方案：按句子字数占比切分 ts 索引
                n_chars = max(len(full_text), 1)
                n_ts = len(ts)
                char_cursor = 0
                ts_cursor = 0
                for sent in sentence_parts:
                    n = len(sent)
                    if n <= 0 or char_cursor >= n_chars:
                        continue
                    end_char = min(char_cursor + n, n_chars)
                    # 估算该句在 ts 中的起止索引
                    i0 = int(ts_cursor + (char_cursor / n_chars) * (n_ts - ts_cursor))
                    i1 = int(ts_cursor + (end_char / n_chars) * (n_ts - ts_cursor))
                    i1 = min(max(i1, i0 + 1), n_ts - 1)
                    seg = Segment(
                        start=float(ts[i0][0]) / 1000.0,
                        end=float(ts[i1][1]) / 1000.0,
                        text=sent,
                    )
                    segments.append(seg)
                    char_cursor = end_char
            except Exception:
                segments = []

        if progress_callback:
            progress_callback(duration, duration,
                              f"识别完成，共 {len(segments) or 1} 段，{len(full_text)} 字")

        return TranscribeResult(
            text=full_text,
            segments=segments,
            language="zh",
            language_probability=1.0,
            duration=duration,
        )


class FasterWhisperBackend(ASRBackend):
    """
    faster-whisper (CTranslate2 优化版 Whisper) 后端【可选，非默认】

    注意：项目基石已切换到 FunASR Paraformer，whisper 模型不再由 download.py 管理。
    如需使用本后端，请自行下载对应模型（Systran/faster-whisper-*）到 ASR_MODEL_DIR。

    模型选择（按推荐度排序）：
      - Systran/faster-whisper-medium            (~1.5GB, 折中)
      - Systran/faster-whisper-small             (~460MB, 速度快)
      - Systran/faster-whisper-large-v3          (~1.5GB, 准确度最高)
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
    """工厂方法：按 config.ASR_BACKEND 选默认后端"""
    backend_name = config.ASR_BACKEND
    if backend_name == "funasr":
        return FunASRBackend()
    return FasterWhisperBackend()


if __name__ == "__main__":
    # 简单自检
    import sys
    print("ASR 后端配置:")
    print(f"  backend: {config.ASR_BACKEND}")
    print(f"  model: {config.ASR_MODEL}")
    print(f"  device: {config.ASR_DEVICE}")
    if len(sys.argv) > 1:
        backend = get_default_backend()
        result = backend.transcribe(sys.argv[1], progress_callback=lambda c, t, m: print(f"[{c:.1f}/{t:.1f}] {m}"))
        print("\n=== 识别结果 ===")
        print(f"语言: {result.language} ({result.language_probability:.2%})")
        print(f"时长: {result.duration:.1f}s")
        print(f"段数: {len(result.segments)}")
        print(f"文本: {result.text[:200]}{'...' if len(result.text) > 200 else ''}")
