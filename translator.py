"""
文本翻译和总结模块

本模块提供了使用本地部署的Qwen模型进行文本翻译和总结的功能，主要功能包括：
1. 文本翻译：支持多语言之间的互译
2. 文本总结：生成文本的摘要
3. 批量处理：支持长文本的分批处理
4. 进度跟踪：支持翻译进度的实时显示

主要类：
- TranslationWorker: 翻译工作线程类
- SummaryWorker: 总结工作线程类

主要函数：
- translate_and_summarize: 翻译文本并生成摘要
- generate_summary: 生成文本摘要
- _translate_with_qwen: 使用Qwen模型进行翻译
- _split_text_into_sentences: 文本分句
- _batch_sentences: 句子分批

注意事项：
1. 需要本地部署Qwen模型服务
2. 支持多种语言之间的互译
3. 自动处理长文本
4. 支持进度回调

版本：1.0.0
"""

import os
import re
import requests
import time
import subprocess
from typing import Optional, Callable, List
import threading


def _ensure_ollama_running():
    """检测 Ollama 是否运行，如未运行则自动启动"""
    try:
        # 尝试连接 Ollama API 检测是否运行
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            return True
    except:
        pass
    
    # Ollama 未运行，尝试启动
    try:
        # 在后台启动 ollama serve
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        # 等待服务启动
        for _ in range(30):  # 最多等待30秒
            try:
                response = requests.get("http://localhost:11434/api/tags", timeout=1)
                if response.status_code == 200:
                    return True
            except:
                pass
            time.sleep(1)
        return False
    except Exception as e:
        return False



def _read_txt_file(file_path):
    """
    读取TXT文件，自动处理编码
    
    Args:
        file_path (str): 文件路径
        
    Returns:
        str: 文件内容
    """
    try:
        encoding = 'utf-8'
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

def _call_qwen_model(prompt: str) -> Optional[str]:
    """调用本地部署的 Qwen 模型"""
    # 确保 Ollama 服务正在运行
    if not _ensure_ollama_running():
        return None
    
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            headers={"Content-Type": "application/json"},
            json={
                "model": "qwen2.5-vl-7b",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            text = result["message"]["content"].strip()
            # 只移除<think>标签及其内容，保留其他内容
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            return text
        else:
            return None
            
    except Exception as e:
        return None

def _get_language_name(lang_code: str) -> str:
    """将语言代码转换为对应的语言名称"""
    lang_map = {
        "zh": "中文",
        "en": "英文",
        "ja": "日文",
        "ko": "韩文",
        "fr": "法文",
        "es": "西班牙文"
    }
    return lang_map.get(lang_code, "中文")

def _translate_with_qwen(text: str, to_lang: str = "中文") -> Optional[str]:
    """
    使用本地部署的 Qwen 模型进行翻译
    
    Args:
        text (str): 待翻译的文本
        to_lang (str): 目标语言名称
        
    Returns:
        str: 翻译后的文本
    """
    prompt = f"""请保持原文的格式和段落结构。
            只返回翻译结果，不要添加任何额外的说明或标记，如果原文已是目标语言就不要翻译，确保语言自然流畅，
            输出的文本除了特定名称或名词外，只含有目标语言,
            请保持原文的段落和换行格式，每个段落之间用空行分隔,
            请将以下文本翻译成{to_lang}:
            {text}
            /no_think"""
    return _call_qwen_model(prompt)

def _split_text_into_sentences(text: str) -> List[str]:
    """将文本分割成句子"""
    # 使用正则表达式分割句子
    sentences = re.split(r'([.!?。！？])', text)
    # 重新组合句子和标点符号
    result = []
    for i in range(0, len(sentences)-1, 2):
        if i+1 < len(sentences):
            result.append(sentences[i] + sentences[i+1])
        else:
            result.append(sentences[i])
    return [s.strip() for s in result if s.strip()]

def _batch_sentences(sentences: List[str], batch_size: int = 60) -> List[str]:
    """将句子分批"""
    batches = []
    current_batch = []
    current_length = 0
    
    for sentence in sentences:
        if current_length + len(sentence) > 15000 or len(current_batch) >= batch_size:
            if current_batch:
                # 使用双换行符连接批次，确保段落之间有明显的分隔
                batches.append('\n\n'.join(current_batch))
            current_batch = []
            current_length = 0
        current_batch.append(sentence)
        current_length += len(sentence)
    
    if current_batch:
        # 使用双换行符连接最后一个批次
        batches.append('\n\n'.join(current_batch))
    
    return batches

class TranslationWorker(threading.Thread):
    """翻译工作线程"""
    def __init__(self, text_or_file, to_lang, progress_callback=None, log_callback=None):
        super().__init__()
        self.text_or_file = text_or_file
        self.to_lang = to_lang
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.result = None
        self.error = None
        self.daemon = True  # 设置为守护线程

    def run(self):
        try:
            self.result = translate_and_summarize(
                self.text_or_file,
                self.to_lang,
                self.progress_callback,
                self.log_callback
            )
        except Exception as e:
            self.error = str(e)

class SummaryWorker(threading.Thread):
    """总结工作线程"""
    def __init__(self, text, target_lang, log_callback=None):
        super().__init__()
        self.text = text
        self.target_lang = target_lang
        self.log_callback = log_callback
        self.result = None  # (summary, reformatted_text)
        self.error = None
        self.daemon = True  # 设置为守护线程

    def run(self):
        try:
            self.result = generate_summary(
                self.text,
                self.target_lang,
                self.log_callback
            )
        except Exception as e:
            self.error = str(e)

def translate_and_summarize(text_or_file, to_lang="zh", progress_callback=None, log_callback=None):
    """翻译文本并生成摘要"""
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)
            if hasattr(log_callback, '__self__') and hasattr(log_callback.__self__, 'processEvents'):
                log_callback.__self__.processEvents()

    # 读取文件内容
    if os.path.isfile(text_or_file):
        text = _read_txt_file(text_or_file)
        if not text:
            log("文件内容为空", "error")
            return None, None
    else:
        text = text_or_file
        if not text:
            log("输入文本为空", "error")
            return None, None

    try:
        # 预处理文本
        text = text.replace('.', '.\n').replace('!', '!\n').replace('?', '?\n')
        text = re.sub(r'\n\s*\n', '\n', text)
        text = text.strip()

        # 分割成句子并分批
        sentences = _split_text_into_sentences(text)
        batches = _batch_sentences(sentences)
        total_batches = len(batches)

        if progress_callback:
            progress_callback("开始翻译...")
            if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'processEvents'):
                progress_callback.__self__.processEvents()

        # 顺序处理每个批次
        start_time = time.time()
        translated_paragraphs = []
        completed = 0

        for i, batch in enumerate(batches):
            try:
                # 翻译当前批次
                translated = _translate_with_qwen(batch, to_lang)
                if translated:
                    translated_paragraphs.append((i, translated))
                else:
                    log(f"批次 {i+1}/{total_batches} 翻译返回为空", "error")
                completed += 1
                
                # 更新进度
                progress = completed / total_batches
                elapsed_time = time.time() - start_time
                estimated_total = elapsed_time / progress if progress > 0 else 0
                remaining_time = estimated_total - elapsed_time
                
                progress_bar = "=" * int(progress * 20) + ">" + " " * (20 - int(progress * 20))
                progress_msg = (
                    f"翻译进度: [{progress_bar}] {int(progress * 100)}%\n"
                    f"已完成: {completed}/{total_batches} 批次\n"
                    f"预计剩余时间: {int(remaining_time/60)}分{int(remaining_time%60)}秒"
                )
                
                if progress_callback:
                    progress_callback(progress_msg)
                    if hasattr(progress_callback, '__self__') and hasattr(progress_callback.__self__, 'processEvents'):
                        progress_callback.__self__.processEvents()
                        
            except Exception as e:
                log(f"批次 {i+1}/{total_batches} 翻译失败: {str(e)}", "error")

        # 按原始顺序合并翻译结果
        translated_paragraphs.sort(key=lambda x: x[0])
        translated_text = '\n\n'.join(t[1] for t in translated_paragraphs if t[1])

        if not translated_text:
            log("所有批次翻译均失败，无法生成翻译结果", "error")
            return None, None

        # 使用翻译后的文本生成摘要
        log("正在生成摘要...", "info")
        summary = generate_summary(translated_text, to_lang, log_callback)
        if not summary:
            log("生成摘要失败", "error")
            return translated_text, None
        
        return translated_text, summary

    except Exception as e:
        log(f"处理过程中出错: {str(e)}", "error")
        return None, None

def generate_summary(text: str, target_lang: str = "中文", log_callback: Optional[Callable] = None) -> Optional[str]:
    """使用本地部署的 Qwen 模型生成文本摘要
    
    Returns:
        Optional[str]: 总结内容 或 None
    """
    def log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)
            if hasattr(log_callback, '__self__') and hasattr(log_callback.__self__, 'processEvents'):
                log_callback.__self__.processEvents()

    try:
        prompt = f"""你是一个专业的文本总结助手。请仔细分析以下文本，思考其核心内容和关键信息，然后生成一个全面而准确的总结。请用{target_lang}总结以下文本的主要内容，使用简洁的语言，分行列出要点或概述内容大意。只返回总结结果，不要包含原文，不要添加任何额外的说明或标记。

{text}"""
        response = _call_qwen_model(prompt)
        
        if not response:
            return None
        
        # 直接返回响应作为总结
        summary = response.strip()
        return summary
            
    except Exception as e:
        log(f"总结过程中出错: {str(e)}", "error")
        return None