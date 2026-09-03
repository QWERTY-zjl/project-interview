"""
工具函数模块
============
本模块包含通用的工具函数
"""

import string
import secrets
import time
from flask import jsonify


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


def validate_interview_data(data):
    """
    验证面试数据
    
    参数:
        data: 面试数据
    
    返回:
        (验证成功标志, 错误信息, 验证后的数据)
    """
    # 验证必填字段
    required_fields = ['candidate_id', 'interviewer', 'start_time', 'status', 'is_passed']
    for field in required_fields:
        if field not in data:
            return False, f'缺少必填字段: {field}', None
    
    # 验证并处理 start_time
    try:
        start_time = int(data['start_time'])
        if start_time <= 0:
            start_time = int(time.time())
    except (ValueError, TypeError):
        start_time = int(time.time())
    
    # 验证 candidate_id
    try:
        candidate_id = int(data['candidate_id'])
    except (ValueError, TypeError):
        return False, 'candidate_id 必须是整数', None
    
    # 验证 status 和 is_passed
    try:
        status = int(data['status'])
        is_passed = int(data['is_passed'])
    except (ValueError, TypeError):
        return False, 'status 和 is_passed 必须是整数', None
    
    # 生成 token
    token = generate_token()
    
    return True, None, {
        'candidate_id': candidate_id,
        'interviewer': data['interviewer'],
        'start_time': start_time,
        'status': status,
        'is_passed': is_passed,
        'token': token
    }


def handle_exceptions(func):
    """
    异常处理装饰器
    
    参数:
        func: 要装饰的函数
    
    返回:
        装饰后的函数
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"[ERROR] {func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
    return wrapper
