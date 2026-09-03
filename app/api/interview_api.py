"""
面试管理API模块
"""

import logging
import time
from fastapi import Path, Query, Body, HTTPException
from fastapi.responses import JSONResponse

from app.db.db import get_db, return_db

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
