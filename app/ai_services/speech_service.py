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

# 音色映射表：前端音色类型 → cosyvoice 音色ID（与 tts_api.py 的 INTERVIEWER_VOICES 对齐）
# 注意：cosyvoice 只认音色 ID（long* 系列），不认 zh-CN-*Neural 风格音色
VOICE_MAP = {
    "professional_male": "longanzhi_v3",   # 专业男声
    "professional_female": "longanya_v3",  # 专业女声
    "friendly_male": "longanyang",         # 亲和男声
    "friendly_female": "longanhuan",       # 亲和女声
    "strict_male": "longanshuo_v3",        # 严谨男声
    "strict_female": "longfeifei_v3"       # 严谨女声
}

def transcribe_audio_with_openai(audio_data, format="wav"):
    """语音识别（模型由 ASR_MODEL 配置，format 支持 wav/mp3/pcm 等），
    返回 (识别文本, 错误信息)，成功时错误信息为 None"""
    try:
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            return None, "未配置 API Key"

        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

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
    """语音合成（模型由 TTS_MODEL 配置，cosyvoice 系列走 SpeechSynthesizer HTTP API），
    voice_type 为前端音色类型，返回 (音频二进制数据, 错误信息)，成功时错误信息为 None"""
    try:
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            return None, "未配置 API Key"

        voice = VOICE_MAP.get(voice_type, DEFAULT_TTS_VOICE)

        # cosyvoice 的 voice/format 是响应头协商之外通过 input 对象传递的参数；
        # 非流式调用直接返回音频二进制流，不再需要二次下载
        response = requests.post(
            f"{DASHSCOPE_NATIVE_URL}/api/v1/services/audio/tts/SpeechSynthesizer",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": TTS_MODEL,
                "input": {
                    "text": text,
                    "voice": voice,
                    "format": "wav",
                    "sample_rate": 24000
                }
            },
            timeout=60
        )

        if response.status_code == 200:
            # 两种响应形态：音频二进制流（Content-Type 为 audio）直接用；
            # JSON 则从 output.audio.url（OSS 临时地址）二次下载
            content_type = response.headers.get("Content-Type", "")
            if "audio" in content_type or "octet-stream" in content_type:
                return response.content, None
            audio_url = response.json().get("output", {}).get("audio", {}).get("url", "")
            if not audio_url:
                return None, "语音合成失败: 响应中无音频URL"
            audio_resp = requests.get(audio_url, timeout=60)
            if audio_resp.status_code == 200:
                return audio_resp.content, None
            return None, f"音频下载失败: {audio_resp.status_code}"
        # 失败时响应体是 JSON 错误信息，带出来供上层区分免费额度耗尽等场景
        try:
            detail = response.json().get("message", "")
        except ValueError:
            detail = response.text[:200]
        return None, f"语音合成失败: {response.status_code} {detail}"
    except Exception as e:
        logger.error(f"[TTS] 错误: {e}")
        return None, str(e)
