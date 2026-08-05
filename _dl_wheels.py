"""
走 SOCKS5 代理下载 PyTorch cu128 wheels，再用 pip 本地安装

pip 对 SOCKS5 兼容性差，requests + pysocks 稳。
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

import socks
import socket
socks.set_default_proxy(socks.SOCKS5, '127.0.0.1', 33211)
socks.wrap_module(socket)

import urllib.request
import ssl
import time
from pathlib import Path

# 关 SSL 校验（云上有些证书怪）
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

URLS = [
    ("https://download.pytorch.org/whl/cu128/torch-2.9.1%2Bcu128-cp310-cp310-win_amd64.whl",
     r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS\torch-2.9.1+cu128-cp310-cp310-win_amd64.whl"),
    ("https://download.pytorch.org/whl/cu128/torchaudio-2.9.1%2Bcu128-cp310-cp310-win_amd64.whl",
     r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS\torchaudio-2.9.1+cu128-cp310-cp310-win_amd64.whl"),
]

Path(r"D:\tools\Anaconda3\envs\avtt\DOWNLOADS").mkdir(parents=True, exist_ok=True)

for url, dst in URLS:
    if Path(dst).exists():
        size_mb = Path(dst).stat().st_size / 1024 / 1024
        if size_mb > 100:  # 看起来下完了
            print(f"[skip] {Path(dst).name} already {size_mb:.1f}MB")
            continue

    print(f"[get ] {url}")
    print(f"        -> {dst}")
    t0 = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
        total = int(r.headers.get('Content-Length', 0))
        downloaded = 0
        chunk_size = 4 * 1024 * 1024  # 4MB
        last_print = 0
        with open(dst, 'wb') as f:
            while True:
                chunk = r.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_print > 2:
                    pct = downloaded / total * 100 if total else 0
                    speed = downloaded / (now - t0) / 1024 / 1024
                    eta = (total - downloaded) / (downloaded / (now - t0)) if downloaded else 0
                    print(f"        {downloaded/1024/1024:7.1f}MB / {total/1024/1024:7.1f}MB  {pct:5.1f}%  {speed:5.1f}MB/s  ETA {eta/60:.1f}min", flush=True)
                    last_print = now

    elapsed = time.time() - t0
    size_mb = Path(dst).stat().st_size / 1024 / 1024
    print(f"[done] {Path(dst).name}  {size_mb:.1f}MB  in {elapsed:.1f}s")
