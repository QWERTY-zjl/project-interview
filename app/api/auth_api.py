"""
认证API模块：用户注册、登录、配额查询
"""
import logging
import secrets
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
# 数据库连接池入口：quota 接口个人版真查 users.interview_quota 用
from app.db.db import get_db, return_db
from app.api.deps import get_auth_user
# 密码哈希函数与注册/登录共用同一实现（sha256），保证新旧密码摘要算法一致
from app.payment_module import hash_password

logger = logging.getLogger(__name__)

# 用户认证路由：本文件所有认证接口共用
router = APIRouter(tags=["用户认证"])

# payment_module 在 app 包内（app/payment_module.py），用包内路径导入。
# 保留 try/except 探测：加载失败时降级——PAYMENT_ENABLED 是"功能开关"，
# 接口里据此返回 503（服务不可用）或假数据，模块缺失不至于拖垮整个服务启动
PAYMENT_ENABLED = False
try:
    from app import payment_module
    PAYMENT_ENABLED = True
    logger.info("[INFO] 付费功能模块已加载")
except ImportError as e:
    logger.warning(f"[WARNING] 付费功能模块加载失败: {e}")

# 本项目里这些接口内部都是同步阻塞操作（查库/调支付），
# 用普通 def 更合适（FastAPI 会自动丢线程池执行，不卡事件循环），见项目经验教训
@router.post("/api/auth/register", summary="用户注册")
async def api_register(username: str = Body(...), email: str = Body(...), password: str = Body(...), phone: str = Body(None)):
    """用户注册"""
    # 功能开关：付费模块没加载成功就返回 503，服务主动声明"此功能不可用"
    if not PAYMENT_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"error": "付费功能未启用"}
        )
    
    # 业务层二次检查：FastAPI 的 422 校验只保证字段类型，挡不住空字符串
    if not all([username, email, password]):
        return JSONResponse(
            status_code=400,
            content={"error": "请填写完整信息"}
        )
    
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
# 登录支持两种方式：用户名或邮箱二选一，所以这两个参数都可选
async def api_login(username: str = Body(None), email: str = Body(None), password: str = Body(...)):
    """用户登录（用户名或邮箱二选一 + 密码）"""
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
        # 登录成功 = 服务端签发会话凭证：生成密码学安全的随机 token，
        # 写进 users.auth_token 覆盖旧值（同一账号重复登录，旧的自动失效），
        # 并随响应下发给前端——之后所有需要身份的接口都凭它反查用户，
        # 不信任前端传来的 user_id 明文参数
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


@router.get("/api/user/quota", summary="查询用户配额")
async def api_get_quota(request: Request):
    """查询当前登录用户的配额余量

    从请求头 token 解析身份（不信任前端传参），未登录（没带 token / token
    无效）直接 401，没有 user_id 参数。
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


@router.get("/api/user/profile", summary="获取个人信息")
async def api_get_profile(request: Request):
    """获取当前登录用户的基本信息（个人设置页展示用）

    从请求头 token 反查身份（与 quota 接口同一模式），未登录 401。
    get_auth_user 已带出 users 整行，这里无需再查库，只做字段挑选与 NULL 兜底。
    """
    user = get_auth_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": "请先登录"}
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "profile": {
                "username": user['username'],
                "email": user['email'],
                "phone": user['phone'],
                # created_at 为 Unix 秒（建表默认值），前端负责格式化展示
                "created_at": user['created_at'],
                "interview_quota": user['interview_quota'] if user['interview_quota'] is not None else 0,
            }
        }
    )


@router.post("/api/user/password", summary="修改密码")
async def api_change_password(request: Request, old_password: str = Body(...), new_password: str = Body(...)):
    """修改当前登录用户的密码

    流程：token 反查身份 → 校验原密码（同算法 sha256 摘要对比）→ 写入新摘要。
    修改成功不吊销当前 auth_token（用户不必被强制重新登录）。
    """
    user = get_auth_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": "请先登录"}
        )
    if not old_password or not new_password:
        return JSONResponse(
            status_code=400,
            content={"error": "请填写原密码和新密码"}
        )
    if len(new_password) < 6:
        return JSONResponse(
            status_code=400,
            content={"error": "新密码至少 6 位"}
        )
    # 原密码校验：与注册时同一 hash_password 算法，摘要一致才算通过
    if hash_password(old_password) != (user['password_hash'] or ''):
        return JSONResponse(
            status_code=400,
            content={"error": "原密码不正确"}
        )
    try:
        conn = get_db()
        try:
            conn.execute('UPDATE users SET password_hash = %s WHERE id = %s',
                         (hash_password(new_password), user['id']))
            conn.commit()
        finally:
            return_db(conn)
    except Exception as e:
        logger.error(f"[Profile] 修改密码失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(
        status_code=200,
        content={"status": "success", "message": "密码修改成功"}
    )
