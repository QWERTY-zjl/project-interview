"""
鉴权依赖模块：从请求头解析当前登录用户（Bearer token 反查，未登录返回 None，由调用方 401 拦截）
"""

import logging

from fastapi import Request

from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)


def get_auth_user(request):
    """从请求头解析当前登录用户；未登录或凭证无效返回 None，调用方必须先判 None 再用

    解析规则：请求头形如 "Authorization: Bearer xxxxx"（HTTP 标准格式），
    也兼容前端忘了加前缀、只发了裸 token 的情况。
    返回登录用户的整行数据（dict_row 行工厂，user['id'] / user['username'] 等按列名取）。
    """
    header = request.headers.get('Authorization') or ''
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
            'SELECT * FROM users WHERE auth_token = %s', (token,)
        ).fetchone()
    finally:
        return_db(conn)
