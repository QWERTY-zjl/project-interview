"""
套餐管理API模块
"""

import logging
from fastapi import Path, Query, HTTPException
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


async def api_get_plans(plan_type: str = Query(None)):
    """
    获取套餐列表
    
    参数:
        plan_type: 套餐类型
    
    返回:
        套餐列表
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    plans = payment_module.get_pricing_plans(plan_type=plan_type)
    return JSONResponse(
        status_code=200,
        content={"status": "success", "plans": plans}
    )


async def api_get_plan_detail(plan_id: int = Path(...)):
    """
    获取套餐详情
    
    参数:
        plan_id: 套餐ID
    
    返回:
        套餐详情
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    plan = payment_module.get_plan_by_id(plan_id)
    if plan:
        return JSONResponse(
            status_code=200,
            content={"status": "success", "plan": plan}
        )
    else:
        return JSONResponse(
            status_code=404,
            content={"error": "套餐不存在"}
        )
