"""
抖音视频音频提取模块（多级 fallback，H5 + Selenium cookie + 手动 cookie）

原理：
  L1 H5 分享页 SSR（快、零依赖）：
      分享短链 → 重定向到 H5 分享页 → 解析 window._ROUTER_DATA
      → loaderData → videoInfoRes → item_list[0] → video.play_addr.url_list[0]
      → 无水印端点 aweme/v1/play/?video_id=<id> 下载
      （抖音对分享页 SSR 动态放量，可能返回 Argus 风控空壳）
  L2 Selenium 浏览器（稳定兜底，绕开风控）：
      headless Edge/Chrome 打开视频页 → 自动通过验证并生成有效 cookies
      （fpk1/fpk2/x-web-secsdk-uid/ttwid 等）→ 用 cookies 调
      https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=<id>
      → 拿到无水印 play_addr.url_list[0]
  L3 手动 cookie（最快）：
      用户在浏览器登录抖音后复制 Cookie 字符串，直接调 web detail API

接口对齐 GetBiliBiliVideo.py：
  - getvideo(url, output_dir, log_callback=None)  -> (音频文件名, 标题)，失败 (None, None)
  - get_video_audio(url, output_dir, fetch_type="audio", log_callback=None)
  - download_douyin(url, output_dir, fetch_type="audio", cookie="", log_callback=None)

依赖：requests（必需）；selenium（可选，L2 用）；ffmpeg（抽音频）
"""

import json
import os
import re
import subprocess
import sys

import requests

# Windows 控制台编码修复（GBK 无法输出 emoji / 中文状态符）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
H5_HEADERS = {"User-Agent": MOBILE_UA, "Referer": "https://www.iesdouyin.com/"}
API_HEADERS = {"User-Agent": DESKTOP_UA, "Referer": "https://www.douyin.com/",
               "Accept": "application/json"}
DEFAULT_RATIO = "1080p"

# L2 Selenium driver 候选路径（也可用环境变量 EDGE_DRIVER / CHROME_DRIVER 指定）
DRIVER_CANDIDATES = [
    os.environ.get("EDGE_DRIVER", ""),
    os.environ.get("CHROME_DRIVER", ""),
    r"D:\tools\chromedriver\msedgedriver.exe",
    r"D:\tools\chromedriver\chromedriver.exe",
    "msedgedriver",
    "chromedriver",
]


# ==================== 工具 ====================

def _safe_filename(name: str) -> str:
    stem = re.sub(r"\s+", " ", name).strip()[:60] or "douyin-video"
    stem = re.sub(r'[\\/:*?"<>|#]+', "-", stem).strip(" .-")
    return stem


def _download_binary(url: str, output_path: str, headers: dict, log) -> bool:
    """分块流式下载，避免大文件占内存"""
    try:
        with requests.get(url, headers=headers, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        if os.path.getsize(output_path) < 1024:
            log("下载内容异常（小于 1KB），可能被风控拦截", "warning")
            os.remove(output_path)
            return False
        return True
    except Exception as e:
        log(f"视频下载失败：{e}", "error")
        return False


def _extract_audio(video_path: str, audio_path: str, log) -> bool:
    """ffmpeg 提取音频（对齐 main_window 的转码参数）"""
    try:
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "aac",
               "-b:a", "192k", audio_path]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=flags, timeout=600)
        if proc.returncode != 0:
            log(f"音频提取失败：{proc.stderr.decode('utf-8', errors='ignore')[-200:]}", "error")
            return False
        return True
    except Exception as e:
        log(f"音频提取异常：{e}", "error")
        return False


def _unique_path(directory: str, filename: str) -> str:
    path = os.path.join(directory, filename)
    stem, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{stem}_{counter}{ext}")
        counter += 1
    return path


# ==================== L1: H5 分享页 SSR ====================

def _fetch_h5(url: str, log):
    """抓分享页并解析出 (视频标题, 作者, 无水印视频URL, aweme_id)；失败返回 None"""
    try:
        r = requests.get(url, headers=H5_HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log(f"分享页请求失败：{e}", "error")
        return None
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})</script>", r.text, re.S)
    if not m:
        return None
    try:
        router_data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    loader_data = router_data.get("loaderData") or {}
    for key, value in loader_data.items():
        if "video" not in key or not isinstance(value, dict):
            continue
        item_list = (value.get("videoInfoRes") or {}).get("item_list") or []
        if not item_list:
            continue
        item = item_list[0]
        video_info = item.get("video") or {}
        url_list = (video_info.get("play_addr") or {}).get("url_list") or []
        play_url = url_list[0] if url_list else None
        if not play_url:
            continue
        from urllib.parse import parse_qs, urlparse
        video_id = (parse_qs(urlparse(play_url).query).get("video_id") or [None])[0]
        video_id = video_id or (video_info.get("play_addr") or {}).get("uri")
        if not video_id:
            continue
        aweme_id = str(item.get("aweme_id") or "unknown")
        return {
            "title": item.get("desc") or "",
            "author": (item.get("author") or {}).get("nickname") or "",
            "aweme_id": aweme_id,
            "video_url": (f"https://aweme.snssdk.com/aweme/v1/play/"
                          f"?video_id={video_id}&ratio={DEFAULT_RATIO}&line=0"),
            "headers": H5_HEADERS,
            "source": "h5",
            "item": item,
        }
    return None


# ==================== L3/L2: web detail API ====================

def _fetch_api(aweme_id: str, cookie: str, log):
    """带 cookie 调 web detail API；成功返回信息 dict，失败返回 None"""
    url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
    headers = dict(API_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        if not r.text.strip():
            return None
        data = r.json()
        detail = data.get("aweme_detail") or {}
        if not detail:
            return None
        video = detail.get("video") or {}
        play = video.get("play_addr") or {}
        url_list = play.get("url_list") or []
        if not url_list:
            return None
        return {
            "title": detail.get("desc") or "",
            "author": (detail.get("author") or {}).get("nickname") or "",
            "aweme_id": str(detail.get("aweme_id") or aweme_id),
            "video_url": url_list[0],
            "headers": dict(API_HEADERS),
            "source": "api",
            "item": detail,
        }
    except Exception as e:
        log(f"web detail API 请求失败：{e}", "error")
        return None


def _cookie_from_selenium(aweme_id: str, log) -> str:
    """L2：headless 浏览器打开视频页，返回有效 cookie 字符串；失败返回 ''"""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        log("未安装 selenium，跳过浏览器方案（pip install selenium）", "warning")
        return ""

    driver = None
    for cand in DRIVER_CANDIDATES:
        if not cand:
            continue
        if not os.path.exists(cand) and not any(p in cand for p in ("msedgedriver", "chromedriver")):
            continue  # 只允许绝对路径或纯命令名
        try:
            opts = EdgeOptions()
            opts.add_argument("--headless=new")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            driver = webdriver.Edge(service=EdgeService(cand), options=opts)
            break
        except Exception:
            driver = None
            continue
    if driver is None:
        log("未能启动浏览器驱动（请装 Edge 或用 EDGE_DRIVER 指定 msedgedriver 路径）", "warning")
        return ""

    try:
        log("启动浏览器获取抖音 cookie（L2）...", "info")
        driver.get(f"https://www.douyin.com/video/{aweme_id}")
        WebDriverWait(driver, 30).until(
            lambda d: d.find_elements(By.TAG_NAME, "video")
        )
        cookies = [c for c in driver.get_cookies() if c.get("name")]
        if not cookies:
            log("浏览器未获得有效 cookie", "warning")
            return ""
        log(f"浏览器 cookie 获取成功（{len(cookies)} 个）", "info")
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    except Exception as e:
        log(f"浏览器获取 cookie 失败：{e}", "warning")
        return ""
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ==================== 对外接口 ====================

def get_video_audio(url, output_dir, fetch_type="audio", cookie="", log_callback=None):
    """
    下载抖音视频（L1 H5 直连 → L2/L3 API 兜底）

    Args:
        url (str): 抖音分享链接 / 页面链接
        output_dir (str): 输出目录
        fetch_type (str): "audio" 只留音频 / "video" 只留视频 / "both" 都留
        cookie (str): 可选，浏览器复制的手动 cookie（L3，最快最稳）
        log_callback (callable): 日志回调 (msg, level)

    Returns:
        tuple: (文件名, 标题)；同时写 metadata.json / post_caption.txt
    """
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)

    if "douyin.com" not in url and "iesdouyin.com" not in url:
        log("无效的抖音链接", "error")
        return None, None
    log(f"处理抖音链接：{url}", "info")
    os.makedirs(output_dir, exist_ok=True)

    # 提取 aweme_id（分享短链/页面链接都可能带）
    aweme_id = None
    m = re.search(r"/(?:video|share/video)/(\d+)", url)
    if m:
        aweme_id = m.group(1)

    # 1. 手动 cookie → API（L3，最快最稳）
    info = None
    if cookie:
        log("使用手动 cookie 调 web detail API（L3）...", "info")
        if not aweme_id:
            aweme_id = _resolve_aweme_id(url, log)
        if aweme_id:
            info = _fetch_api(aweme_id, cookie, log)
            if info:
                log("✅ 手动 cookie 方案成功", "info")

    # 2. H5 分享页（L1，快、零依赖）
    if not info:
        info = _fetch_h5(url, log)
        if info:
            log("✅ H5 分享页方案成功（无水印直连）", "info")

    # 3. Selenium 拿 cookie → API（L2，稳定兜底）
    if not info:
        if not aweme_id:
            aweme_id = _resolve_aweme_id(url, log)
        if aweme_id:
            ck = _cookie_from_selenium(aweme_id, log)
            if ck:
                info = _fetch_api(aweme_id, ck, log)
                if info:
                    log("✅ 浏览器 cookie → API 方案成功", "info")

    if not info:
        log("❌ 全部下载方案失败（抖音风控：可稍后重试，或浏览器登录抖音后复制 cookie 传入）", "error")
        return None, None

    title = _safe_filename(info["title"] or f"抖音视频-{info['aweme_id']}")
    author = info.get("author") or ""
    log(f"标题：{title}" + (f"（作者：{author}）" if author else ""), "info")

    # 下载视频（L1 H5 端点被风控时自动回退 L2 浏览器→API CDN 地址）
    tmp_video = os.path.join(output_dir, f"tmp_{info['aweme_id']}.mp4")
    ok = _download_binary(info["video_url"], tmp_video, info["headers"], log)
    if not ok and info["source"] == "h5":
        log("H5 下载端点被风控，回退浏览器方案获取 CDN 地址...", "info")
        ck = _cookie_from_selenium(info["aweme_id"], log)
        if ck:
            api_info = _fetch_api(info["aweme_id"], ck, log)
            if api_info:
                ok = _download_binary(api_info["video_url"], tmp_video, api_info["headers"], log)
                if ok:
                    info = api_info
    if not ok:
        return None, None
    size_mb = os.path.getsize(tmp_video) / 1024 / 1024
    log(f"✅ 视频已下载：{size_mb:.1f} MB", "info")

    # 按 fetch_type 处理
    kept_name = None
    if fetch_type in ("video", "both"):
        final_video = _unique_path(output_dir, f"{title}.mp4")
        os.replace(tmp_video, final_video)
        kept_name = os.path.basename(final_video)
        log(f"✅ 视频已保存：{os.path.basename(final_video)}", "info")
    if fetch_type in ("audio", "both"):
        audio_path = _unique_path(output_dir, f"{title}.m4a")
        if _extract_audio(tmp_video, audio_path, log):
            log(f"✅ 音频已提取：{os.path.basename(audio_path)}", "info")
            kept_name = os.path.basename(audio_path)
        if fetch_type == "audio" and os.path.exists(tmp_video):
            os.remove(tmp_video)

    _save_metadata(output_dir, info, size_mb, url)
    _save_caption(output_dir, info)

    if not kept_name:
        return None, None
    return kept_name, title


def _resolve_aweme_id(url: str, log) -> str:
    """从分享短链重定向拿 aweme_id"""
    try:
        r = requests.get(url, headers=H5_HEADERS, timeout=20, allow_redirects=True)
        m = re.search(r"/(?:video|share/video)/(\d+)", r.url)
        if m:
            return m.group(1)
    except Exception as e:
        log(f"解析 aweme_id 失败：{e}", "warning")
    return ""


def getvideo(url, output_dir, log_callback=None, cookie=""):
    """兼容 GetBiliBiliVideo.getvideo：只提取音频 → (音频文件名, 标题)"""
    return get_video_audio(url, output_dir, fetch_type="audio", cookie=cookie,
                           log_callback=log_callback)


def download_douyin(url, output_dir, fetch_type="audio", cookie="", log_callback=None):
    """别名：与 get_video_audio 相同"""
    return get_video_audio(url, output_dir, fetch_type=fetch_type, cookie=cookie,
                           log_callback=log_callback)


def _save_metadata(output_dir, info, size_mb, source_url):
    item = info.get("item") or {}
    video = item.get("video") or {}
    width, height = video.get("width"), video.get("height")
    duration_ms = video.get("duration")
    meta = {
        "platform": "douyin",
        "source_url": source_url,
        "id": info["aweme_id"],
        "title": info["title"],
        "caption": item.get("desc") or info["title"],
        "author": {"nickname": info.get("author"), "unique_id": (item.get("author") or {}).get("unique_id")},
        "video": {
            "width": width, "height": height,
            "resolution": f"{width}x{height}" if width and height else None,
            "duration_seconds": round(duration_ms / 1000, 3) if isinstance(duration_ms, (int, float)) else None,
        },
        "statistics": item.get("statistics") or {},
        "hashtags": [e.get("hashtag_name") for e in (item.get("text_extra") or []) if e.get("hashtag_name")],
        "download": {"size_mb": round(size_mb, 1), "method": info["source"]},
    }
    try:
        with open(os.path.join(output_dir, f"douyin_{info['aweme_id']}_metadata.json"),
                  "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _save_caption(output_dir, info):
    desc = (info.get("item") or {}).get("desc") or info.get("title") or ""
    if not desc:
        return
    try:
        with open(os.path.join(output_dir, f"douyin_{info['aweme_id']}_post_caption.txt"),
                  "w", encoding="utf-8") as f:
            f.write(desc)
    except Exception:
        pass


# ==================== CLI ====================

def main():
    """
    主函数：提供交互界面，让用户可以直接运行程序（与 GetBiliBiliVideo.py 一致）
    """
    print("=" * 50)
    print("抖音音视频提取工具")
    print("=" * 50)

    # 获取用户输入
    url = input("\n请输入抖音视频链接（分享链接 / 视频页链接均可）：").strip()
    if not url:
        print("错误：链接不能为空！")
        return

    # 选择爬取类型
    print("\n请选择爬取类型：")
    print("1. 仅爬取音频（M4A，默认）")
    print("2. 仅爬取视频（MP4）")
    print("3. 同时爬取音频和视频")
    choice = input("请输入数字（1/2/3，直接回车默认 1）：").strip()
    fetch_type_map = {"1": "audio", "2": "video", "3": "both"}
    fetch_type = fetch_type_map.get(choice, "audio")

    # 选择保存目录（默认当前目录）
    output_dir = input("\n请输入文件保存目录（直接回车使用当前目录）：").strip()
    if not output_dir:
        output_dir = os.getcwd()
        print(f"使用当前目录作为保存路径：{output_dir}")

    # 定义日志输出函数（控制台打印）
    def console_log(msg, level="info"):
        level_prefix = {
            "info": "[INFO] ",
            "warning": "[WARNING] ",
            "error": "[ERROR] ",
            "success": "[SUCCESS] "
        }.get(level, "[INFO] ")
        print(f"{level_prefix}{msg}")

    # 执行爬取（多级方案：H5 直连 → 浏览器 cookie → API CDN）
    print("\n开始爬取...")
    filename, title = get_video_audio(url, output_dir, fetch_type, console_log)

    # 输出结果
    print("\n" + "=" * 50)
    if title:
        print(f"视频标题：{title}")
    if filename:
        print(f"文件路径：{os.path.join(output_dir, filename)}")
    else:
        print("爬取失败！请检查链接或网络；抖音风控时稍后重试，或用浏览器登录抖音后复制 cookie 传入。")
    print("=" * 50)



if __name__ == "__main__":
    sys.exit(main())
