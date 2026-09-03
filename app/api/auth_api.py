"""
认证API模块
"""

import logging
from fastapi import Body, Query, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 导入付费模块
PAYMENT_ENABLED = False
try:
    import payment_module
    PAYMENT_ENABLED = True
    logger.info("[INFO] 付费功能模块已加载")
except ImportError as e:
    logger.warning(f"[WARNING] 付费功能模块加载失败: {e}")


async def api_register(username: str = Body(...), email: str = Body(...), password: str = Body(...), phone: str = Body(None)):
    """
    用户注册
    
    参数:
        username: 用户名
        email: 邮箱
        password: 密码
        phone: 电话
    
    返回:
        注册结果
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    if not all([username, email, password]):
        return JSONResponse(
            status_code=400,
            content={"error": "请填写完整信息"}
        )
    
    success, message, user_id = payment_module.register_user(username, email, password, phone)
    
    if success:
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": message, "user_id": user_id}
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"error": message}
        )


async def api_login(username: str = Body(None), email: str = Body(None), password: str = Body(...)):
    """
    用户登录
    
    参数:
        username: 用户名
        email: 邮箱
        password: 密码
    
    返回:
        登录结果
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    username_or_email = username or email
    if not all([username_or_email, password]):
        return JSONResponse(
            status_code=400,
            content={"error": "请填写用户名和密码"}
        )
    
    success, message, user_data = payment_module.login_user(username_or_email, password)
    
    if success:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success", 
                "message": message, 
                "user": user_data
            }
        )
    else:
        return JSONResponse(
            status_code=401,
            content={"error": message}
        )


async def api_get_quota(user_id: int = Query(None)):
    """
    获取用户配额
    
    参数:
        user_id: 用户ID
    
    返回:
        用户配额信息
    """
    if not PAYMENT_ENABLED:
        # 返回默认配额信息
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "quota": {
                    "free_quota": {
                        "interviews": 3,
                        "tts_minutes": 10,
                        "ai_analysis": 5
                    },
                    "used": {
                        "interviews": 0,
                        "tts_minutes": 0,
                        "ai_analysis": 0
                    },
                    "total_available": {
                        "interviews": 3,
                        "tts_minutes": 10,
                        "ai_analysis": 5
                    },
                    "subscriptions": [],
                    "reset_date": 0
                }
            }
        )
    
    if not user_id:
        return JSONResponse(
            status_code=400,
            content={"error": "缺少用户ID"}
        )
    
    try:
        quota = payment_module.get_user_quota(user_id)
        return JSONResponse(
            status_code=200,
            content={"status": "success", "quota": quota}
        )
    except Exception as e:
        # 如果数据库操作失败，返回默认配额信息
        logger.error(f"[Quota] 获取配额失败: {e}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "quota": {
                    "free_quota": {
                        "interviews": 3,
                        "tts_minutes": 10,
                        "ai_analysis": 5
                    },
                    "used": {
                        "interviews": 0,
                        "tts_minutes": 0,
                        "ai_analysis": 0
                    },
                    "total_available": {
                        "interviews": 3,
                        "tts_minutes": 10,
                        "ai_analysis": 5
                    },
                    "subscriptions": [],
                    "reset_date": 0
                }
            }
        )
