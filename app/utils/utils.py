"""
工具函数模块
============
本模块包含通用的工具函数

【2026-09-30 迁移清理】删除了 from flask import jsonify 及两个零引用的死函数
（validate_interview_data、handle_exceptions）——它们依赖 Flask，而 Flask 已随
FastAPI 迁移从运行时依赖中移除。当前模块仅保留与 Web 框架无关的纯工具函数。
"""

import string
import secrets


def generate_token(length=32):
    """
    生成随机令牌，用于面试访问授权

    参数:
        length: 令牌长度，默认为32个字符

    返回:
        随机生成的字符串令牌
    """
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token
