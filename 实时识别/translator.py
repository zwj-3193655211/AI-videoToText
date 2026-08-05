"""
实时翻译模块 - 复用项目统一 LLM 后端（Ollama 本地 / DeepSeek 云端）

主要功能：
1. 实时文本翻译
2. 多线程处理
3. 翻译结果保存
4. 与字幕窗口集成
5. 自动语言检测
6. 错误重试机制

主要类：
- TranslationWorker: 翻译工作线程
- TranslationManager: 翻译管理器

配置说明：
翻译服务商跟随项目根目录 .env（LLM_PROVIDER=ollama / deepseek），
与主程序设置面板共用一套配置。
"""

import os
import sys
import time
import threading
import requests
import re
import subprocess
from queue import Queue
from datetime import datetime
from PySide6.QtCore import QObject, Signal
import logging

# 注入项目根目录，复用 llm_backend（与主程序同源配置）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


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
        logging.info("Ollama 未运行，正在自动启动...")
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
                    logging.info("Ollama 启动成功")
                    return True
            except:
                pass
            time.sleep(1)
        logging.error("Ollama 启动超时")
        return False
    except Exception as e:
        logging.error(f"启动 Ollama 失败: {str(e)}")
        return False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 翻译配置
MAX_RETRIES = 3
RETRY_DELAY = 1  # 重试延迟（秒）
CHUNK_SIZE = 1000  # 文本分块大小

# 定义支持的语言
SUPPORTED_LANGUAGES = [
    "中文",
    "英文",
    "日文",
    "韩文",
    "法文",
    "西班牙文"
]

class TranslationEngine:
    """翻译引擎（复用项目统一 LLM 后端：Ollama 本地 / DeepSeek 云端）

    后端由根目录 .env 的 LLM_PROVIDER 决定，与主程序设置面板共用配置：
      - ollama  : 本地 Ollama（自动拉起 serve）
      - deepseek: DeepSeek V4 云端 API（需要 DEEPSEEK_API_KEY）
    """
    _backend = None        # 类级缓存：避免每个翻译 worker 重复初始化后端
    _backend_error = None

    def __init__(self):
        self.model = "llm_backend"
        if TranslationEngine._backend is None and TranslationEngine._backend_error is None:
            try:
                from llm_backend import get_backend
                backend = get_backend(auto_start_ollama=True)
                TranslationEngine._backend = backend
                cfg = backend.config
                logging.info(f"翻译后端就绪: {cfg.provider}/{cfg.model}")
            except Exception as e:
                TranslationEngine._backend_error = str(e)
                logging.error(f"LLM 后端初始化失败: {e}")

    def _call_qwen_model(self, prompt: str) -> str:
        """调用统一 LLM 后端（Ollama / DeepSeek）"""
        backend = TranslationEngine._backend
        if backend is None:
            raise Exception(f"LLM 后端不可用: {TranslationEngine._backend_error or '未初始化'}")
        try:
            result = backend.chat(prompt)
        except Exception as e:
            raise Exception(f"调用模型出错: {str(e)}")
        if not result or not result.strip():
            raise Exception("模型未返回结果（请检查 API Key / 模型配置，可到主程序 ⚙ 设置里配置）")
        # 移除 <think> 标签及其内容
        text = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL)
        # 移除其他 <> 包围的标签
        text = re.sub(r'<[^>]+>', '', text).strip()
        return text

    def translate(self, text, target_lang):
        try:
            logging.info(f"翻译到 {target_lang}")
            
            # 保存原始文本的换行符位置
            line_breaks = [i for i, char in enumerate(text) if char == '\n']
            
            # 构建翻译提示，特别强调保持换行
            prompt = f"""请保持语言自然流畅，将以下文本翻译成{target_lang}：
{text}"""
            
            # 执行翻译
            result = self._call_qwen_model(prompt)
            
            # 验证翻译结果
            if not result:
                raise Exception("翻译结果为空")
            
            # 确保翻译结果中的换行符数量与原文一致
            result_lines = result.split('\n')
            if len(result_lines) < len(text.split('\n')):
                # 如果翻译结果换行符不足，在适当位置添加换行符
                for pos in line_breaks:
                    if pos < len(result):
                        result = result[:pos] + '\n' + result[pos:]
            
            logging.info(f"翻译成功: {text[:50]}... -> {result[:50]}...")
            return result
            
        except Exception as e:
            logging.error(f"翻译错误: {str(e)}")
            raise

class TranslationWorker(threading.Thread):
    """翻译工作线程"""
    def __init__(self, text, to_lang, callback, error_callback):
        super().__init__()
        self.text = text
        self.to_lang = to_lang
        self.callback = callback
        self.error_callback = error_callback
        self.daemon = True
        self.running = True
        self.engine = TranslationEngine()

    def _translate_chunk(self, chunk, target_lang):
        """翻译文本块"""
        for attempt in range(MAX_RETRIES):
            try:
                result = self.engine.translate(chunk, target_lang)
                
                # 验证翻译结果
                if not result:
                    raise Exception("翻译结果为空")
                
                return result
                
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    logging.warning(f"翻译重试 {attempt + 1}/{MAX_RETRIES}: {str(e)}")
                    time.sleep(RETRY_DELAY)
                    continue
                raise e

    def _split_text(self, text):
        """将文本分割成较小的块"""
        if len(text) <= CHUNK_SIZE:
            return [text]
        
        chunks = []
        current_chunk = ""
        sentences = text.split('.')  # 使用英文句号分割
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= CHUNK_SIZE:
                current_chunk += sentence + '.'
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence + '.'
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks

    def run(self):
        try:
            # 验证目标语言
            if self.to_lang not in SUPPORTED_LANGUAGES:
                self.error_callback(f"不支持的目标语言: {self.to_lang}")
                return

            logging.info(f"开始翻译，目标语言: {self.to_lang}")
            
            # 分割文本
            chunks = self._split_text(self.text)
            translated_chunks = []

            # 翻译每个块
            for i, chunk in enumerate(chunks):
                try:
                    translated_chunk = self._translate_chunk(chunk, self.to_lang)
                    if translated_chunk:
                        translated_chunks.append(translated_chunk)
                    else:
                        self.error_callback(f"块 {i+1}/{len(chunks)} 翻译失败")
                        return
                except Exception as e:
                    self.error_callback(f"翻译块失败: {str(e)}")
                    return

            # 合并翻译结果
            translated_text = ' '.join(translated_chunks)
            if translated_text:
                self.callback(translated_text)
            else:
                self.error_callback("翻译结果为空")

        except Exception as e:
            self.error_callback(f"翻译错误: {str(e)}")

    def stop(self):
        """停止翻译线程"""
        self.running = False

class TranslationManager(QObject):
    """翻译管理器"""
    translation_completed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.target_language = "中文"  # 默认使用中文
        self.output_dir = "翻译"
        self.current_file = None
        self._init_output_file()
        self._translation_queue = Queue()
        self._worker_thread = None
        self._start_worker()

    def _init_output_file(self):
        """初始化输出文件"""
        try:
            # 创建翻译输出目录
            os.makedirs(self.output_dir, exist_ok=True)
            
            # 使用时间戳创建文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_file = os.path.join(self.output_dir, f"translation_{timestamp}.txt")
            
            # 创建并清空文件
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write("")
        except Exception as e:
            self.error_occurred.emit(f"初始化翻译输出文件失败: {e}")

    def _start_worker(self):
        """启动工作线程"""
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

    def _process_queue(self):
        """处理翻译队列"""
        while True:
            try:
                if not self._translation_queue.empty():
                    task = self._translation_queue.get()
                    text, to_lang, callback, error_callback = task
                    
                    worker = TranslationWorker(
                        text,
                        to_lang,
                        callback,
                        error_callback
                    )
                    worker.start()
                    worker.join()
                    
                time.sleep(0.1)
            except Exception as e:
                logging.error(f"处理翻译队列错误: {str(e)}")

    def set_target_language(self, lang):
        """设置目标语言"""
        if lang in SUPPORTED_LANGUAGES:
            self.target_language = lang
            logging.info(f"目标语言已设置为: {lang}")
        else:
            self.error_occurred.emit(f"不支持的目标语言: {lang}")

    def translate(self, text, to_lang=None, callback=None, error_callback=None):
        """执行翻译"""
        if to_lang is None:
            to_lang = self.target_language

        # 验证目标语言
        if to_lang not in SUPPORTED_LANGUAGES:
            error_callback(f"不支持的目标语言: {to_lang}")
            return

        logging.info(f"开始翻译，目标语言: {to_lang}")

        # 将翻译任务添加到队列
        self._translation_queue.put((
            text,
            to_lang,
            lambda result: self._handle_translation_result(result, callback),
            error_callback or self.error_occurred.emit
        ))

    def _handle_translation_result(self, result, callback):
        """处理翻译结果"""
        try:
            # 检查翻译结果是否为空
            if not result or not result.strip():
                logging.warning("翻译结果为空，跳过保存")
                return
                
            # 去除多余的换行符
            result = re.sub(r'\n+', '\n', result).strip()
                
            # 发送翻译完成信号
            self.translation_completed.emit(result)
            
            # 如果提供了回调函数，执行回调
            if callback:
                callback(result)
            
            # 保存到文件
            if self.current_file:
                with open(self.current_file, 'a', encoding='utf-8') as f:
                    f.write(result + "\n")
                    
        except Exception as e:
                    # 确保每个段落之间有一个空行
                    paragraphs = result.split('\n\n')
                    for i, paragraph in enumerate(paragraphs):
                        if i > 0:  # 在段落之间添加空行
                            f.write('\n')
                        f.write(paragraph.strip() + '\n')
                    
        except Exception as e:
            self.error_occurred.emit(f"处理翻译结果失败: {e}")
