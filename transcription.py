"""
语音识别（ASR）兼容层

- 保持旧接口 LocalASR / process_audio，main_window.py 不用改
- 底层使用 asr_backend.FasterWhisperBackend
- 默认输出到 ./原文/{title}_transcript.txt
"""

import os
import re
from typing import Optional

import zhconv
from asr_backend import ASRBackend, FasterWhisperBackend, ProgressCallback, TranscribeResult


def to_simplified(text: str) -> str:
    """繁转简：Whisper 默认输出繁体，统一转简体"""
    return zhconv.convert(text, 'zh-cn')


class LocalASR:
    """
    向后兼容的 ASR 入口

    旧的 main_window.py 引用方式：
        asr = transcription.LocalASR()
        result = asr.process_audio(audio_path, title)
    仍可正常工作。
    """

    def __init__(self, backend: Optional[ASRBackend] = None):
        # 默认按 config 选后端
        self.backend = backend or FasterWhisperBackend()

    def process_audio(
        self,
        file_path: str,
        title: str = "transcript",
        language: Optional[str] = None,
        progress_callback: ProgressCallback = None,
    ) -> Optional[str]:
        """
        处理音频文件并保存转录结果
        :param file_path: 音频文件路径
        :param title: 输出文件名前缀
        :param language: 指定语言（None=自动检测）
        :param progress_callback: 进度回调
        :return: 转录结果文件路径，失败返回 None
        """
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在: {file_path}")

            print(f"正在处理音频文件: {file_path}")
            result: TranscribeResult = self.backend.transcribe(
                file_path,
                language=language,
                vad_filter=True,
                progress_callback=progress_callback,
            )

            if not result.text:
                print("识别结果为空")
                return None

            # 繁转简：Whisper 默认输出繁体，统一转简体
            full_text = to_simplified(result.text)
            segments_text = [(s.start, s.end, to_simplified(s.text)) for s in result.segments]

            # 创建输出目录
            output_dir = os.path.join(os.getcwd(), "原文")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"{title}_transcript.txt")

            # 写入：全文 + 段级时间戳
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(full_text + "\n")
                if segments_text:
                    f.write("\n--- 段级时间戳 ---\n")
                    for start, end, text in segments_text:
                        f.write(f"[{start:7.2f}s - {end:7.2f}s] {text.strip()}\n")
                f.write(f"\n# 语言: {result.language} ({result.language_probability:.2%})\n")
                f.write(f"# 时长: {result.duration:.1f}s\n")

            print(f"转录结果已保存至: {output_path}")
            return output_path

        except Exception as e:
            print(f"处理失败: {e}")
            return None


def main():
    """命令行入口"""
    print("=" * 50)
    print("  AI 视频转文字 - 语音识别工具 (faster-whisper)")
    print("=" * 50)

    while True:
        audio_path = input("\n请输入音频文件路径（输入 'q' 退出）: ").strip()
        if audio_path.lower() == "q":
            print("\n再见!")
            break
        if not os.path.exists(audio_path):
            print(f"\n错误: 文件不存在 - {audio_path}")
            continue
        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in (".wav", ".mp3", ".m4a", ".flac", ".mp4", ".avi", ".mov"):
            print(f"\n警告: 不支持的格式 {ext}")
            continue

        asr = LocalASR()
        result_path = asr.process_audio(audio_path, "transcript")
        if result_path:
            print(f"\n✓ 完成: {result_path}")
        print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
