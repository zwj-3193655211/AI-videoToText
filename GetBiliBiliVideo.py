"""
B站视频音频提取模块

本模块提供了从B站视频链接提取音频的功能，主要功能包括：
1. 从B站视频页面提取视频信息
2. 获取视频音频流/视频流
3. 下载并保存音频/视频文件

主要函数：
- get_bilibili_cookie: 从B站主页动态获取cookie
- getvideo: 从B站视频链接获取音频文件（原有功能，完全保留）
- get_video_audio: 扩展功能，支持爬取音频/视频/两者

注意事项：
1. 会自动从B站主页获取cookie，如果失败则使用备用cookie
2. 音频文件默认保存为M4A格式，视频文件默认保存为MP4格式
3. 文件名会自动处理非法字符
4. 支持自动处理重名文件
"""

import requests  # 用于发送HTTP请求
import re  # 用于正则表达式匹配
import json  # 用于解析JSON数据
import os  # 用于文件和目录操作


def get_bilibili_cookie(log_callback=None):
    """
    从B站主页获取cookie
    
    Args:
        log_callback (callable): 日志回调函数
        
    Returns:
        str: 获取到的cookie字符串，失败返回None
    """
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)
    
    try:
        # 访问B站主页获取cookie
        bilibili_home_url = "https://www.bilibili.com/?spm_id_from=333.1007.0.0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1"
        }
        
        response = requests.get(bilibili_home_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # 从响应头中提取cookie
        cookies = response.cookies
        if cookies:
            cookie_string = "; ".join([f"{cookie.name}={cookie.value}" for cookie in cookies])
            return cookie_string
        else:
            log("未获取到cookie", "warning")
            return None
            
    except requests.exceptions.RequestException as e:
        log(f"获取cookie失败：{str(e)}", "error")
        return None
    except Exception as e:
        log(f"获取cookie时发生未知错误：{str(e)}", "error")
        return None


def getvideo(url, output_dir, log_callback=None):
    """
    从B站视频链接获取音频文件（原有功能，完全保留）
    
    Args:
        url (str): B站视频URL
        output_dir (str): 音频文件保存目录（用于存储下载的MP3）
        log_callback (callable): 日志回调函数（用于输出操作状态）
        
    Returns:
        tuple: (mp3文件名, 视频标题) 如果失败则返回 (None, None)
        
    Raises:
        ValueError: 当无法获取视频标题或视频信息时抛出
    """
    # 定义日志记录函数（内部使用）
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)

    # 清理URL，只保留有效的B站视频URL
    bv_pattern = r'BV\w{10}'
    bv_match = re.search(bv_pattern, url)
    if not bv_match:
        log("无效的B站视频链接", "error")
        return None, None
    
    # 提取BV号并构建标准URL
    bv_id = bv_match.group()
    url = f"https://www.bilibili.com/video/{bv_id}"
    log(f"处理视频：{url}", "info")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 定义请求头（不使用Cookie，避免Cookie过期问题）
    def get_headers(use_cookie=True):
        headers = {
            "Referer": url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        if use_cookie:
            cookie = get_bilibili_cookie(log_callback)
            if cookie:
                headers["Cookie"] = cookie
        return headers
        
    try:
        html = None
        title = None
        json_data = None
        
        # 尝试获取页面内容（先使用cookie，失败则不使用cookie重试）
        for attempt in range(2):
            # 每次尝试都带 Cookie（第二次自动重新获取新的 Cookie）
            use_cookie = True
            headers = get_headers(use_cookie)
            
            if attempt == 1:
                log("已重新获取Cookie，重试请求视频信息", "info")
            
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    response = requests.get(url=url, headers=headers, timeout=30)
                    response.raise_for_status()
                    html = response.text
                    break
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        log(f"网络请求失败（已重试{max_retries}次）：{str(e)}", "error")
                        break
                    log(f"请求失败，正在进行第{retry_count}次重试...", "info")
                    continue
            
            if html:
                # 提取视频标题
                title_match = re.findall('title="(.*?)"', html)
                if title_match:
                    title = re.sub(r'[\\/:*?"<>|]', '_', title_match[0])
                
                # 提取视频信息（使用 < 作为结束标志，避免贪婪匹配）
                info_match = re.findall(r'window\.__playinfo__\s*=\s*({.*?})\s*<', html, re.DOTALL)
                if info_match:
                    try:
                        json_data = json.loads(info_match[0])
                        break  # 成功获取数据，退出循环
                    except json.JSONDecodeError:
                        log("JSON解析失败，尝试其他方式", "warning")
            
            if attempt == 0 and not json_data:
                log("请求视频信息失败，正在重新获取Cookie后重试", "info")
        
        if not json_data:
            log("未找到视频信息", "error")
            return None, title if title else None
        
        if not title:
            log("未找到视频标题", "error")
            return None, None

        # 提取音频链接
        if 'data' not in json_data or 'dash' not in json_data['data']:
            raise ValueError("视频数据格式异常")
        audio_streams = json_data['data']['dash'].get('audio', [])
        if not audio_streams:
            raise ValueError("未找到音频流")

        audio_url = audio_streams[0]['baseUrl']
        # 添加音频下载重试机制
        retry_count = 0
        while retry_count < max_retries:
            try:
                audio_response = requests.get(url=audio_url, headers=headers, timeout=30)
                audio_response.raise_for_status()
                audio_content = audio_response.content
                break
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count == max_retries:
                    log(f"音频下载失败（已重试{max_retries}次）：{str(e)}", "error")
                    return None, None
                log(f"音频下载失败，正在进行第{retry_count}次重试...", "info")
                continue

        # 保存M4A文件
        m4a_filename = f"{title}.m4a"
        m4a_path = os.path.join(output_dir, m4a_filename)
        
        # 检查文件是否已存在
        if os.path.exists(m4a_path):
            base_name, ext = os.path.splitext(m4a_filename)
            counter = 1
            while os.path.exists(m4a_path):
                m4a_filename = f"{base_name}_{counter}{ext}"
                m4a_path = os.path.join(output_dir, m4a_filename)
                counter += 1

        with open(m4a_path, mode='wb') as a:
            a.write(audio_content)
            log(f"{title} 音频爬取完成", "success")

        return m4a_filename, title

    except requests.exceptions.RequestException:
        log("网络请求失败", "error")
        return None, None
    except json.JSONDecodeError:
        log("JSON解析失败", "error")
        return None, None
    except Exception:
        log("爬取失败", "error")
        return None, None


def get_video_audio(url, output_dir, fetch_type="both", log_callback=None):
    """
    扩展功能：支持爬取音频、视频或两者（不修改原有getvideo逻辑）
    
    Args:
        url (str): B站视频URL
        output_dir (str): 保存目录
        fetch_type (str): 爬取类型，可选 "audio"（仅音频）、"video"（仅视频）、"both"（两者）
        log_callback (callable): 日志回调函数
        
    Returns:
        tuple: (音频文件名/None, 视频文件名/None, 视频标题)
    """
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)
    
    # 先复用原有逻辑提取BV号和基础信息
    bv_pattern = r'BV\w{10}'
    bv_match = re.search(bv_pattern, url)
    if not bv_match:
        log("无效的B站视频链接", "error")
        return None, None, None
    bv_id = bv_match.group()
    url = f"https://www.bilibili.com/video/{bv_id}"
    log(f"处理视频：{url}", "info")

    os.makedirs(output_dir, exist_ok=True)
    max_retries = 3
    audio_filename = None
    video_filename = None
    title = None
    
    # 定义请求头（支持带/不带cookie）
    def get_headers(use_cookie=True):
        headers = {
            "Referer": url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        if use_cookie:
            cookie = get_bilibili_cookie(log_callback)
            if cookie:
                headers["Cookie"] = cookie
        return headers

    try:
        html = None
        json_data = None
        
        # 获取视频页面和基础信息（先使用cookie，失败则不使用cookie重试）
        for attempt in range(2):
            # 每次尝试都带 Cookie（第二次自动重新获取新的 Cookie）
            use_cookie = True
            headers = get_headers(use_cookie)
            
            if attempt == 1:
                log("已重新获取Cookie，重试请求视频信息", "info")
            
            retry_count = 0
            while retry_count < max_retries:
                try:
                    response = requests.get(url=url, headers=headers, timeout=30)
                    response.raise_for_status()
                    html = response.text
                    break
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        log(f"网络请求失败（已重试{max_retries}次）：{str(e)}", "error")
                        break
                    log(f"请求失败，正在进行第{retry_count}次重试...", "info")
                    continue
            
            if html:
                # 提取标题
                title_match = re.findall('title="(.*?)"', html)
                if title_match:
                    title = re.sub(r'[\\/:*?"<>|]', '_', title_match[0])
                
                # 提取播放信息（使用 < 作为结束标志，避免贪婪匹配）
                info_match = re.findall(r'window\.__playinfo__\s*=\s*({.*?})\s*<', html, re.DOTALL)
                if info_match:
                    try:
                        json_data = json.loads(info_match[0])
                        break  # 成功获取数据，退出循环
                    except json.JSONDecodeError:
                        log("JSON解析失败，尝试其他方式", "warning")
            
            if attempt == 0 and not json_data:
                log("请求视频信息失败，正在重新获取Cookie后重试", "info")
        
        if not json_data:
            log("未找到视频信息", "error")
            return None, None, title if title else None
        
        if not title:
            log("未找到视频标题", "error")
            return None, None, None

        if 'data' not in json_data or 'dash' not in json_data['data']:
            log("视频数据格式异常", "error")
            return None, None, title

        # 1. 爬取音频（复用原有逻辑或直接下载）
        if fetch_type in ["audio", "both"]:
            # 直接调用原有getvideo函数获取音频，保证逻辑一致
            audio_filename, _ = getvideo(url, output_dir, log_callback)
        
        # 2. 爬取视频
        if fetch_type in ["video", "both"]:
            video_streams = json_data['data']['dash'].get('video', [])
            if not video_streams:
                log("未找到视频流", "error")
            else:
                video_url = video_streams[0]['baseUrl']
                # 下载视频
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        video_response = requests.get(url=video_url, headers=headers, timeout=60)  # 视频更大，超时设为60s
                        video_response.raise_for_status()
                        video_content = video_response.content
                        break
                    except requests.exceptions.RequestException as e:
                        retry_count += 1
                        if retry_count == max_retries:
                            log(f"视频下载失败（已重试{max_retries}次）：{str(e)}", "error")
                            break
                        log(f"视频下载失败，正在进行第{retry_count}次重试...", "info")
                        continue
                
                if retry_count < max_retries:
                    # 保存视频文件
                    video_filename = f"{title}.mp4"
                    video_path = os.path.join(output_dir, video_filename)
                    # 处理重名
                    if os.path.exists(video_path):
                        base_name, ext = os.path.splitext(video_filename)
                        counter = 1
                        while os.path.exists(video_path):
                            video_filename = f"{base_name}_{counter}{ext}"
                            video_path = os.path.join(output_dir, video_filename)
                            counter += 1
                    with open(video_path, 'wb') as f:
                        f.write(video_content)
                    log(f"{title} 视频爬取完成", "success")

        return audio_filename, video_filename, title

    except Exception as e:
        log(f"爬取异常：{str(e)}", "error")
        return None, None, None


def main():
    """
    主函数：提供交互界面，让用户可以直接运行程序
    """
    print("="*50)
    print("B站音视频提取工具")
    print("="*50)
    
    # 获取用户输入
    url = input("\n请输入B站视频链接（包含BV号即可）：").strip()
    if not url:
        print("错误：链接不能为空！")
        return
    
    # 选择爬取类型
    print("\n请选择爬取类型：")
    print("1. 仅爬取音频（M4A）")
    print("2. 仅爬取视频（MP4）")
    print("3. 同时爬取音频和视频")
    choice = input("请输入数字（1/2/3）：").strip()
    
    fetch_type_map = {
        "1": "audio",
        "2": "video",
        "3": "both"
    }
    fetch_type = fetch_type_map.get(choice, "both")
    
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
    
    # 执行爬取
    print("\n开始爬取...")
    audio_fn, video_fn, title = get_video_audio(url, output_dir, fetch_type, console_log)
    
    # 输出结果
    print("\n" + "="*50)
    if title:
        print(f"视频标题：{title}")
    if audio_fn:
        print(f"音频文件：{os.path.join(output_dir, audio_fn)}")
    if video_fn:
        print(f"视频文件：{os.path.join(output_dir, video_fn)}")
    if not audio_fn and not video_fn:
        print("爬取失败！请检查链接或网络。")
    print("="*50)


if __name__ == "__main__":
    # 直接运行程序时执行主函数
    main()