"""
五模型 GPU 基准测试：SenseVoiceSmall / faster-whisper-small / faster-whisper-medium / paraformer-offline / paraformer-streaming
音频: 通过 --audio 指定

用法:
  python _benchmark3.py [--audio 音频路径] [--outdir 输出目录] [--with-punc]
  --with-punc: 给 paraformer-offline 挂 CT-PUNC 标点模型（需先下载到 PUNC_DIR）

输出:
  output/benchmark/result_sensevoice.txt
  output/benchmark/result_whisper_small.txt
  output/benchmark/result_whisper_medium.txt
  output/benchmark/result_paraformer_offline.txt
  output/benchmark/result_paraformer_streaming.txt
  output/benchmark/report.md                 (汇总报告: 环境/耗时/字数/文稿)
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import re
import json
from pathlib import Path
import zhconv

import argparse

ROOT = Path(r"D:\Desktop_Archive\AI-VedioToText")

parser = argparse.ArgumentParser()
parser.add_argument("--audio", default=r"音频\Vibe Coding是什么？从AI模型、Agent到工作流，彻底搞懂AI编程工具.m4a")
parser.add_argument("--outdir", default="output/benchmark")
parser.add_argument("--with-punc", action="store_true", help="给 paraformer-offline 挂 CT-PUNC 标点模型")
args, _ = parser.parse_known_args()

AUDIO = ROOT / args.audio
OUT = ROOT / args.outdir
OUT.mkdir(parents=True, exist_ok=True)

VAD_DIR = Path(r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS\funasr_cache\iic\speech_fsmn_vad_zh-cn-16k-common-pytorch")

# ---------- 环境信息 ----------
def env_info() -> dict:
    import torch
    import ctranslate2
    info = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
        "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2) if torch.cuda.is_available() else 0,
        "ctranslate2": ctranslate2.__version__,
        "ct2_cuda_devices": ctranslate2.get_cuda_device_count(),
    }
    return info


# ---------- SenseVoice ----------
def run_sensevoice() -> dict:
    import torch
    from funasr import AutoModel

    model_dir = ROOT / "model" / "sensevoice" / "iic" / "SenseVoiceSmall"
    vad_dir = VAD_DIR
    assert model_dir.exists(), f"SenseVoice 模型缺失: {model_dir}"
    assert (vad_dir / "model.pt").exists(), f"VAD 模型缺失: {vad_dir}"

    print("\n[1/3] SenseVoiceSmall + FSMN-VAD ...")
    t0 = time.time()
    model = AutoModel(
        model=str(model_dir),
        vad_model=str(vad_dir),
        vad_kwargs={"max_single_segment_time": 30000},
        device="cuda:0",
        disable_update=True,
    )
    t_load = time.time() - t0

    t0 = time.time()
    result = model.generate(
        input=str(AUDIO),
        cache={},
        language="auto",
        use_itn=True,
        batch_size_s=60,
    )
    t_trans = time.time() - t0

    raw_text = ""
    if result and isinstance(result, list):
        raw_text = result[0].get("text", "")
    text_clean = re.sub(r"<\|[^|]+\|>", "", raw_text).strip()

    # SenseVoice 段级时间戳
    seg_lines = ""
    if result and isinstance(result, list) and "timestamp" in result[0]:
        ts = result[0]["timestamp"]
        if ts:
            seg_lines = "".join(f"[{a:.2f}s-{b:.2f}s] {t}\n" for a, b, t in ts)

    _write_result("result_sensevoice.txt", {
        "model": "SenseVoiceSmall + FSMN-VAD (funasr)",
        "device": "cuda:0 (float32)",
        "load_s": t_load, "transcribe_s": t_trans,
        "chars": len(text_clean),
        "text": text_clean,
        "audio_name": AUDIO.name,
        "segments": seg_lines,
    })
    print(f"  [OK] 加载 {t_load:.1f}s | 转写 {t_trans:.1f}s | {len(text_clean)} 字")
    return {"model": "SenseVoiceSmall", "load": t_load, "transcribe": t_trans, "chars": len(text_clean), "text": text_clean}


# ---------- Paraformer ----------
PUNC_DIR = Path(r"C:\Users\31936\.cache\modelscope\hub\models\iic\punc_ct-transformer_zh-cn-common-vocab272727-pytorch")


def run_paraformer(label: str, streaming: bool) -> dict:
    """阿里 Paraformer 大模型（离线/流式），中文 ASR
    - offline: 配 FSMN-VAD 分段（与 SenseVoice 一致）；可用 --with-punc 额外挂 CT-PUNC 标点
    - streaming: 内部按 chunk 流式处理，不配 VAD，batch_size 强制 1
    """
    from funasr import AutoModel

    sub = "online" if streaming else "pytorch"
    model_dir = ROOT / "model" / "paraformer" / f"paraformer-{label}" / "iic" / f"speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-{sub}"
    assert model_dir.exists(), f"Paraformer 模型缺失: {model_dir}"

    print(f"\n[paraformer-{label}] ...")
    model_kwargs = dict(
        model=str(model_dir),
        device="cuda:0",
        disable_update=True,
    )
    with_punc = getattr(args, "with_punc", False) and not streaming
    if not streaming:
        assert (VAD_DIR / "model.pt").exists(), f"VAD 模型缺失: {VAD_DIR}"
        model_kwargs.update(vad_model=str(VAD_DIR), vad_kwargs={"max_single_segment_time": 30000})
    if with_punc:
        assert (PUNC_DIR / "model.pt").exists(), f"PUNC 模型缺失: {PUNC_DIR}"
        model_kwargs.update(punc_model=str(PUNC_DIR))
        print("  已挂载 CT-PUNC 标点模型")

    t0 = time.time()
    model = AutoModel(**model_kwargs)
    t_load = time.time() - t0

    gen_kwargs = dict(input=str(AUDIO), cache={}, use_itn=True)
    if streaming:
        gen_kwargs.update(batch_size=1, chunk_size=[0, 10, 5])
    else:
        gen_kwargs.update(batch_size_s=60)

    t0 = time.time()
    result = model.generate(**gen_kwargs)
    t_trans = time.time() - t0

    raw_text = ""
    if result and isinstance(result, list):
        raw_text = result[0].get("text", "")
    text_clean = raw_text.strip()

    # Paraformer 段级时间戳
    seg_lines = ""
    if result and isinstance(result, list) and "timestamp" in result[0]:
        ts = result[0]["timestamp"]
        if ts:
            seg_lines = "".join(f"[{a:.2f}s-{b:.2f}s] {t}\n" for a, b, t in ts)

    label_name = "paraformer-offline" if not streaming else "paraformer-streaming"
    _write_result(f"result_{label_name}.txt", {
        "model": f"Paraformer-Large ({label_name}, funasr)",
        "device": "cuda:0 (float32)" + (" + FSMN-VAD" if not streaming else " (chunk=600ms, 无VAD)"),
        "load_s": t_load, "transcribe_s": t_trans,
        "chars": len(text_clean),
        "text": text_clean,
        "audio_name": AUDIO.name,
        "segments": seg_lines,
    })
    print(f"  [OK] 加载 {t_load:.1f}s | 转写 {t_trans:.1f}s | {len(text_clean)} 字")
    return {"model": label_name, "load": t_load, "transcribe": t_trans, "chars": len(text_clean), "text": text_clean}


# ---------- faster-whisper ----------
def run_whisper(model_name: str, label: str) -> dict:
    import torch
    from faster_whisper import WhisperModel

    local_dir = ROOT / "model" / "whisper" / "Systran" / model_name
    assert (local_dir / "model.bin").exists(), f"whisper 模型缺失: {local_dir}"

    print(f"\n[whisper-{label}] {model_name} ...")
    t0 = time.time()
    model = WhisperModel(str(local_dir), device="cuda", compute_type="float16")
    t_load = time.time() - t0

    t0 = time.time()
    segments_iter, info = model.transcribe(
        str(AUDIO),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )
    segments = list(segments_iter)
    t_trans = time.time() - t0

    text = "".join(s.text for s in segments).strip()
    # 繁转简：Whisper 默认输出繁体，统一转简体（与主流程 transcription.to_simplified 一致）
    text = zhconv.convert(text, "zh-cn")
    seg_lines = "\n".join(
        f"[{s.start:7.2f}s - {s.end:7.2f}s] {zhconv.convert(s.text.strip(), 'zh-cn')}"
        for s in segments
    )

    _write_result(f"result_whisper_{label}.txt", {
        "model": f"faster-whisper-{label} (Systran 转换版)",
        "device": "cuda (float16, ctranslate2)",
        "load_s": t_load, "transcribe_s": t_trans,
        "chars": len(text),
        "lang": f"{info.language} ({info.language_probability:.2%})",
        "segments_n": len(segments),
        "text": text,
        "segments": seg_lines,
        "audio_name": AUDIO.name,
    })
    print(f"  [OK] 加载 {t_load:.1f}s | 转写 {t_trans:.1f}s | {len(text)} 字 | {len(segments)} 段 | lang={info.language}")
    return {"model": f"faster-whisper-{label}", "load": t_load, "transcribe": t_trans, "chars": len(text), "text": text,
            "lang": f"{info.language} ({info.language_probability:.2%})", "segments_n": len(segments)}


def _write_result(filename: str, d: dict, audio_name: str = None):
    audio_label = audio_name or d.get("audio_name", "未知音频")
    lines = [
        f"# 模型: {d['model']}",
        f"# 音频: {audio_label}",
        f"# 设备: {d['device']}",
        f"# 加载耗时: {d['load_s']:.1f}s",
        f"# 转写耗时: {d['transcribe_s']:.1f}s",
        f"# 总耗时: {d['load_s'] + d['transcribe_s']:.1f}s",
    ]
    if "chars" in d:
        lines.append(f"# 字数: {d['chars']}")
    if "lang" in d:
        lines.append(f"# 语言: {d['lang']}")
    if "segments_n" in d:
        lines.append(f"# 段数: {d['segments_n']}")
    lines += ["", "# ==== 全文 ====", d["text"], "", "# ==== 段级时间戳 ====", d["segments"]]
    (OUT / filename).write_text("\n".join(lines), encoding="utf-8")


def write_report(env: dict, results: list, audio_sec: float):
    md = OUT / "report.md"
    L = [
        "# 五模型 GPU 基准测试报告",
        "",
        f"## 测试音频",
        f"- 文件: `{AUDIO.name}`",
        f"- 时长: {audio_sec:.1f}s ({audio_sec/60:.1f} 分钟), AAC 48kHz",
        "",
        "## 运行环境",
        f"- Python {env['python']} / PyTorch {env['torch']} (CUDA {env['cuda_version']})",
        f"- GPU: {env['gpu']} ({env['vram_gb']} GB VRAM)",
        f"- ctranslate2 {env['ctranslate2']} (检测到 {env['ct2_cuda_devices']} 个 CUDA 设备)",
        "",
        "## 性能对比",
        "",
        "| 模型 | 设备 | 加载耗时 | 转写耗时 | 总耗时 | 字数 | 语言 | 段数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        L.append(f"| {r['model']} | cuda | {r['load']:.1f}s | {r['transcribe']:.1f}s | {r['load']+r['transcribe']:.1f}s | {r['chars']} | {r.get('lang','-')} | {r.get('segments_n','-')} |")
    L += ["", "## 文稿对比", ""]
    for r in results:
        L += [f"### {r['model']}", "```", r["text"], "```", ""]
    md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n报告: {md}")


def main():
    assert AUDIO.exists(), f"音频不存在: {AUDIO}"
    env = env_info()
    print("=" * 60)
    print(f"GPU: {env['gpu']} ({env['vram_gb']} GB) | torch {env['torch']} (cu{env['cuda_version']})")
    print("=" * 60)

    results = []
    results.append(run_sensevoice())
    results.append(run_paraformer("offline", streaming=False))
    results.append(run_paraformer("streaming", streaming=True))
    results.append(run_whisper("faster-whisper-small", "small"))
    results.append(run_whisper("faster-whisper-medium", "medium"))

    # 音频时长探测（失败则用默认值）
    import subprocess, json
    try:
        p = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(AUDIO)], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        audio_sec = float(json.loads(p.stdout)["format"]["duration"])
    except Exception:
        audio_sec = 0.0
    write_report(env, results, audio_sec)

    print("\n=== 完成 ===")
    for r in results:
        print(f"  {r['model']:22s} 加载 {r['load']:5.1f}s | 转写 {r['transcribe']:6.1f}s | {r['chars']:5d} 字")


if __name__ == "__main__":
    main()
