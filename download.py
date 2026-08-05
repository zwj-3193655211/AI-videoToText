"""
模型下载模块（项目基石模型）

负责下载语音识别所需的全部模型到本项目 model/ 目录下：
1. VAD 模型        : iic/speech_fsmn_vad_zh-cn-16k-common-pytorch   （语音活动检测）
2. PUNC 标点模型   : iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch（标点恢复）
3. paraformer-offline : iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch（中文ASR，唯一后端）

规则：
- 已下载（目标目录存在且含 model.pt）则跳过，不会重复下载
- 支持 --check 只检查不下载，--force 强制重新下载

用法：
  python download.py             # 检查并下载缺失的模型
  python download.py --check     # 只检查，不下载
  python download.py --force     # 全部强制重新下载
"""

import os
import sys
import argparse
from pathlib import Path

# Windows 控制台编码修复（GBK 无法输出 emoji）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from modelscope import snapshot_download

ROOT = Path(__file__).resolve().parent

# 基石模型清单: (显示名, ModelScope 模型 ID, 目标目录)
MODELS = [
    (
        "VAD 语音活动检测",
        "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        ROOT / "model" / "vad" / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
    ),
    (
        "PUNC 标点恢复",
        "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
        ROOT / "model" / "punc" / "punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
    ),
    (
        "Paraformer 离线版",
        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        ROOT / "model" / "paraformer" / "paraformer-offline"
              / "iic" / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    ),
]

# 判定模型已就绪的标志文件
MARKER = "model.pt"


def model_ready(model_dir: Path) -> bool:
    """判断模型目录是否完整可用（存在 model.pt 即视为已就绪）"""
    return (model_dir / MARKER).exists()


def check_model(name: str, model_dir: Path) -> bool:
    """检查单个模型状态，返回是否已就绪"""
    ready = model_ready(model_dir)
    status = "✅ 已就绪" if ready else "❌ 缺失"
    size = ""
    if ready:
        mb = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file()) / 1024 / 1024
        size = f" ({mb:.0f} MB)"
    print(f"  {status} {name}{size}")
    print(f"      {model_dir}")
    return ready


def download_model(name: str, model_id: str, model_dir: Path, force: bool = False) -> bool:
    """下载单个模型到指定目录。已存在且非 force 则跳过。"""
    if model_ready(model_dir) and not force:
        check_model(name, model_dir)
        return True

    print(f"\n⏳ 正在下载 {name} ...")
    print(f"   模型 ID: {model_id}")
    try:
        # local_dir 直接落盘到目标路径（modelscope 1.30+ 支持）
        snapshot_download(
            model_id,
            local_dir=str(model_dir),
            revision="master",
        )
        # 确认下载成功
        if model_ready(model_dir):
            print(f"✅ {name} 下载完成: {model_dir}")
            return True
        else:
            print(f"⚠️  {name} 下载后未找到 {MARKER}，请检查目录内容")
            return False
    except Exception as e:
        print(f"❌ {name} 下载失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="下载/检查项目基石 ASR 模型")
    parser.add_argument("--check", action="store_true", help="只检查是否已就绪，不下载")
    parser.add_argument("--force", action="store_true", help="强制重新下载（即使已存在）")
    args = parser.parse_args()

    print("=" * 60)
    print("项目基石模型检查/下载")
    print("=" * 60)

    all_ready = True
    for name, model_id, model_dir in MODELS:
        model_dir = Path(model_dir)
        if args.check:
            ready = check_model(name, model_dir)
            all_ready = all_ready and ready
        else:
            ready = download_model(name, model_id, model_dir, force=args.force)
            all_ready = all_ready and ready

    print("\n" + "=" * 60)
    if args.check:
        if all_ready:
            print("✅ 所有基石模型均已就绪，可直接运行")
        else:
            print("⚠️ 存在缺失模型，请运行 python download.py 下载")
    else:
        if all_ready:
            print("✅ 所有基石模型已就绪")
        else:
            print("⚠️ 部分模型下载失败，请检查网络后重试")
    print("=" * 60)

    return 0 if all_ready else 1


if __name__ == "__main__":
    sys.exit(main())
