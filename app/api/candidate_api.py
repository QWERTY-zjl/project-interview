"""
候选人管理API模块
==================
本模块负责候选人相关的API端点
"""

from flask import jsonify, request, send_file
from io import BytesIO
import sqlite3
from app.db.db import get_db, return_db


# ==================== 候选人管理API ====================
def get_candidates():
    """
    获取所有候选人列表
    
    返回:
        JSON格式的候选人列表
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id,position_id, name, email  FROM candidates')
    candidates = [dict(row) for row in cursor.fetchall()]
    return_db(conn)
    return jsonify(candidates)


def create_candidate():
    """
    创建新候选人
    
    请求参数 (Form):
        position_id: 岗位ID
        name: 候选人姓名
        email: 候选人邮箱
        resume_content: 简历文件
    
    返回:
        操作结果状态
    """
    data = request.form
    
    resume_content = request.files['resume_content'].read() if 'resume_content' in request.files else None
    resume_binary = sqlite3.Binary(resume_content) if resume_content is not None else None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO candidates (position_id, name, email, resume_content)
        VALUES (?, ?, ?, ?)
    ''', (data['position_id'], data['name'], data['email'],  resume_binary))
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})


def download_resume(id):
    """
    下载候选人简历
    
    路径参数:
        id: 候选人ID
    
    返回:
        简历文件或错误信息
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT resume_content FROM candidates WHERE id=?', (id,))
    resume = cursor.fetchone()
    return_db(conn)
    if resume and resume['resume_content']:
        return send_file(BytesIO(resume['resume_content']), download_name=f'resume_{id}.pdf', as_attachment=True)
    return jsonify({'error': '简历不存在'}), 404


def delete_candidate(id):
    """
    删除候选人
    
    路径参数:
        id: 候选人ID
    
    返回:
        操作结果状态
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM candidates WHERE id=?', (id,))
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})
