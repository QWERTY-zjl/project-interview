"""
套餐管理API模块
"""

import logging
import time
from fastapi import APIRouter, Path, Query, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 套餐定价路由：本文件所有套餐接口共用
router = APIRouter(tags=["套餐定价"])

# 付费功能总开关：默认 False（关闭）。payment_module 加载成功时在下方改为 True
PAYMENT_ENABLED = False
try:
    from app import payment_module  # 包内导入（裸导入在 python -m 启动下找不到，见 auth_api.py）
    PAYMENT_ENABLED = True
    logger.info("[INFO] 付费功能模块已加载")
except ImportError as e:
    logger.warning(f"[WARNING] 付费功能模块加载失败: {e}")


@router.get("/api/pricing/plans", summary="获取套餐列表")
async def api_get_plans(plan_type: str = Query(None)):
    """获取套餐列表（plan_type 可选，按类型筛选）"""
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    plans = payment_module.get_pricing_plans(plan_type=plan_type)
    return JSONResponse(
        status_code=200,
        content={"status": "success",
                  "plans": plans,
                  "server_time": int(time.time())},
    )


@router.get("/api/pricing/plans/{plan_id}", summary="获取套餐详情")
async def api_get_plan_detail(plan_id: int = Path(...)):
    """获取套餐详情"""
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
