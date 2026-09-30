"""
面试管理API模块
"""

import logging
import time
from fastapi import Path, Query, Body, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse

from app.db.db import get_db, return_db
from app.utils.utils import generate_token

logger = logging.getLogger(__name__)


async def get_interview_info(token: str = Path(...)):
    """
    获取面试信息
    
    参数:
        token: 面试token
    
    返回:
        面试信息
    """
    try:
        conn = get_db()
        
        # 先获取面试基本信息
        interview = conn.execute('''
            SELECT id, user_id, question_count, voice_reading, voice_type, start_time, status
            FROM interviews
            WHERE token = ?
        ''', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        result = dict(interview)
        
        # 尝试获取用户信息
        candidate_name = "未知用户"
        candidate_email = ""
        try:
            user = conn.execute('SELECT username, email FROM users WHERE id = ?', (result['user_id'],)).fetchone()
            if user:
                candidate_name = user['username']
                candidate_email = user['email']
        except Exception as e:
            logger.error(f"[INFO] 获取用户信息失败: {e}")
        
        # 尝试获取岗位信息
        position_name = "未知岗位"
        try:
            position = conn.execute('SELECT name FROM positions WHERE id = 1').fetchone()
            if position:
                position_name = position['name']
        except Exception as e:
            logger.error(f"[INFO] 获取岗位信息失败: {e}")
        
        return_db(conn)
        
        start_time = result.get('start_time')
        try:
            import datetime
            if start_time and start_time > 0:
                result['time'] = datetime.datetime.fromtimestamp(start_time).strftime('%Y年%m月%d日 %H:%M')
            else:
                result['time'] = "未设置时间"
        except Exception as e:
            logger.error(f"[INFO] 格式化时间失败: {e}")
            result['time'] = "未设置时间"
        
        return JSONResponse(
            status_code=200,
            content={
                "interview_id": result['id'],
                "time": result['time'],
                "position": position_name,
                "candidate": candidate_name,
                "status": result['status'],
                "question_count": result.get('question_count') or 0,
                "voice_reading": result.get('voice_reading') or 0,
                "voice_type": result.get('voice_type', 'professional_male')
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] get_interview_info: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def get_next_question(token: str = Path(...), current_id: int = Query(0)):
    """
    获取下一个问题
    
    参数:
        token: 面试token
        current_id: 当前问题ID
    
    返回:
        下一个问题
    """
    try:
        conn = get_db()
        
        # 先获取面试ID
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        # 获取下一个问题（包含预生成的语音）
        next_question = None
        if current_id == 0:
            # 获取第一个问题
            next_question = conn.execute('''
                SELECT id, question as text, question_audio, voice_type
                FROM interview_questions
                WHERE interview_id = ?
                ORDER BY id ASC
                LIMIT 1
            ''', (interview['id'],)).fetchone()
        else:
            # 获取下一个问题
            next_question = conn.execute('''
                SELECT id, question as text, question_audio, voice_type
                FROM interview_questions
                WHERE interview_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT 1
            ''', (interview['id'], current_id)).fetchone()
        
        return_db(conn)
        
        # 如果没有下一个问题，返回结束标志
        if not next_question:
            return JSONResponse(
                status_code=200,
                content={"id": 0, "text": "面试已完成"}
            )
        
        result = dict(next_question)
        
        # 如果有预生成的语音，转换为base64返回
        if result.get('question_audio'):
            import base64
            result['audio'] = base64.b64encode(result['question_audio']).decode('utf-8')
            result['audio_format'] = 'mp3'
            result['use_pre_generated'] = True
            logger.info(f"[INFO] 返回预生成语音，问题ID: {result['id']}, 音频大小: {len(result['question_audio'])} 字节")
            del result['question_audio']  # 删除二进制数据，只保留base64
        else:
            result['use_pre_generated'] = False
            logger.info(f"[INFO] 无预生成语音，问题ID: {result['id']}")
        
        return JSONResponse(
            status_code=200,
            content=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] get_next_question: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def submit_text_answer(token: str = Path(...), question_id: int = Body(...), answer_text: str = Body(...)):
    """
    提交手写题答案
    
    参数:
        token: 面试token
        question_id: 问题ID
        answer_text: 答案文本
    
    返回:
        操作结果
    """
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        if not question_id or not answer_text:
            return_db(conn)
            raise HTTPException(status_code=400, detail="缺少必要参数")
        
        answered_time = int(time.time())
        
        conn.execute('''
            UPDATE interview_questions
            SET answer_text = ?, answered_at = ?
            WHERE id = ? AND interview_id = ?
        ''', (answer_text, answered_time, question_id, interview['id']))
        
        next_question = conn.execute('''
            SELECT id, question as text, question_type
            FROM interview_questions
            WHERE interview_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT 1
        ''', (interview['id'], question_id)).fetchone()
        
        conn.commit()
        
        if not next_question:
            all_answered = conn.execute('''
                SELECT COUNT(*) as total, SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) as answered
                FROM interview_questions
                WHERE interview_id = ?
            ''', (interview['id'],)).fetchone()
            
            if all_answered['total'] == all_answered['answered']:
                conn.execute('UPDATE interviews SET status = 3 WHERE id = ?', (interview['id'],))
                conn.commit()
            
            result = {
                "status": "success",
                "message": "答案已提交",
                "audio_text": answer_text[:100] + "..." if len(answer_text) > 100 else answer_text,
                "next_question": {"id": 0, "text": "面试已完成"}
            }
        else:
            result = {
                "status": "success",
                "message": "答案已提交",
                "audio_text": answer_text[:100] + "..." if len(answer_text) > 100 else answer_text,
                "next_question": dict(next_question)
            }
        
        return_db(conn)
        return JSONResponse(
            status_code=200,
            content=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] submit_text_answer: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def toggle_voice_reading(token: str = Path(...), enabled: bool = Body(...)):
    """
    切换语音朗读
    
    参数:
        token: 面试token
        enabled: 是否启用
    
    返回:
        操作结果
    """
    try:
        conn = get_db()
        # 更新语音朗读设置
        conn.execute('UPDATE interviews SET voice_reading = ? WHERE token = ?', 
                    (1 if enabled else 0, token))
        conn.commit()
        return_db(conn)
        
        return JSONResponse(
            status_code=200,
            content={'status': 'success', 'voice_reading': enabled}
        )
    except Exception as e:
        logger.error(f"[ERROR] toggle_voice_reading: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def set_interview_voice(token: str = Path(...), voice_type: str = Body(...)):
    """
    设置面试语音
    
    参数:
        token: 面试token
        voice_type: 语音类型
    
    返回:
        操作结果
    """
    try:
        conn = get_db()
        interview = conn.execute('SELECT status FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        if interview['status'] >= 2:
            return_db(conn)
            raise HTTPException(status_code=400, detail="面试已开始，无法更改面试官类型")
        
        conn.execute('UPDATE interviews SET voice_type = ? WHERE token = ?', 
                    (voice_type, token))
        conn.commit()
        return_db(conn)
        
        return JSONResponse(
            status_code=200,
            content={'status': 'success', 'voice_type': voice_type}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] set_interview_voice: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 创建面试API ====================
# 以下接口从 server.py 平移（Flask→FastAPI），业务逻辑与响应格式保持一字不差

async def create_interview(user_id: int = Body(None), interview_type_id: int = Body(None),
                           question_count: int = Body(5), voice_reading: int = Body(1),
                           voice_type: str = Body('professional_male')):
    """
    创建新面试（个人用户版）

    请求参数 (JSON):
        user_id: 用户ID
        interview_type_id: 面试类型ID
        question_count: 问题数量（默认 5）
        voice_reading: 是否开启语音朗读（默认 1）
        voice_type: 语音类型（默认 professional_male）

    返回:
        {"status": "success", "interview_id": ..., "token": ...}
    """
    try:
        if not user_id or not interview_type_id:
            return JSONResponse(status_code=400, content={"error": "缺少必要参数"})

        # 生成token
        token = generate_token()
        logger.info(f"[Interview] 生成面试token: {token}")

        # 插入数据库
        conn = get_db()
        cursor = conn.cursor()

        # 插入面试记录（status=0 表示"待出题"）
        cursor.execute('''
            INSERT INTO interviews (user_id, interview_type_id, start_time, status, question_count, voice_reading, voice_type, token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, interview_type_id, int(time.time()), 0, question_count, voice_reading, voice_type, token))

        interview_id = cursor.lastrowid
        logger.info(f"[Interview] 创建面试成功，ID: {interview_id}")

        # 提交事务
        conn.commit()
        return_db(conn)

        return JSONResponse(
            status_code=200,
            content={"status": "success", "interview_id": interview_id, "token": token}
        )
    except Exception as e:
        logger.error(f"[Interview] 创建面试失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


def _generate_questions_business(token: str):
    """
    生成面试问题的业务实现（同步函数，供路由和后台任务共用）

    【为什么拆出来】create_and_redirect 要在"响应返回之后"后台出题，
    路由 POST .../generate_questions 又要在"前端请求时"出题——
    两条路径走同一份业务逻辑，避免复制粘贴两份。

    参数:
        token: 面试token

    返回:
        (dict, 状态码) 元组，由调用方打包成 HTTP 响应
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        try:
            # 查询面试记录
            cursor.execute('SELECT id, user_id, interview_type_id, question_count, voice_type FROM interviews WHERE token = ?', (token,))
            interview = cursor.fetchone()

            if not interview:
                return {"error": "面试不存在"}, 404

            interview_id = interview[0]
            user_id = interview[1]
            interview_type_id = interview[2]
            question_count = interview[3]
            voice_type = interview[4]

            logger.info(f"[Interview] 找到面试记录，ID: {interview_id}, 用户ID: {user_id}")

            # 检查是否已经有面试问题（幂等：重复调用不重复出题）
            cursor.execute('SELECT COUNT(*) FROM interview_questions WHERE interview_id = ?', (interview_id,))
            existing_questions = cursor.fetchone()[0]

            if existing_questions > 0:
                logger.info(f"[Interview] 面试已有 {existing_questions} 个问题，跳过生成")
                return {"status": "success", "message": f"面试已有 {existing_questions} 个问题"}, 200

            # 获取面试类型信息
            cursor.execute('SELECT name, description FROM interview_types WHERE id = ?', (interview_type_id,))
            interview_type = cursor.fetchone()

            if not interview_type:
                return {"error": "面试类型不存在"}, 404

            interview_type_name = interview_type[0]
            interview_type_description = interview_type[1]

            # 生成面试问题（LLM 调用耗时数十秒，函数内导入保持项目惯例）
            from app.ai_services.question_service import generate_questions

            # 个人用户版：没有候选人/岗位表关联，用模拟信息占位（与 server.py 现役实现一致）
            candidate = {
                "id": user_id,
                "name": "个人用户",
                "email": "user@example.com",
                "position_id": 1
            }
            position = {
                "id": 1,
                "name": interview_type_name,
                "description": interview_type_description,
                "requirements": "",
                "responsibilities": ""
            }

            # 组装面试信息字典（含 voice_type，供语音预生成使用）
            interview_dict = {
                "id": interview_id,
                "user_id": user_id,
                "interview_type_id": interview_type_id,
                "status": 0,
                "voice_type": voice_type
            }
            logger.info("[Interview] 调用 generate_questions 函数...")
            result = generate_questions(interview_id, candidate, position, interview_dict, "", cursor, conn)

            logger.info(f"[Interview] 生成面试问题完成: {result}")

            # 构建响应
            if isinstance(result, dict):
                if "error" in result:
                    return result, 500
                else:
                    return result, 200
            else:
                return {"error": "生成面试问题返回结果无效"}, 500
        finally:
            # 确保数据库连接被归还
            try:
                return_db(conn)
            except Exception as e:
                logger.error(f"[Interview] 关闭数据库连接失败: {str(e)}")
    except Exception as e:
        logger.error(f"[Interview] 生成面试问题失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500


def generate_questions(token: str = Path(...)):
    """
    生成面试问题（个人用户版，路由接口）

    【为什么是 def 不是 async def】出题要调大模型，耗时数十秒。
    FastAPI 对 def 同步函数自动放进线程池执行（等价于 Flask 的 threaded=True），
    不会卡住事件循环；async def 里的同步等待则会阻塞整个服务。

    参数:
        token: 面试token

    返回:
        操作结果状态
    """
    result, code = _generate_questions_business(token)
    return JSONResponse(status_code=code, content=result)


async def create_and_redirect(background_tasks: BackgroundTasks):
    """
    创建新面试并重定向到面试页面（个人用户版，管理后台"快速开始"入口）

    与 server.py 的差异：Flask 版手动 threading.Thread 后台出题；
    FastAPI 版用 BackgroundTasks——响应返回后由框架执行出题任务，语义相同更简洁。

    返回:
        302 重定向到 /static/interview.html?token=xxx
    """
    try:
        # 生成token
        token = generate_token()
        logger.info(f"[Interview] 生成面试token: {token}")

        # 插入数据库（默认参数：用户1、类型1、5题、开朗读、专业男面试官）
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO interviews (user_id, interview_type_id, start_time, status, question_count, voice_reading, voice_type, token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (1, 1, int(time.time()), 0, 5, 1, 'professional_male', token))

        interview_id = cursor.lastrowid
        logger.info(f"[Interview] 创建面试成功，ID: {interview_id}")

        conn.commit()
        return_db(conn)

        # 先登记后台任务（响应返回后框架自动执行出题），再立即重定向
        background_tasks.add_task(_generate_questions_business, token)

        return RedirectResponse(url=f"/static/interview.html?token={token}", status_code=302)
    except Exception as e:
        logger.error(f"[Interview] 创建面试失败: {str(e)}")
        return JSONResponse(status_code=500, content={"error": str(e)})
