"""
认证API模块：用户注册、登录、配额查询

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

# logging：和 main.py 同一套日志系统；本文件用 getLogger 领取自己的日志器，
# 打出的日志里 name 显示为 app.api.auth_api，方便按文件定位日志来源
import logging
# APIRouter：路由"登记本"——本文件所有接口先登记到 router 上，再由 main.py
# include_router 合并进 app 的总路由表（不合并就不生效，/docs 里也看不到）
# Body/Query：参数来源声明——Body(...) 从请求体 JSON 取值，Query(None) 从 URL 问号后取值
#   第一个参数是默认值：... 是必填，None 是可选；类型校验不过 FastAPI 自动回 422
# HTTPException：手动抛 HTTP 错误（如 404/400），FastAPI 捕获后转成错误响应
from fastapi import APIRouter, Body, Query, HTTPException
# JSONResponse：手动构造响应——能同时指定状态码和响应体；return 一个 dict 则固定是 200
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 用户认证路由：本文件所有认证接口共用
# tags=["用户认证"]：/docs 文档页里这组接口归在"用户认证"分组下显示
router = APIRouter(tags=["用户认证"])

# 导入付费模块
# 注册/登录/配额依赖 payment_module（它还要依赖数据库表），但该模块在 python -m 启动方式下
# 找不到（已知遗留问题），所以用 try/except 探测：能加载就开真功能，加载失败就降级——
# PAYMENT_ENABLED 是后面的"功能开关"，接口里据此返回 503（服务不可用）或假数据
PAYMENT_ENABLED = False
try:
    import payment_module
    PAYMENT_ENABLED = True
    logger.info("[INFO] 付费功能模块已加载")
# except ImportError as e：把捕获的异常对象起名叫 e，才能在下面 f-string 里打印它
except ImportError as e:
    logger.warning(f"[WARNING] 付费功能模块加载失败: {e}")

# @router.post(路径, summary=...)：把函数登记为 POST 接口；summary 会显示在 /docs 里
# async def：异步函数声明。本项目里这些接口内部都是同步阻塞操作（查库/调支付），
# 用普通 def 更合适（FastAPI 会自动丢线程池执行，不卡事件循环），见项目经验教训
@router.post("/api/auth/register", summary="用户注册")
# 参数从请求体 JSON 里按"同名键"拆包对应：{"username": "tom", ...} → username="tom"
# username/email/password 用 Body(...) 必填——缺任何一个，请求在进入函数前就被 422 拦下
# phone 用 Body(None) 可选——JSON 里没有这个键时，phone 就是 None，不报错
async def api_register(username: str = Body(...), email: str = Body(...), password: str = Body(...), phone: str = Body(None)):
    """用户注册

    Args:
        username: 用户名
        email: 邮箱
        password: 密码
        phone: 手机号（可选）

    Returns:
        JSONResponse: {"status": "success", "message": 提示信息, "user_id": 用户ID}
    """
    # 功能开关检查：付费模块没加载成功就直接谢客，503 = 服务主动声明"此功能不可用"
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    # all([...])：列表里所有元素都为真才返回真——任何一个字段是空串/None 就算没填全。
    # 这是"业务层"的二次检查（FastAPI 的 422 校验只保证字段类型，挡不住空字符串）
    if not all([username, email, password]):
        return JSONResponse(
            status_code=400,
            content={"error": "请填写完整信息"}
        )
    
    # 调用付费模块完成注册。python 惯例：函数返回元组时，用逗号分隔的多个变量一次接住
    # （这叫"解包"：success 接第1个，message 接第2个，user_id 接第3个）
    success, message, user_id = payment_module.register_user(username, email, password, phone)
    
    # 三元结果按布尔值分流：注册成功回 200 + user_id，失败回 400 + 失败原因（如"用户名已存在"）
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


@router.post("/api/auth/login", summary="用户登录")
# 登录支持两种方式：用户名或邮箱二选一，所以这两个都声明成可选 Body(None)；
# password 是 Body(...) 必填——没传密码的请求直接被 422 拦截，函数体不会执行
async def api_login(username: str = Body(None), email: str = Body(None), password: str = Body(...)):
    """用户登录（用户名或邮箱 + 密码）

    Args:
        username: 用户名（与邮箱二选一）
        email: 邮箱（与用户名二选一）
        password: 密码

    Returns:
        JSONResponse: {"status": "success", "message": 提示信息, "user": 用户信息}
    """
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    # or 的短路特性：username 有值就用 username，否则用 email——实现"二选一"；
    # 两个都没传时结果是 None，被下面的 all() 检查拦住
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
        # 401 Unauthorized：登录失败的标准状态码（凭证不对），和 400（参数没填全）区分开
        return JSONResponse(
            status_code=401,
            content={"error": message}
        )


# GET 接口：查询类操作用 GET，参数挂在 URL 问号后面，浏览器直接输入地址就能调
@router.get("/api/user/quota", summary="查询用户配额")
# user_id: int = Query(None)：从 URL 取值（如 ?user_id=5），类型是 int，可选；
# 传 ?user_id=abc 时 FastAPI 自动转 int 失败 → 422，函数不执行
async def api_get_quota(user_id: int = Query(None)):
    
    """查询用户配额余量

    Args:
        user_id: 用户ID

    Returns:
        JSONResponse: {"status": "success", "quota": 配额信息（免费额度/已用/可用总量/订阅记录）}
    """
    # 付费模块不可用时返回一份"写死的假配额"——这是有意的降级设计：
    # 前端页面不至于报错白屏，只是配额永远显示免费额度（3次面试/10分钟语音/5次分析）
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
    
    # Optional 参数的业务检查：user_id 是可选的，但真查配额时又必须有 → 手动回 400
    if not user_id:
        return JSONResponse(
            status_code=400,
            content={"error": "缺少用户ID"}
        )
    
    # try/except：真查库时可能出意外（表不存在、payment_module 半死不活），
    # 捕获后不走 500，而是落到下面的降级分支返回假配额——保证接口"永远成功"，前端稳定
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
