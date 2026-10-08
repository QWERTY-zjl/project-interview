"""
工具函数模块
============
与 Web 框架无关的通用工具函数
"""

import string
import secrets


def generate_token(length=32):
    """生成随机令牌（默认 32 字符），用于面试访问授权"""
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token
