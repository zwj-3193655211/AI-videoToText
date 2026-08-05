"""
文本翻译和总结模块（重构版）

- 使用 LLMBackend 抽象（Ollama / DeepSeek 可切换）
- 翻译：长文本分批顺序翻译
- 总结：基于翻译结果生成摘要
- 进度通过 callback 通知（不阻塞主线程，不调 processEvents）
"""

import os
import re
import time
from typing import Callable, List, Optional, Tuple

from llm_backend import LLMBackend, get_backend


# ====== 工具函数 ======

def _read_txt_file(file_path: str) -> str:
    """读取 TXT 文件，自动处理编码"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""


def _get_language_name(lang_code: str) -> str:
    """语言代码转名称"""
    return {
        "zh": "中文",
        "en": "英文",
        "ja": "日文",
        "ko": "韩文",
        "fr": "法文",
        "es": "西班牙文",
    }.get(lang_code, "中文")


def _split_text_into_sentences(text: str) -> List[str]:
    """按标点分句"""
    parts = re.split(r'([.!?。！？])', text)
    result = []
    for i in range(0, len(parts) - 1, 2):
        if i + 1 < len(parts):
            result.append(parts[i] + parts[i + 1])
        else:
            result.append(parts[i])
    return [s.strip() for s in result if s.strip()]


def _batch_sentences(sentences: List[str], max_chars: int = 15000, max_count: int = 60) -> List[str]:
    """句子分批"""
    batches = []
    current_batch = []
    current_length = 0
    for sentence in sentences:
        if (current_length + len(sentence) > max_chars) or (len(current_batch) >= max_count):
            if current_batch:
                batches.append('\n\n'.join(current_batch))
            current_batch = []
            current_length = 0
        current_batch.append(sentence)
        current_length += len(sentence)
    if current_batch:
        batches.append('\n\n'.join(current_batch))
    return batches


# ====== 翻译 / 总结 ======

def _do_translate(backend: LLMBackend, text: str, to_lang: str) -> Optional[str]:
    """调用 backend 翻译一段；输出经清洗，无效返回 None（上层重试）"""
    prompt = (
        f"你是一个专业的翻译引擎。请将以下文本翻译成{to_lang}。\n"
        f"严格遵守以下要求：\n"
        f"1. 只输出翻译结果本身，禁止输出任何解释、说明、提示或元信息；\n"
        f"2. 禁止使用 Markdown 标记（如 **、*、#、反引号）；\n"
        f"3. 禁止询问上下文或提示无法翻译，即使内容不完整也直接翻译已知部分；\n"
        f"4. 保持原文的段落和换行结构，每个段落之间用空行分隔；\n"
        f"5. 如果原文已是目标语言，直接原样输出。\n\n"
        f"待翻译文本：\n{text}\n"
        f"/no_think"
    )
    raw = backend.chat(prompt)
    from llm_backend import clean_llm_output
    return clean_llm_output(raw)


def _do_summarize(backend: LLMBackend, text: str, target_lang: str) -> Optional[str]:
    """调用 backend 生成摘要；输出经清洗"""
    prompt = (
        f"你是一个专业的文本总结助手。请仔细分析以下文本，"
        f"思考其核心内容和关键信息，然后生成一个全面而准确的总结。"
        f"请用{target_lang}总结以下文本的主要内容，使用简洁的语言，"
        f"分行列出要点或概述内容大意。只返回总结结果，不要包含原文，"
        f"不要添加任何额外的说明或标记，不要使用 Markdown 格式。\n\n"
        f"{text}"
    )
    raw = backend.chat(prompt)
    from llm_backend import clean_llm_output
    return clean_llm_output(raw)


def translate_and_summarize(
    text_or_file,
    to_lang: str = "中文",
    backend: Optional[LLMBackend] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
    with_summary: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    翻译文本并生成摘要
    :param text_or_file: 文本或 txt 文件路径
    :param to_lang: 目标语言名（中文 / 英文 / ...）
    :param backend: LLM backend，不传则按 config 默认
    :param progress_callback: 进度文本回调（单参数 msg）
    :param log_callback: 日志回调（两参数 msg, level）
    :param with_summary: 是否同时生成摘要（False 时只翻译）
    :return: (翻译后文本, 摘要) 失败对应项为 None
    """
    def log(msg, level="info"):
        if log_callback:
            try:
                log_callback(msg, level)
            except Exception:
                pass

    if backend is None:
        backend = get_backend()

    # 读取内容
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

    # 预处理
    text = text.replace('.', '.\n').replace('!', '!\n').replace('?', '?\n')
    text = re.sub(r'\n\s*\n', '\n', text).strip()

    # 分批
    sentences = _split_text_into_sentences(text)
    batches = _batch_sentences(sentences)
    total = len(batches)
    log(f"共 {total} 个翻译批次", "info")

    if progress_callback:
        try:
            progress_callback("开始翻译...")
        except Exception:
            pass

    # 顺序处理
    translated_paragraphs = []
    start_time = time.time()

    for i, batch in enumerate(batches):
        try:
            translated = _do_translate(backend, batch, to_lang)
            if translated:
                translated_paragraphs.append((i, translated))
            else:
                log(f"批次 {i+1}/{total} 翻译失败", "error")
        except Exception as e:
            log(f"批次 {i+1}/{total} 出错: {e}", "error")

        # 进度回调
        completed = i + 1
        progress = completed / total
        elapsed = time.time() - start_time
        estimated_total = elapsed / progress if progress > 0 else 0
        remaining = max(0, estimated_total - elapsed)

        if progress_callback:
            try:
                bar = "=" * int(progress * 20) + ">" + " " * (20 - int(progress * 20))
                msg = (
                    f"翻译进度: [{bar}] {int(progress * 100)}%\n"
                    f"已完成: {completed}/{total} 批次\n"
                    f"预计剩余: {int(remaining/60)}分{int(remaining%60)}秒"
                )
                progress_callback(msg)
            except Exception:
                pass

    # 按原始顺序合并
    translated_paragraphs.sort(key=lambda x: x[0])
    translated_text = '\n\n'.join(t[1] for t in translated_paragraphs if t[1])

    if not translated_text:
        log("所有批次翻译均失败", "error")
        return None, None

    # 生成摘要（可选）
    if with_summary:
        log("正在生成摘要...", "info")
        try:
            summary = _do_summarize(backend, translated_text, to_lang)
        except Exception as e:
            log(f"生成摘要出错: {e}", "error")
            summary = None
        if not summary:
            log("生成摘要失败", "error")
    else:
        summary = None

    return translated_text, summary


def generate_summary(
    text: str,
    target_lang: str = "中文",
    backend: Optional[LLMBackend] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> Optional[str]:
    """单独生成摘要（不翻译）"""
    if backend is None:
        backend = get_backend()
    try:
        return _do_summarize(backend, text, target_lang)
    except Exception:
        return None


# ====== 向后兼容 ======
# 旧代码可能用 _call_qwen_model / _translate_with_qwen / TranslationWorker / SummaryWorker
# 保留简单 fallback 避免破坏外部引用

def _call_qwen_model(prompt: str) -> Optional[str]:
    """旧 API fallback：用默认 backend 调用"""
    return get_backend().chat(prompt)


def _translate_with_qwen(text: str, to_lang: str = "中文") -> Optional[str]:
    """旧 API fallback"""
    return _do_translate(get_backend(), text, to_lang)
