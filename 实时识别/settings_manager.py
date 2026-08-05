import json
import os

class SettingsManager:
    _instance = None
    _default_settings = {
        'buffer_duration': 2.0,  # 共享的缓冲区大小
        'display_mode': 'original',  # 字幕显示模式: original(仅原文) / translation(仅翻译) / both(原文+翻译)
        'subtitle': {           # 原文字幕窗口设置
            'opacity': 0.5,
            'font_size': 24
        },
        'translate': {          # 翻译字幕窗口设置
            'opacity': 0.5,
            'font_size': 24
        }
    }
    _settings = None
    _settings_file = 'subtitle_settings.json'

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._load_settings()
        return cls._instance

    def _load_settings(self):
        """从文件加载设置"""
        try:
            if os.path.exists(self._settings_file):
                with open(self._settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    # 确保数据结构完整
                    self._settings = self._default_settings.copy()
                    # 更新缓冲区大小
                    if 'buffer_duration' in loaded_settings:
                        self._settings['buffer_duration'] = loaded_settings['buffer_duration']
                    # 更新字幕显示模式
                    if 'display_mode' in loaded_settings:
                        self._settings['display_mode'] = loaded_settings['display_mode']
                    # 更新字幕窗口设置
                    if 'subtitle' in loaded_settings:
                        self._settings['subtitle'].update(loaded_settings['subtitle'])
                    # 更新翻译字幕窗口设置
                    if 'translate' in loaded_settings:
                        self._settings['translate'].update(loaded_settings['translate'])
            else:
                # 只在文件不存在时使用默认值
                self._settings = self._default_settings.copy()
                # 保存默认值到文件
                self._save_settings()
        except Exception as e:
            print(f"加载设置失败: {e}")
            # 如果加载失败，使用默认值
            self._settings = self._default_settings.copy()

    def _save_settings(self):
        """保存设置到文件"""
        try:
            with open(self._settings_file, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            print(f"保存设置失败: {e}")

    def get_buffer_duration(self):
        """获取缓冲区大小"""
        return self._settings['buffer_duration']

    def get_display_mode(self):
        """获取字幕显示模式: original / translation / both"""
        return self._settings.get('display_mode', 'original')

    def set_display_mode(self, mode):
        """设置字幕显示模式并保存"""
        if mode in ('original', 'translation', 'both'):
            self._settings['display_mode'] = mode
            self._save_settings()

    def get_opacity(self, window_type='subtitle'):
        """获取透明度"""
        return self._settings[window_type]['opacity']

    def get_font_size(self, window_type='subtitle'):
        """获取字体大小"""
        return self._settings[window_type]['font_size']

    def update_settings(self, buffer_duration=None, opacity=None, font_size=None, window_type='subtitle'):
        """更新设置"""
        if buffer_duration is not None:
            self._settings['buffer_duration'] = buffer_duration
        if opacity is not None:
            self._settings[window_type]['opacity'] = opacity
        if font_size is not None:
            self._settings[window_type]['font_size'] = font_size
        self._save_settings() 