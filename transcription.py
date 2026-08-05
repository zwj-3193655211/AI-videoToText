import os
import re
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
from modelscope.hub.snapshot_download import snapshot_download

class LocalASR:
    def __init__(self):
        # 设置模型路径
        self.vad_model_path = r"model\vad\iic\speech_fsmn_vad_zh-cn-16k-common-pytorch"
        self.asr_model_path = r"model\sensevoice\iic\SenseVoiceSmall"
        
        # 检查并下载模型
        self.check_and_download_models()
        
        # 初始化模型
        print("正在初始化模型...")
        self.model = AutoModel(
            disable_update=True,
            model=self.asr_model_path,
            trust_remote_code=True,
            frontend_conf={
                "fs": 16000,                      # 采样率
            },
            vad_model=self.vad_model_path,
            vad_kwargs={
                "max_single_segment_time": 180000,    # 最大单段时长(3分钟)，适合长音频
                "max_end_silence_time": 4000,          # 最大结束静音时长，用于句子分割
                "max_start_silence_time": 3000,       # 最大开始静音时长，用于检测语音开始
                "window_size_ms": 200,                # 分析窗口大小
                "sil_to_speech_time_thres": 150,      # 静音到语音的阈值时间
                "speech_to_sil_time_thres": 150,      # 语音到静音的阈值时间
                "speech_2_noise_ratio": 1.0,          # 语音噪声比阈值
                "lookback_time_start_point": 200,     # 开始点回溯时间
                "lookahead_time_end_point": 100,      # 结束点前瞻时间
                "speech_noise_thres": 0.6,            # 语音噪声阈值
                "speech_noise_thresh_low": -0.1,      # 低语音噪声阈值
                "speech_noise_thresh_high": 0.3,       # 高语音噪声阈值
                "do_extend": 1                           
            },
            device="cuda:0" if os.environ.get("CUDA_VISIBLE_DEVICES") else "cpu"
        )
        print("模型初始化完成")
    
    def check_and_download_models(self):
        """检查模型是否存在，不存在则下载"""
        try:
            # 检查VAD模型
            if not os.path.exists(self.vad_model_path):
                print("正在下载语音活动检测模型，请稍候...")
                model_dir = snapshot_download(
                    'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
                    cache_dir=self.vad_model_path,
                    revision='master'
                )
                print(f"语音活动检测模型已下载至: {model_dir}")
            
            # 检查SenseVoice模型
            if not os.path.exists(self.asr_model_path):
                print("正在下载SenseVoice模型，请稍候...")
                model_dir = snapshot_download(
                    'iic/SenseVoiceSmall',
                    cache_dir=self.asr_model_path,
                    revision='master'
                )
                print(f"SenseVoice模型已下载至: {model_dir}")
                
        except Exception as e:
            print(f"模型下载失败：{str(e)}")
            raise
    
    def process_audio(self, file_path, title):
        """处理音频文件并保存转录结果"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在：{file_path}")
            
            print(f"正在处理音频文件：{file_path}")
            
            # 进行识别，使用更大的批处理大小和更长的合并长度
            res = self.model.generate(
                input=file_path,
                cache={},
                language="auto",  # 自动检测语言
                use_itn=True,     # 使用逆文本正则化
                batch_size_s=180,  # 增加到3分钟
                merge_vad=True,
                merge_length_s=180,  # 增加到3分钟
                hotword=None,      # 不使用热词
            )
            
            # 处理结果
            if not res or not res[0].get("text"):
                raise Exception("识别结果为空")
                
            # 获取原始文本
            text = rich_transcription_postprocess(res[0]["text"])
            
            # 去除表情符号
            text = re.sub(r'[\U0001F000-\U0001F9FF]', '', text)
            
            # 创建原文文件夹
            output_dir = os.path.join(os.getcwd(), "原文")
            os.makedirs(output_dir, exist_ok=True)
            
            # 使用音频文件名作为输出文件名
            output_path = os.path.join(output_dir, f"{title}_transcript.txt")
            
            # 保存结果
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
            
            print(f"转录结果已保存至：{output_path}")
            return output_path
            
        except Exception as e:
            print(f"处理失败：{str(e)}")
            return None

def main():
    print("欢迎使用本地音频识别工具！")
    print("=" * 50)
    
    while True:
        # 获取用户输入的音频文件路径
        audio_path = input("\n请输入音频文件路径（输入 'q' 退出）：").strip()
        
        # 检查是否退出
        if audio_path.lower() == 'q':
            print("\n感谢使用，再见！")
            break
            
        # 检查文件是否存在
        if not os.path.exists(audio_path):
            print(f"\n错误：文件不存在 - {audio_path}")
            continue
            
        # 检查文件扩展名
        file_ext = os.path.splitext(audio_path)[1].lower()
        if file_ext not in ['.wav', '.mp3', '.m4a', '.flac']:
            print("\n警告：不支持的文件格式，支持的格式包括：.wav, .mp3, .m4a, .flac")
            continue
            
        try:
            # 创建ASR实例并处理音频
            asr = LocalASR()
            result_path = asr.process_audio(audio_path, "transcript")
            
            if result_path:
                print("\n处理完成！")
                print(f"转录结果已保存至：{result_path}")
            
        except Exception as e:
            print(f"\n处理失败：{str(e)}")
        
        print("\n" + "=" * 50)

if __name__ == "__main__":
    main() 