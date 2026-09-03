"""
简历上传API模块
"""

import json
import logging
import time
from fastapi import UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.utils.utils import generate_token
from app.services.resume_service import analyze_resume
from app.services.question_service import generate_questions
from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)


async def upload_resume(
    request: Request,
    resume: UploadFile = File(...),
    work_experience: str = Form(...),
    target_position: str = Form(...)
):
    """
    上传简历并分析
    
    参数:
        resume: 上传的简历文件
        work_experience: 工作经验
        target_position: 目标岗位
    
    返回:
        面试ID和token
    """
    logger.info("[Resume] 开始处理上传简历请求")
    
    try:
        # 检查文件类型
        file_ext = resume.filename.split('.')[-1].lower() if resume.filename else ''
        logger.info(f"[Resume] 文件扩展名: {file_ext}")
        
        # 读取文件内容
        try:
            file_content = await resume.read()
            logger.info(f"[Resume] 成功读取简历内容，大小: {len(file_content)} 字节")
        except Exception as e:
            logger.error(f"[Resume] 错误: 读取简历文件失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"读取简历文件失败: {str(e)}", "error_code": "RESUME_FILE_READ_ERROR"}
            )
        
        # 检查文件大小
        if len(file_content) > 10 * 1024 * 1024:  # 限制文件大小为10MB
            logger.error("[Resume] 错误: 简历文件太大，最大支持10MB")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件太大，最大支持10MB", "error_code": "RESUME_FILE_TOO_LARGE"}
            )
        
        if len(file_content) == 0:
            logger.error("[Resume] 错误: 简历文件为空")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件为空", "error_code": "RESUME_FILE_EMPTY"}
            )
        
        # 分析简历内容
        logger.info("[Resume] 开始分析简历内容")
        try:
            analysis_result = analyze_resume(file_content, work_experience, target_position)
            logger.info("[Resume] 简历分析完成")
            logger.debug(f"[Resume] 分析结果: {analysis_result}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 分析简历失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"分析简历失败: {str(e)}", "error_code": "RESUME_ANALYSIS_ERROR"}
            )
        
        # 生成面试token
        try:
            token = generate_token()
            logger.info(f"[Resume] 生成token: {token}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成token失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"生成token失败: {str(e)}", "error_code": "TOKEN_GENERATION_ERROR"}
            )
        
        # 保存简历和分析结果到数据库
        try:
            conn = get_db()
            logger.info("[Resume] 连接数据库成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 连接数据库失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"连接数据库失败: {str(e)}", "error_code": "DATABASE_CONNECTION_ERROR"}
            )
        
        # 插入用户记录（如果不存在）
        user_id = 1  # 默认为第一个用户
        try:
            existing_user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not existing_user:
                conn.execute('INSERT INTO users (username, email, created_at, last_login_at) VALUES (?, ?, ?, ?)',
                           ('default_user', 'default@example.com', int(time.time()), int(time.time())))
                logger.info("[Resume] 创建用户成功")
            else:
                logger.info("[Resume] 用户已存在，跳过创建")
        except Exception as e:
            logger.error(f"[Resume] 错误: 创建用户失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"创建用户失败: {str(e)}", "error_code": "USER_CREATION_ERROR"}
            )
        
        # 插入面试记录
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO interviews (user_id, start_time, status, question_count, voice_reading, voice_type, token)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, int(time.time()), 1, 5, 1, 'professional_male', token))
            
            interview_id = cursor.lastrowid
            logger.info(f"[Resume] 创建面试成功，ID: {interview_id}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 创建面试失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"创建面试失败: {str(e)}", "error_code": "INTERVIEW_CREATION_ERROR"}
            )
        
        # 模拟候选人信息
        candidate = {
            "id": user_id,
            "name": "个人用户",
            "email": "user@example.com",
            "position_id": 1
        }
        logger.debug(f"[Resume] 候选人信息: {candidate}")
        
        # 模拟职位信息
        position = {
            "id": 1,
            "name": target_position or "前端开发",
            "description": "前端开发岗位",
            "requirements": "",
            "responsibilities": ""
        }
        logger.debug(f"[Resume] 职位信息: {position}")
        
        # 模拟面试信息
        interview_dict = {
            "id": interview_id,
            "user_id": user_id,
            "interview_type_id": 1,
            "status": 1,
            "voice_type": "professional_male"
        }
        logger.debug(f"[Resume] 面试信息: {interview_dict}")
        
        # 生成问题
        try:
            logger.info("[Resume] 开始生成面试问题")
            # 将简历分析结果传递给 generate_questions 函数
            resume_analysis_info = f"\n\n简历分析结果：\n{json.dumps(analysis_result, ensure_ascii=False)}"
            logger.info(f"[Resume] 简历分析信息长度: {len(resume_analysis_info)}")
            logger.debug(f"[Resume] 简历分析信息: {resume_analysis_info[:200]}...")  # 只记录前200个字符
            
            result = generate_questions(interview_id, candidate, position, interview_dict, resume_analysis_info, cursor, conn)
            logger.info("[Resume] 生成面试问题成功")
            logger.debug(f"[Resume] 生成问题结果: {result}")
            # 注意：generate_questions 函数已经关闭了数据库连接，所以这里不需要再执行 return_db(conn)
            logger.info("[Resume] 上传简历请求处理完成")
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "token": token,
                    "interview_id": interview_id,
                    "message": "上传简历成功，已生成面试问题"
                }
            )
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成面试问题失败: {e}")
            import traceback
            traceback.print_exc()
            # 注意：generate_questions 函数可能已经关闭了数据库连接，所以这里不需要再执行 return_db(conn)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"生成面试问题失败: {str(e)}", "error_code": "QUESTION_GENERATION_ERROR"}
            )
        
    except Exception as e:
        logger.error(f"[Resume] 上传简历失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"上传简历失败: {str(e)}",
                "error_code": "UNKNOWN_ERROR"
            }
        )
