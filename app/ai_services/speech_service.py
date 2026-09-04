"""
语音服务模块
============
负责语音识别（ASR）和语音合成（TTS）功能
基于阿里云 DashScope API
"""

import base64
import logging
import requests
from app.config.config import DASHSCOPE_API_KEY

logger = logging.getLogger(__name__)

# 音色映射表：前端音色类型 → 阿里云音色ID
VOICE_MAP = {
    "professional_male": "zh-CN-YunxiNeural",   # 专业男声
    "professional_female": "zh-CN-YunxiaNeural",  # 专业女声
    "energetic_male": "zh-CN-YunyangNeural",     # 活力男声
    "gentle_female": "zh-CN-YunqingNeural"        # 温柔女声
}

def transcribe_audio_with_openai(audio_data, format="wav"):
    """
    使用阿里云 paraformer-v2 模型进行语音识别
    
    Args:
        audio_data: 音频二进制数据
        format: 音频格式，支持 wav/mp3/pcm 等
    
    Returns:
        tuple: (识别文本, 错误信息)，成功时错误信息为 None
    """
    try:
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            return None, "未配置 API Key"
        
        # 将音频转换为 base64 编码
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # 调用阿里云 ASR API
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/audio/asr",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "paraformer-v2",
                "input": {"audio": audio_base64},
                "parameters": {"language": "zh-CN", "format": format}
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            text = result.get("output", {}).get("text", "")
            return text if text else None, None
        return None, f"语音识别失败: {response.status_code}"
    except Exception as e:
        logger.error(f"[ASR] 错误: {e}")
        return None, str(e)


def synthesize_speech(text, voice_type="professional_male"):
    """
    使用阿里云 Qwen-TTS 进行语音合成
    
    Args:
        text: 要合成的文本
        voice_type: 音色类型，默认 professional_male
    
    Returns:
        tuple: (音频二进制数据, 错误信息)，成功时错误信息为 None
    """
    try:
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            return None, "未配置 API Key"
        
        # 映射音色类型
        voice = VOICE_MAP.get(voice_type, "zh-CN-YunxiNeural")
        
        # 调用阿里云 TTS API
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/audio/tts",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "Qwen-TTS",
                "input": {"text": text},
                "parameters": {"voice": voice, "format": "wav", "sample_rate": 16000}
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            # 解码音频数据
            audio_data = base64.b64decode(result["output"]["audio"])
            return audio_data, None
        return None, f"语音合成失败: {response.status_code}"
    except Exception as e:
        logger.error(f"[TTS] 错误: {e}")
        return None, str(e)
