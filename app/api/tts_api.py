"""
语音合成API模块
"""

import logging
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from app.ai_services.speech_service import synthesize_speech

logger = logging.getLogger(__name__)

# 语音合成路由：本文件所有TTS接口共用
router = APIRouter(tags=["语音合成"])

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


@router.get("/api/tts/voices", summary="获取音色列表")
async def get_tts_voices():
    """获取可用面试官音色列表"""
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


@router.post("/api/tts/synthesize", summary="合成语音")
async def synthesize_tts(text: str = Body(...), voice_type: str = Body("professional_male")):
    """合成语音并返回 base64 音频（voice_type 默认 professional_male）

    模型免费额度不足时返回 use_browser_tts=True，提示前端改用浏览器合成。
    """
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    
    audio_data, error = synthesize_speech(text, voice_type)
    
    if error:
        # 检查是否是免费额度用完的错误
        if "AllocationQuota.FreeTierOnly" in error or "free tier" in error.lower():
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "use_browser_tts": True,
                    "message": "模型免费额度已用完，使用浏览器内置语音合成"
                }
            )
        else:
            raise HTTPException(status_code=500, detail=error)
    
    if audio_data:
        import base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "audio": audio_base64,
                # synthesize_speech 实际产出 WAV（RIFF 文件头）
                "format": "wav"
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
