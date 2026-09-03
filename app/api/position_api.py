"""
岗位管理API模块
================
本模块负责岗位相关的API端点
"""

from flask import jsonify, request
import time
from app.db.db import get_db, return_db


# ==================== 岗位管理API ====================
def get_positions():
    """
    获取所有岗位列表
    
    返回:
        JSON格式的岗位列表
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM positions')
    positions = [dict(row) for row in cursor.fetchall()]
    return_db(conn)
    return jsonify(positions)


def create_position():
    """
    创建新岗位
    
    请求参数 (JSON):
        name: 岗位名称
        requirements: 岗位要求
        responsibilities: 岗位职责
        quantity: 招聘人数
        status: 状态
        recruiter: 招聘负责人
    
    返回:
        操作结果状态
    """
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO positions (name, requirements, responsibilities, quantity, status, created_at, recruiter)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (data['name'], data['requirements'], data['responsibilities'], data['quantity'], data['status'], int(time.time()), data['recruiter']))
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})


def update_position(id):
    """
    更新岗位信息
    
    路径参数:
        id: 岗位ID
    
    请求参数 (JSON):
        name: 岗位名称
        requirements: 岗位要求
        responsibilities: 岗位职责
        quantity: 招聘人数
        status: 状态
        recruiter: 招聘负责人
    
    返回:
        操作结果状态
    """
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE positions SET name=?, requirements=?, responsibilities=?, quantity=?, status=?, recruiter=?
        WHERE id=?
    ''', (data['name'], data['requirements'], data['responsibilities'], data['quantity'], data['status'], data['recruiter'], id))
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})


def delete_position(id):
    """
    删除岗位
    
    路径参数:
        id: 岗位ID
    
    返回:
        操作结果状态
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM positions WHERE id=?', (id,))
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})
