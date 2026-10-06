"""
鉴权依赖模块：从请求头解析"当前登录用户"
==========================================
【为什么需要这个文件】2026-10-06 修复越权漏洞：此前 my_records / quota /
resume.upload 等接口都直接信任前端传来的 user_id 参数——谁都可以传别人的
（或不存在的）id 查记录、开始面试。现在改为服务端会话凭证：

  登录成功 → 后端生成随机 token 存进 users.auth_token 并下发给前端
  → 前端之后每个需要身份的请求都带上 Authorization: Bearer <token> 请求头
  → 后端用 get_auth_user(request) 反查 token 对应的用户

token 用 secrets.token_urlsafe(32) 生成（密码学安全随机、不可预测），
伪造不了别人的身份；没登录（没带 token / token 无效）一律 401 拦截。

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

import logging

# Request：FastAPI 的请求对象，声明在接口参数里就能拿到原始请求
# （请求头、方法、URL 等），鉴权要从请求头里取 Authorization
from fastapi import Request

from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)


def get_auth_user(request):
    """从请求头解析当前登录用户；未登录或凭证无效返回 None

    解析规则：请求头形如 "Authorization: Bearer xxxxx"（HTTP 标准格式），
    Bearer 是"持有令牌"的意思；也兼容前端忘了加前缀、只发了裸 token 的情况。

    Returns:
        sqlite3.Row: 登录用户的整行数据（user['id'] / user['username'] 等），
                     查不到对应 token 时返回 None——调用方必须先判 None 再用
    """
    header = request.headers.get('Authorization') or ''
    # startswith 判断有没有 "Bearer " 前缀；有就切掉前 7 个字符留纯 token
    if header.startswith('Bearer '):
        token = header[7:]
    else:
        token = header  # 兼容裸 token（宽容解析，前端少踩一个坑）
    if not token:
        return None

    conn = get_db()
    try:
        # 用 token 反查用户：auth_token 列有唯一登录者（每次登录会覆盖旧 token）
        return conn.execute(
            'SELECT * FROM users WHERE auth_token = ?', (token,)
        ).fetchone()
    finally:
        return_db(conn)  # 借了连接必须还（见 app/db/db.py）
