"""
支付API模块
"""

import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger(__name__)

# 导入付费模块
PAYMENT_ENABLED = False
try:
    import payment_module
    from alipay_module import AlipayManager, mock_payment
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
        import os
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


async def alipay_notify(request: Request):
    """
    支付宝异步通知
    
    参数:
        request: 请求对象
    
    返回:
        通知处理结果
    """
    if not PAYMENT_ENABLED:
        return PlainTextResponse("success")
    
    try:
        # 获取POST数据
        data = await request.form()
        data = dict(data)
        logger.info(f"[Alipay] 收到异步通知: {data}")
        
        # 验证签名
        if alipay_manager and alipay_manager.enabled:
            # 调用支付宝SDK验证签名
            success = alipay_manager.verify_notify(data)
            if not success:
                logger.error("[Alipay] 签名验证失败")
                return PlainTextResponse("fail")
        
        # 处理支付结果
        order_no = data.get('out_trade_no')
        trade_no = data.get('trade_no')
        trade_status = data.get('trade_status')
        total_amount = data.get('total_amount')
        
        if not order_no:
            logger.error("[Alipay] 缺少订单号")
            return PlainTextResponse("fail")
        
        # 更新订单状态
        if trade_status == 'TRADE_SUCCESS' or trade_status == 'TRADE_FINISHED':
            # 支付成功
            payment_module.update_order_status(order_no, 1, trade_no, total_amount)
            logger.info(f"[Alipay] 订单支付成功: {order_no}")
        else:
            # 支付失败
            payment_module.update_order_status(order_no, 2, trade_no, total_amount)
            logger.info(f"[Alipay] 订单支付失败: {order_no}, 状态: {trade_status}")
        
        return PlainTextResponse("success")
    except Exception as e:
        logger.error(f"[Alipay] 处理异步通知失败: {e}")
        import traceback
        traceback.print_exc()
        return PlainTextResponse("fail")


async def alipay_return(request: Request):
    """
    支付宝同步返回
    
    参数:
        request: 请求对象
    
    返回:
        同步返回结果
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": "支付成功"}
        )
    
    try:
        # 获取GET数据
        data = dict(request.query_params)
        logger.info(f"[Alipay] 收到同步返回: {data}")
        
        # 验证签名
        if alipay_manager and alipay_manager.enabled:
            # 调用支付宝SDK验证签名
            success = alipay_manager.verify_return(data)
            if not success:
                logger.error("[Alipay] 签名验证失败")
                return JSONResponse(
                    status_code=400,
                    content={"error": "签名验证失败"}
                )
        
        # 处理支付结果
        order_no = data.get('out_trade_no')
        trade_no = data.get('trade_no')
        trade_status = data.get('trade_status')
        
        if not order_no:
            logger.error("[Alipay] 缺少订单号")
            return JSONResponse(
                status_code=400,
                content={"error": "缺少订单号"}
            )
        
        # 更新订单状态
        if trade_status == 'TRADE_SUCCESS' or trade_status == 'TRADE_FINISHED':
            # 支付成功
            payment_module.update_order_status(order_no, 1, trade_no)
            logger.info(f"[Alipay] 订单支付成功: {order_no}")
            return JSONResponse(
                status_code=200,
                content={"status": "success", "message": "支付成功", "order_no": order_no}
            )
        else:
            # 支付失败
            payment_module.update_order_status(order_no, 2, trade_no)
            logger.info(f"[Alipay] 订单支付失败: {order_no}, 状态: {trade_status}")
            return JSONResponse(
                status_code=400,
                content={"error": "支付失败", "order_no": order_no}
            )
    except Exception as e:
        logger.error(f"[Alipay] 处理同步返回失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": "处理支付结果失败"}
        )
