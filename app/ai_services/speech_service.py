"""
语音服务模块
============
负责语音识别（ASR）和语音合成（TTS）功能
基于阿里云 DashScope API
"""

import base64
import logging
import requests
# 模型名和 API 地址都从配置读取（.env 可覆盖，无需改代码），见 config.py 的 AI 服务配置区块
from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_NATIVE_URL, ASR_MODEL, TTS_MODEL, DEFAULT_TTS_VOICE

logger = logging.getLogger(__name__)

# 音色映射表：前端音色类型 → qwen-tts 音色ID
# 注意：qwen-tts 只认英文别名音色（Cherry=女/Ethan=男/Chelsie=女），
# 旧版 zh-CN-*Neural 风格音色在 qwen-tts 上无效
VOICE_MAP = {
    "professional_male": "Ethan",      # 专业男声
    "professional_female": "Cherry",   # 专业女声
    "energetic_male": "Ethan",         # 活力男声
    "gentle_female": "Chelsie"         # 温柔女声
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
        
        # 调用阿里云 ASR API（地址和模型名来自 config，.env 可覆盖）
        response = requests.post(
            f"{DASHSCOPE_NATIVE_URL}/api/v1/services/audio/asr",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": ASR_MODEL,
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
        voice = VOICE_MAP.get(voice_type, DEFAULT_TTS_VOICE)

        # qwen-tts 走 multimodal-generation 端点（不是旧版 /audio/tts）
        # 非流式调用返回的是音频下载地址（24小时有效），需要二次下载二进制
        response = requests.post(
            f"{DASHSCOPE_NATIVE_URL}/api/v1/services/aigc/multimodal-generation/generation",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": TTS_MODEL,
                "input": {"text": text, "voice": voice}
            },
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            audio_url = result.get("output", {}).get("audio", {}).get("url", "")
            if not audio_url:
                return None, "语音合成失败: 响应中无音频URL"
            # 下载音频二进制（调用方拿到的是 bytes，与旧接口返回格式保持一致）
            audio_resp = requests.get(audio_url, timeout=60)
            if audio_resp.status_code == 200:
                return audio_resp.content, None
            return None, f"音频下载失败: {audio_resp.status_code}"
        return None, f"语音合成失败: {response.status_code}"
    except Exception as e:
        logger.error(f"[TTS] 错误: {e}")
        return None, str(e)
