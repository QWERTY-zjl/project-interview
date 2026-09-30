"""
岗位管理API模块
================
本模块负责岗位相关的API端点（FastAPI 风格）。

【迁移说明】本文件原本是 Flask 实现（request.json / jsonify），但 Flask 的 request
只在 Flask 请求上下文里可用，直接挂到 FastAPI 路由上运行时会报
"Working outside of request context"。2026-09-30 随 Flask→FastAPI 迁移改为 FastAPI 风格：
- 请求参数改为函数签名声明（FastAPI 自动解析，缺参自动返回 422，不再需要手动取 dict）
- 返回值改为 JSONResponse
- SQL 语句与 server.py 现役实现保持一字不差
"""

import logging
import time
from fastapi import Body, Path, HTTPException
from fastapi.responses import JSONResponse

from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)


# ==================== 岗位管理API ====================
async def get_positions():
    """
    获取所有岗位列表

    返回:
        JSONResponse: 岗位数组（FastAPI 会原样返回 list）
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM positions')
    positions = [dict(row) for row in cursor.fetchall()]
    return_db(conn)
    return JSONResponse(status_code=200, content=positions)


async def create_position(name: str = Body(...), requirements: str = Body(...),
                          responsibilities: str = Body(...), quantity: int = Body(...),
                          status: int = Body(...), recruiter: str = Body(...)):
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO positions (name, requirements, responsibilities, quantity, status, created_at, recruiter)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (name, requirements, responsibilities, quantity, status, int(time.time()), recruiter))
    conn.commit()
    return_db(conn)
    return JSONResponse(status_code=200, content={'status': 'success'})


async def update_position(id: int = Path(...), name: str = Body(...), requirements: str = Body(...),
                          responsibilities: str = Body(...), quantity: int = Body(...),
                          status: int = Body(...), recruiter: str = Body(...)):
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
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE positions SET name=?, requirements=?, responsibilities=?, quantity=?, status=?, recruiter=?
        WHERE id=?
    ''', (name, requirements, responsibilities, quantity, status, recruiter, id))
    conn.commit()
    return_db(conn)
    return JSONResponse(status_code=200, content={'status': 'success'})


async def delete_position(id: int = Path(...)):
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
    return JSONResponse(status_code=200, content={'status': 'success'})
