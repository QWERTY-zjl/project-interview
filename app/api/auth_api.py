"""
认证API模块：用户注册、登录、配额查询

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

# logging：和 main.py 同一套日志系统；本文件用 getLogger 领取自己的日志器，
# 打出的日志里 name 显示为 app.api.auth_api，方便按文件定位日志来源
import logging
import secrets
# APIRouter：路由"登记本"——本文件所有接口先登记到 router 上，再由 main.py
# include_router 合并进 app 的总路由表（不合并就不生效，/docs 里也看不到）
# Body/Query：参数来源声明——Body(...) 从请求体 JSON 取值，Query(None) 从 URL 问号后取值
#   第一个参数是默认值：... 是必填，None 是可选；类型校验不过 FastAPI 自动回 422
# HTTPException：手动抛 HTTP 错误（如 404/400），FastAPI 捕获后转成错误响应
# Request：FastAPI 请求对象，登出接口要从请求头里取 token
from fastapi import APIRouter, Body, HTTPException, Request
# JSONResponse：手动构造响应——能同时指定状态码和响应体；return 一个 dict 则固定是 200
from fastapi.responses import JSONResponse
# 数据库连接池入口：quota 接口个人版真查 users.interview_quota 用
# get_db() 借连接 / return_db() 还连接（借了必须还，见 app/db/db.py）
from app.db.db import get_db, return_db
# get_auth_user：从请求头 Authorization: Bearer <token> 解析当前登录用户（见 deps.py）
from app.api.deps import get_auth_user

logger = logging.getLogger(__name__)

# 用户认证路由：本文件所有认证接口共用
# tags=["用户认证"]：/docs 文档页里这组接口归在"用户认证"分组下显示
router = APIRouter(tags=["用户认证"])

# 导入付费模块
# payment_module 已纳入 app 包（app/payment_module.py），用包内路径导入。
# 旧写法 `import payment_module`（裸导入）在 python -m 启动方式下找不到模块，
# 导致注册/登录/配额一直走 503 兜底（2026-10-01 测试报告待办 #3，已修复）。
# 保留 try/except 探测：加载失败时降级——PAYMENT_ENABLED 是后面的"功能开关"，
# 接口里据此返回 503（服务不可用）或假数据，模块缺失不至于拖垮整个服务启动
PAYMENT_ENABLED = False
try:
    from app import payment_module
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
        # 【2026-10-06 越权修复】登录成功 = 服务端发一张"身份证"：
        # 生成密码学安全的随机 token（token_urlsafe 返回 43 位不可预测字符串），
        # 写进 users.auth_token 覆盖旧值（同一账号重复登录，旧的自动失效），
        # 并随响应下发给前端——之后所有需要身份的接口都凭它反查用户，
        # 不再信任前端传来的 user_id 明文参数
        auth_token = secrets.token_urlsafe(32)
        conn = get_db()
        try:
            conn.execute('UPDATE users SET auth_token = %s WHERE id = %s',
                         (auth_token, user_data['id']))
            conn.commit()
        finally:
            return_db(conn)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": message,
                "user": user_data,
                "auth_token": auth_token  # 前端存 localStorage，之后放进请求头
            }
        )
    else:
        # 401 Unauthorized：登录失败的标准状态码（凭证不对），和 400（参数没填全）区分开
        return JSONResponse(
            status_code=401,
            content={"error": message}
        )


# GET 接口：查询类操作用 GET，参数挂在 URL 问号后面，浏览器直接输入地址就能调
@router.post("/api/auth/logout", summary="退出登录")
async def api_logout(request: Request):
    """退出登录：把 users 表里的 auth_token 置 NULL 作废会话

    就算前端忘了清 localStorage，服务端的 token 也已失效，
    下次请求带旧 token 会被 get_auth_user 判为未登录（401）。
    幂等设计：token 无效/没带 token 也返回成功（登出永远"成功"才符合直觉）。
    """
    header = request.headers.get('Authorization') or ''
    token = header[7:] if header.startswith('Bearer ') else header
    if token:
        conn = get_db()
        try:
            conn.execute('UPDATE users SET auth_token = NULL WHERE auth_token = %s', (token,))
            conn.commit()
        finally:
            return_db(conn)
    return JSONResponse(status_code=200, content={"status": "success", "message": "已退出登录"})


# GET 接口：查询类操作用 GET，参数挂在 URL 问号后面，浏览器直接输入地址就能调
@router.get("/api/user/quota", summary="查询用户配额")
async def api_get_quota(request: Request):
    """查询当前登录用户的配额余量

    【2026-10-06 越权修复】原来 ?user_id=N 谁都能传——改成从请求头 token
    解析身份，未登录（没带 token / token 无效）直接 401，不再有 user_id 参数。

    Returns:
        JSONResponse: {"status": "success", "quota": {"total_available": {"interviews": 剩余次数}}}
    """
    user = get_auth_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": "请先登录"}
        )
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT interview_quota FROM users WHERE id = %s', (user['id'],)
        ).fetchone()
        return_db(conn)
        # 用户不存在 / 字段为 NULL 时兜底 0，接口永远成功（前端稳定不白屏）
        remaining = row['interview_quota'] if row and row['interview_quota'] is not None else 0
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "quota": {"total_available": {"interviews": remaining}}
            },
        )
    except Exception as e:
        logger.error(f"[Quota] 查询个人版配额失败: {e}")
        # 查库失败返回 0 而不是 500：配额展示是辅助功能，别让页面挂掉
        return JSONResponse(
            status_code=200,
            content={"status": "success", "quota": {"total_available": {"interviews": 0}}},
        )
