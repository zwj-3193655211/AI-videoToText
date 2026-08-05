"""
同音频三模型对比：SenseVoice (老) / faster-whisper-small / faster-whisper-medium

输入：output/comparison/*.m4a
输出：
  output/comparison/result_sensevoice.txt
  output/comparison/result_fw_small.txt
  output/comparison/result_fw_medium.txt
  output/comparison/result_compare.md
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

# Windows 编码 fix
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import json
import re
import glob
from pathlib import Path

ROOT = Path(r"D:\Desktop_Archive\AI-VedioToText")
CMP = ROOT / "output" / "comparison"
CMP.mkdir(parents=True, exist_ok=True)


def find_audio():
    # 优先用 clip_3min.m4a（裁过的，CPU SenseVoice 跑得动）
    clip = CMP / "clip_3min.m4a"
    if clip.exists():
        return clip
    audios = [p for p in CMP.glob("*.m4a")] + [p for p in CMP.glob("*.wav")]
    if not audios:
        raise SystemExit("comparison 目录里没找到音频")
    return audios[0]


def run_sensevoice(audio_path: Path) -> dict:
    """
    老 ASR：FunASR SenseVoiceSmall + FSMN-VAD
    注意：PyTorch 2.5.1 不支持 sm_120（Blackwell），强制 CPU 跑
    """
    from funasr import AutoModel
    import torch

    model_dir = ROOT / "model" / "sensevoice" / "iic" / "SenseVoiceSmall"
    vad_dir = ROOT / "model" / "vad" / "iic" / "speech_fsmn_vad_zh-cn-16k-common-pytorch"

    print(f"\n[1/3] SenseVoice (老 + VAD) ...")
    print(f"  model: {model_dir}")
    print(f"  vad:   {vad_dir}")
    print(f"  device: CPU (PyTorch 2.5.1 + RTX 5060 sm_120 不兼容)")

    t0 = time.time()
    model = AutoModel(
        model=str(model_dir),
        vad_model=str(vad_dir),
        vad_kwargs={"max_single_segment_time": 30000},
        device="cpu",  # sm_120 兼容性问题，强制 CPU
    )
    result = model.generate(
        input=str(audio_path),
        cache={},
        language="auto",
        use_itn=True,
        batch_size_s=60,
    )
    elapsed = time.time() - t0

    # SenseVoice 输出格式: [{key, text, timestamp, ...}]
    text = ""
    if result and isinstance(result, list):
        text = result[0].get("text", "")

    # SenseVoice 带特殊 tag：<|zh|><|NEUTRAL|><|Speech|><|withitn|> ...
    # 去掉这些 tag，保留纯文本
    text_clean = re.sub(r"<\|[^|]+\|>", "", text).strip()

    out = CMP / "result_sensevoice.txt"
    out.write_text(
        f"# 模型: SenseVoiceSmall (老 + FSMN-VAD)\n"
        f"# 耗时: {elapsed:.1f}s\n"
        f"# 设备: CPU\n"
        f"# 原始输出 (带 SenseVoice 标签):\n{text}\n\n"
        f"# 清洗后 (去除 <|lang|><|emo|><|event|> 等标签):\n{text_clean}\n",
        encoding="utf-8"
    )
    print(f"  [OK] {elapsed:.1f}s, {len(text_clean)} 字 -> {out.name}")
    return {"model": "SenseVoiceSmall (老)", "elapsed": elapsed, "chars": len(text_clean), "text": text_clean, "device": "CPU"}


def run_faster_whisper(audio_path: Path, model_name: str, label: str) -> dict:
    """faster-whisper 对比"""
    import torch
    from faster_whisper import WhisperModel

    # 直接走本地路径，避免重新下载
    local_model_dir = ROOT / "model" / "whisper" / "Systran" / model_name
    if not (local_model_dir / "model.bin").exists():
        raise FileNotFoundError(f"模型未找到: {local_model_dir}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    print(f"\n[FW-{label}] {model_name} ...")
    print(f"  device: {device}, compute: {compute_type}")

    t0 = time.time()
    model = WhisperModel(
        str(local_model_dir),
        device=device,
        compute_type=compute_type,
    )
    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )
    segments = list(segments_iter)
    elapsed = time.time() - t0

    text = "".join(seg.text for seg in segments).strip()
    text_simp = text  # 默认已经是简体

    out = CMP / f"result_fw_{label}.txt"
    seg_lines = "\n".join(
        f"[{s.start:7.2f}s - {s.end:7.2f}s] {s.text.strip()}"
        for s in segments
    )
    out.write_text(
        f"# 模型: faster-whisper-{label}\n"
        f"# 耗时: {elapsed:.1f}s\n"
        f"# 设备: {device}, compute: {compute_type}\n"
        f"# 语言: {info.language} ({info.language_probability:.2%})\n"
        f"# 段数: {len(segments)}\n\n"
        f"# 全文:\n{text_simp}\n\n"
        f"# 段级时间戳:\n{seg_lines}\n",
        encoding="utf-8"
    )
    print(f"  [OK] {elapsed:.1f}s, {len(text_simp)} 字, {len(segments)} 段 -> {out.name}")
    return {
        "model": f"faster-whisper-{label}",
        "elapsed": elapsed,
        "chars": len(text_simp),
        "segments": len(segments),
        "lang": f"{info.language} ({info.language_probability:.2%})",
        "text": text_simp,
        "device": f"{device}/{compute_type}",
    }


def write_compare_md(results: list, audio: Path, audio_mb: float):
    """生成对比总览"""
    md = CMP / "result_compare.md"
    lines = [
        f"# 同音频三模型对比",
        f"",
        f"- 音频：`{audio.name}`",
        f"- 大小：{audio_mb:.2f} MB",
        f"- 设备：GPU=RTX 5060 Laptop (sm_120) / PyTorch 2.5.1+cu121",
        f"- 说明：SenseVoice 因 PyTorch 2.5.1 不支持 sm_120 强制走 CPU；faster-whisper 用 ctranslate2 不走 PyTorch，GPU 正常",
        f"",
        f"## 性能对比",
        f"",
        f"| 模型 | 设备 | 耗时 | 字数 | 备注 |",
        f"|---|---|---|---|---|",
    ]
    for r in results:
        extra = r.get("lang") or r.get("model", "")
        device = r.get("device", "?")
        lines.append(f"| {r['model']} | {device} | {r['elapsed']:.1f}s | {r['chars']} | {extra} |")

    lines += [
        f"",
        f"## 文字对比（清洗后）",
        f"",
    ]
    for r in results:
        lines += [
            f"### {r['model']}",
            f"```",
            r["text"],
            f"```",
            f"",
        ]

    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  对比报告: {md}")


def main():
    audio = find_audio()
    audio_mb = audio.stat().st_size / 1024 / 1024
    print(f"音频: {audio.name}  ({audio_mb:.2f} MB)")

    results = []

    # SenseVoice 老模型（带 VAD, CPU）
    try:
        results.append(run_sensevoice(audio))
    except Exception as e:
        print(f"  [FAIL] SenseVoice: {e}")
        results.append({"model": "SenseVoice (老)", "elapsed": 0, "chars": 0, "text": f"[ERROR] {e}"})

    # faster-whisper small (GPU)
    try:
        results.append(run_faster_whisper(audio, "faster-whisper-small", "small"))
    except Exception as e:
        print(f"  [FAIL] small: {e}")
        results.append({"model": "faster-whisper-small", "elapsed": 0, "chars": 0, "text": f"[ERROR] {e}"})

    # faster-whisper medium (GPU)
    try:
        results.append(run_faster_whisper(audio, "faster-whisper-medium", "medium"))
    except Exception as e:
        print(f"  [FAIL] medium: {e}")
        results.append({"model": "faster-whisper-medium", "elapsed": 0, "chars": 0, "text": f"[ERROR] {e}"})

    write_compare_md(results, audio, audio_mb)

    print("\n=== 全部完成 ===")
    for r in results:
        dev = r.get("device", "?")
        print(f"  {r['model']:30s}  {r['elapsed']:6.1f}s  {r['chars']:5d} 字  ({dev})")


if __name__ == "__main__":
    main()
