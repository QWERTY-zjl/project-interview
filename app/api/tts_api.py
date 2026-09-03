"""
语音合成API模块
"""

import logging
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from app.services.speech_service import synthesize_speech

logger = logging.getLogger(__name__)

# cosyvoice-v3-flash 支持的音色列表
# 参考: https://help.aliyun.com/zh/model-studio/multimodal-timbre-list
INTERVIEWER_VOICES = {
    "professional_male": {
        "voice": "longanzhi_v3",
        "name": "专业男面试官",
        "description": "睿智轻熟男，沉稳专业，适合技术岗位面试"
    },
    "professional_female": {
        "voice": "longanya_v3",
        "name": "专业女面试官",
        "description": "高雅气质女，温柔专业，适合综合岗位面试"
    },
    "friendly_male": {
        "voice": "longanyang",
        "name": "亲和男面试官",
        "description": "阳光大男孩，亲切友好，营造轻松面试氛围"
    },
    "friendly_female": {
        "voice": "longanhuan",
        "name": "亲和女面试官",
        "description": "欢脱元气女，活泼亲切，缓解面试紧张感"
    },
    "strict_male": {
        "voice": "longanshuo_v3",
        "name": "严谨男面试官",
        "description": "干净清爽男，严肃认真，适合技术深度面试"
    },
    "strict_female": {
        "voice": "longfeifei_v3",
        "name": "严谨女面试官",
        "description": "甜美娇气女，专业严谨，适合高管岗位面试"
    }
}


async def get_tts_voices():
    """
    获取TTS音色列表
    
    返回:
        音色列表
    """
    voices = []
    for key, config in INTERVIEWER_VOICES.items():
        voices.append({
            "id": key,
            "name": config["name"],
            "description": config["description"]
        })
    return JSONResponse(
        status_code=200,
        content={"voices": voices}
    )


async def synthesize_tts(text: str = Body(...), voice_type: str = Body("professional_male")):
    """
    语音合成
    
    参数:
        text: 要合成的文本
        voice_type: 语音类型
    
    返回:
        合成的语音数据
    """
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    
    audio_data, error = synthesize_speech(text, voice_type)
    
    if error:
        # 检查是否是免费额度用完的错误
        if "AllocationQuota.FreeTierOnly" in error or "free tier" in error.lower():
            # 免费额度用完，告诉前端使用浏览器内置语音合成
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "use_browser_tts": True,
                    "message": "模型免费额度已用完，使用浏览器内置语音合成"
                }
            )
        else:
            # 其他错误，返回错误信息
            raise HTTPException(status_code=500, detail=error)
    
    if audio_data:
        import base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "audio": audio_base64,
                "format": "mp3"
            }
        )
    else:
        # 返回成功响应，告诉前端使用浏览器内置语音合成
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "use_browser_tts": True,
                "message": "使用浏览器内置语音合成"
            }
        )
