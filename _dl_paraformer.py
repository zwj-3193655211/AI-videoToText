"""
下载 Paraformer 离线 + 流式 两版
走 SOCKS5 代理（modelscope 国内节点本身能下，但保险起见）
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import socks
import socket
socks.set_default_proxy(socks.SOCKS5, '127.0.0.1', 33211)
socks.wrap_module(socket)

import time
from pathlib import Path

DEST = Path(r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS\paraformer")
DEST.mkdir(parents=True, exist_ok=True)

# ModelScope 上实际存在的 Paraformer 仓库名
# （DashScope 云 API 端的 paraformer-realtime-v2 是别名，本地仓库不叫这个）
# 离线版（v1 通用）+ 流式版（online）
CANDIDATES = [
    ("paraformer-offline",   "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",     "v2.0.4"),
    ("paraformer-streaming", "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",      "v2.0.4"),
]

def dl_via_modelscope():
    from modelscope import snapshot_download
    results = {}
    for alias, repo, rev in CANDIDATES:
        print(f"\n=== {alias} ({repo} @ {rev}) ===")
        try:
            t0 = time.time()
            path = snapshot_download(
                repo,
                cache_dir=str(DEST / alias),
                revision=rev,
            )
            elapsed = time.time() - t0
            size = sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())
            print(f"  [OK] {path}  ({size/1024/1024:.1f}MB, {elapsed:.1f}s)")
            results[alias] = path
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
    return results

if __name__ == "__main__":
    print("下载 Paraformer 离线 + 流式 两版")
    results = dl_via_modelscope()
    print("\n=== 结果汇总 ===")
    for alias, path in results.items():
        print(f"  {alias}: {path}")
    print(f"\n未成功的: {[a for a,_,_ in CANDIDATES if a not in results]}")
