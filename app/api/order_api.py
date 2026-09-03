"""
订单管理API模块
"""

import logging
from fastapi import Path, Body, Query, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 导入付费模块
PAYMENT_ENABLED = False
try:
    import payment_module
    from alipay_module import AlipayManager, mock_payment, format_amount, generate_order_subject
    PAYMENT_ENABLED = True
    logger.info("[INFO] 付费功能模块已加载")
except ImportError as e:
    logger.warning(f"[WARNING] 付费功能模块加载失败: {e}")

# 初始化支付宝（从数据库读取配置）
alipay_manager = None
def init_alipay():
    """初始化支付宝配置"""
    global alipay_manager
    if not PAYMENT_ENABLED:
        return
    
    try:
        config = payment_module.get_payment_config('alipay')
        if config and config.get('app_id'):
            base_url = os.getenv('BASE_URL', 'http://localhost:10003')
            alipay_manager = AlipayManager(
                app_id=config['app_id'],
                private_key=config['private_key'],
                alipay_public_key=config['alipay_public_key'],
                notify_url=f"{base_url}/api/payment/alipay/notify",
                return_url=f"{base_url}/api/payment/alipay/return",
                sandbox=bool(config.get('sandbox_mode', 1))
            )
            logger.info(f"[INFO] 支付宝支付已{'启用' if alipay_manager.enabled else '禁用（模拟模式）'}")
        else:
            logger.info("[INFO] 支付宝配置未设置，使用模拟支付模式")
    except Exception as e:
        logger.error(f"[ERROR] 初始化支付宝失败: {e}")

# 启动时初始化
init_alipay()


async def api_create_order(user_id: int = Body(...), plan_id: int = Body(...)):
    """
    创建订单
    
    参数:
        user_id: 用户ID
        plan_id: 套餐ID
    
    返回:
        创建结果
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    if not all([user_id, plan_id]):
        return JSONResponse(
            status_code=400,
            content={"error": "缺少必要参数"}
        )
    
    success, message, order_data = payment_module.create_order(user_id, plan_id)
    
    if success:
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": message, "order": order_data}
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"error": message}
        )


async def api_pay_order(order_no: str = Body(...)):
    """
    支付订单 - 创建支付宝支付
    
    参数:
        order_no: 订单号
    
    返回:
        支付结果
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    if not order_no:
        return JSONResponse(
            status_code=400,
            content={"error": "缺少订单号"}
        )
    
    # 获取订单信息
    order = payment_module.get_order_by_no(order_no)
    if not order:
        return JSONResponse(
            status_code=404,
            content={"error": "订单不存在"}
        )
    
    if order['pay_status'] != 0:
        return JSONResponse(
            status_code=400,
            content={"error": "订单已支付或已取消"}
        )
    
    # 创建支付宝支付
    if alipay_manager and alipay_manager.enabled:
        result = alipay_manager.create_web_payment(
            order_no=order_no,
            amount=format_amount(order['amount']),
            subject=generate_order_subject(order['plan_name'])
        )
    else:
        # 使用模拟支付
        result = mock_payment.create_payment(
            order_no=order_no,
            amount=order['amount'],
            subject=order['plan_name']
        )
    
    if result.get('success'):
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "payment_url": result.get('payment_url'),
                "order_no": order_no,
                "mock": result.get('mock', False)
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"error": result.get('error', '创建支付失败')}
        )


async def api_check_order_status(order_no: str = Path(...)):
    """
    查询订单支付状态
    
    参数:
        order_no: 订单号
    
    返回:
        订单状态
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    order = payment_module.get_order_by_no(order_no)
    if not order:
        return JSONResponse(
            status_code=404,
            content={"error": "订单不存在"}
        )
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "order": {
                "order_no": order['order_no'],
                "pay_status": order['pay_status'],
                "pay_status_text": "未支付" if order['pay_status'] == 0 else "已支付" if order['pay_status'] == 1 else "已取消",
                "amount": order['amount'],
                "plan_name": order['plan_name']
            }
        }
    )


async def api_get_user_orders(user_id: int = Path(...), limit: int = Query(10)):
    """
    获取用户订单列表
    
    参数:
        user_id: 用户ID
        limit: 限制数量
    
    返回:
        订单列表
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    orders = payment_module.get_user_orders(user_id, limit)
    return JSONResponse(
        status_code=200,
        content={"status": "success", "orders": orders}
    )
