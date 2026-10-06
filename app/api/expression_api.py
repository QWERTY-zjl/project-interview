"""
表情分析API模块
================
面试中摄像头抓拍的表情/情绪分析接口：
1. /api/expression/analyze          —— 分析单张图片（前端每 5 秒抓拍上报，不存库）
2. /api/interview/{token}/expression —— 把表情数据保存进 interview_expression_records 表
3. /api/interview/{token}/expression_report —— 聚合某场面试的表情记录

【2026-10-06 修复 400】原接口签名混用 File(None) + 多个 Body(None) 散参数：
FastAPI 的规则是——只要函数里有 UploadFile/File 参数，整个请求就按
multipart/form-data 解析，此时散装 Body 参数也从表单里找值，而不是从
JSON body 里找。前端用 axios 发的是 application/json，所以所有字段
永远收不到 → 100% 触发 400「请提供图片」。
现在统一改为纯 JSON 接口（单标量 Body 加 embed=True，多标量 Body 组合
成 JSON 对象），与前端发法一致。

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

import base64
import json
import logging
import time
from collections import Counter

from fastapi import APIRouter, Path, Body, HTTPException
from fastapi.responses import JSONResponse

from app.ai_services.expression_service import analyze_face_expression
from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)

# 表情分析路由：本文件所有表情接口共用
router = APIRouter(tags=["表情分析"])


@router.post("/api/expression/analyze", summary="分析表情")
async def analyze_expression_api(image_base64: str = Body(None, embed=True)):
    """分析图片中的表情（面试抓拍上报用，结果不存库）

    Args:
        image_base64: 图片base64编码（支持 dataURL 全串，前端 canvas.toDataURL 原样传入；
                      单标量 Body 必须加 embed=True，否则 FastAPI 要求裸 JSON 值导致 422）

    Returns:
        JSONResponse: {"success": True, "expression": 表情, "expression_cn": 表情中文名,
                       "emotion_status": 情绪状态, "emotion_score": 情绪得分, ...}
        400 "未检测到人脸" 是正常业务响应（画面里没人脸，如用户离开座位），
        前端据此静默更新面板文案，不当作错误刷屏
    """
    try:
        if not image_base64:
            return JSONResponse(
                status_code=400,
                content={"error": "请提供图片base64编码"}
            )
        # dataURL 形如 "data:image/jpeg;base64,xxxx"——只留逗号后的纯 base64 部分
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
        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.error(f"[Expression] API异常: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/interview/{token}/expression", summary="保存面试表情")
async def save_interview_expression(
    token: str = Path(...),
    expression: str = Body(None),
    expression_cn: str = Body(None),
    emotion_status: str = Body(None),
    emotion_score: float = Body(0),
    quality_score: float = Body(0),
    final_score: float = Body(0),
    suggestions: list = Body([]),
    image_base64: str = Body(None)
):
    """保存面试表情记录到 interview_expression_records 表

    数据来源两选一（优先级从上到下）：
    1. expression 非空：前端把 /analyze 的识别结果原样转交——直接入库，
       不再重复调用大模型（原实现 image_base64 优先，导致同一次抓拍
       识别两次、费钱且慢，2026-10-06 调整为复用结果优先）
    2. image_base64 非空：现场识别后再入库（兼容直接传图的调用方）

    Args:
        token: 面试token（路径参数），一场面试的对外门牌号
        expression: 表情名（前端转交的分析结果）
        expression_cn: 表情中文名
        emotion_status: 情绪状态（积极/中性/消极）
        emotion_score: 情绪得分
        quality_score: 质量得分
        final_score: 最终得分
        suggestions: 改进建议列表
        image_base64: 图片base64编码（仅在没转交结果时用于现场识别）

    Returns:
        JSONResponse: {"success": True, "expression": 表情, ...}，记录已入库
    """
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()

        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        interview_id = interview['id']
        result = {}

        if expression:
            # 路径 1：前端转交的识别结果，直接采用（省一次重复的模型调用）
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
        elif image_base64:
            # 路径 2：没有现成结果，现场识别（兼容直接传图的调用方）
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
        else:
            return_db(conn)
            return JSONResponse(
                status_code=400,
                content={"error": "请提供表情数据或图片base64编码"}
            )

        if result.get('success'):
            cursor = conn.cursor()
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


@router.get("/api/interview/{token}/expression_report", summary="获取表情报告")
async def get_expression_report(token: str = Path(...)):
    """获取面试表情分析报告

    Args:
        token: 面试token（路径参数）

    Returns:
        JSONResponse: {"success": True, "total_records": 记录数, "summary": 平均分与表情分布统计, "top_suggestions": 高频建议, "records": 表情记录明细}
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
                except Exception:
                    pass

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
