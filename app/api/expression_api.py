"""
表情分析API模块
"""

import base64
import json
import logging
import time
from fastapi import Path, UploadFile, File, Body, HTTPException
from fastapi.responses import JSONResponse

from app.services.expression_service import analyze_face_expression
from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)


async def recognize_expression_api(
    image: UploadFile = File(None),
    image_url: str = Body(None),
    image_base64: str = Body(None)
):
    """
    识别表情
    
    参数:
        image: 图片文件
        image_url: 图片URL
        image_base64: 图片base64编码
    
    返回:
        表情分析结果
    """
    try:
        if image:
            image_data = await image.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif image_url:
            # 这里暂时不支持URL，因为 analyze_face_expression 只支持图像数据
            return JSONResponse(
                status_code=400,
                content={"error": "暂不支持图片URL"}
            )
        elif image_base64:
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        else:
            return JSONResponse(
                status_code=400,
                content={"error": "请提供图片文件或base64编码"}
            )
        
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except Exception as e:
        logger.error(f"[Expression] API异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def analyze_expression_api(
    image: UploadFile = File(None),
    image_url: str = Body(None),
    image_base64: str = Body(None)
):
    """
    分析表情
    
    参数:
        image: 图片文件
        image_url: 图片URL
        image_base64: 图片base64编码
    
    返回:
        表情分析结果
    """
    try:
        if image:
            image_data = await image.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif image_url:
            # 这里暂时不支持URL，因为 analyze_face_expression 只支持图像数据
            return JSONResponse(
                status_code=400,
                content={"error": "暂不支持图片URL"}
            )
        elif image_base64:
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        else:
            return JSONResponse(
                status_code=400,
                content={"error": "请提供图片文件或base64编码"}
            )
        
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except Exception as e:
        logger.error(f"[Expression] API异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def save_interview_expression(
    token: str = Path(...),
    image: UploadFile = File(None),
    image_base64: str = Body(None),
    expression: str = Body(None),
    expression_cn: str = Body(None),
    emotion_status: str = Body(None),
    emotion_score: float = Body(0),
    quality_score: float = Body(0),
    final_score: float = Body(0),
    suggestions: list = Body([])
):
    """
    保存面试表情记录
    
    参数:
        token: 面试token
        image: 图片文件
        image_base64: 图片base64编码
        expression: 表情
        expression_cn: 表情中文
        emotion_status: 情绪状态
        emotion_score: 情绪得分
        quality_score: 质量得分
        final_score: 最终得分
        suggestions: 建议
    
    返回:
        保存结果
    """
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        interview_id = interview['id']
        
        result = {}
        
        if image:
            image_data = await image.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return_db(conn)
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return_db(conn)
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif image_base64:
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return_db(conn)
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": error}
                )
            if not faces:
                return_db(conn)
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "未检测到人脸"}
                )
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif expression:
            # 直接使用前端提供的表情数据
            result = {
                'success': True,
                'expression': expression,
                'expression_cn': expression_cn or '',
                'confidence': 1.0,
                'emotion_status': emotion_status or '',
                'emotion_score': emotion_score,
                'quality_score': quality_score,
                'final_score': final_score,
                'suggestions': suggestions,
                'timestamp': int(time.time())
            }
        else:
            return_db(conn)
            return JSONResponse(
                status_code=400,
                content={"error": "请提供图片或表情数据"}
            )
        
        if result.get('success'):
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM interview_expression_records 
                WHERE interview_id = ?
            ''', (interview_id,))
            record_count = cursor.fetchone()['count']
            
            cursor.execute('''
                INSERT INTO interview_expression_records 
                (interview_id, expression, expression_cn, confidence, emotion_status, 
                 emotion_score, quality_score, final_score, suggestions, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                interview_id,
                result.get('expression', ''),
                result.get('expression_cn', ''),
                result.get('confidence', 0),
                result.get('emotion_status', ''),
                result.get('emotion_score', 0),
                result.get('quality_score', 0),
                result.get('final_score', 0),
                json.dumps(result.get('suggestions', []), ensure_ascii=False),
                result.get('timestamp', int(time.time()))
            ))
            conn.commit()
        
        return_db(conn)
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Expression] 保存异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def get_expression_report(token: str = Path(...)):
    """
    获取表情分析报告
    
    参数:
        token: 面试token
    
    返回:
        表情分析报告
    """
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")
        
        interview_id = interview['id']
        
        records = conn.execute('''
            SELECT expression, expression_cn, confidence, emotion_status, 
                   emotion_score, quality_score, final_score, suggestions, timestamp
            FROM interview_expression_records
            WHERE interview_id = ?
            ORDER BY timestamp ASC
        ''', (interview_id,)).fetchall()
        
        if not records:
            return_db(conn)
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "total_records": 0,
                    "message": "暂无表情记录"
                }
            )
        
        records_list = [dict(row) for row in records]
        
        avg_emotion_score = sum(r['emotion_score'] for r in records_list) / len(records_list)
        avg_quality_score = sum(r['quality_score'] for r in records_list) / len(records_list)
        avg_final_score = sum(r['final_score'] for r in records_list) / len(records_list)
        
        expression_counts = {}
        for r in records_list:
            expr = r['expression_cn']
            expression_counts[expr] = expression_counts.get(expr, 0) + 1
        
        positive_count = sum(1 for r in records_list if r['emotion_status'] == '积极')
        negative_count = sum(1 for r in records_list if r['emotion_status'] == '消极')
        neutral_count = sum(1 for r in records_list if r['emotion_status'] == '中性')
        
        all_suggestions = []
        for r in records_list:
            if r['suggestions']:
                try:
                    suggestions = json.loads(r['suggestions'])
                    all_suggestions.extend(suggestions)
                except:
                    pass
        
        from collections import Counter
        suggestion_counts = Counter(all_suggestions)
        top_suggestions = suggestion_counts.most_common(3)
        
        return_db(conn)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total_records": len(records_list),
                "summary": {
                    "avg_emotion_score": round(avg_emotion_score, 1),
                    "avg_quality_score": round(avg_quality_score, 1),
                    "avg_final_score": round(avg_final_score, 1),
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "neutral_count": neutral_count,
                    "expression_distribution": expression_counts
                },
                "top_suggestions": [s[0] for s in top_suggestions],
                "records": records_list
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Expression] 报告生成异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
