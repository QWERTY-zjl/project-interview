"""
面试报告API模块
================
面试收尾环节的评估报告生成接口。

【为什么单独一个文件】评估报告是独立于"出题"（interview_api）和"支付"（payment_api）
的业务线：按 token 找面试 → 联查候选人/岗位 → 取问题与回答 → 聚合表情数据 →
调 report_service.generate_interview_report 让大模型逐题评分 → 报告存库。
"""

import logging
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.db.db import get_db, return_db

logger = logging.getLogger(__name__)

# 面试报告路由：本文件所有报告接口共用
router = APIRouter(tags=["面试报告"])


@router.post("/api/evaluation/generate", summary="生成面试评价报告")
def generate_evaluation(token: str = Body(None)):
    """生成面试评价报告（面试收尾环节，前端答完全部问题后调用）

    Args:
        token: 面试token

    Returns:
        JSONResponse: {"status": "success", "evaluation": 前端评价字段, "report": 完整存档报告}
    """
    conn = None
    try:
        # 函数内导入（与项目其他 ai_services 模块的导入惯例一致）
        from app.ai_services.report_service import generate_interview_report

        if not token:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "缺少token参数"}
            )

        conn = get_db()
        cursor = conn.cursor()

        # 查面试记录
        cursor.execute("SELECT id FROM interviews WHERE token = ?", (token,))
        interview = cursor.fetchone()

        if not interview:
            return_db(conn)
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "面试记录不存在"}
            )

        interview_id = interview['id']

        # 个人版单用户，无候选人/岗位表（candidates/positions 为企业版遗留，已清理）。
        # 简历原文未入库，评估提示词只使用问题回答与表情数据；
        # 占位结构与 generate_questions 的个人版模拟数据保持一致
        candidate = {"name": "个人用户", "resume_content": ""}
        position = {"name": "模拟面试"}

        # 查问题+回答（score_standard 回传给大模型当评分依据）
        cursor.execute('''
            SELECT question, score_standard, answer_text
            FROM interview_questions WHERE interview_id = ? ORDER BY id
        ''', (interview_id,))
        questions = [dict(r) for r in cursor.fetchall()]

        if not questions:
            return_db(conn)
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "面试没有回答记录"}
            )

        # 聚合表情数据（emotion_status 取值为中文：积极/中性/消极）
        expression_summary = None
        cursor.execute('''
            SELECT COUNT(*) AS total_records,
                   AVG(emotion_score) AS avg_emotion_score,
                   AVG(quality_score) AS avg_quality_score,
                   AVG(final_score) AS avg_final_score,
                   SUM(CASE WHEN emotion_status = '积极' THEN 1 ELSE 0 END) AS positive_count,
                   SUM(CASE WHEN emotion_status = '中性' THEN 1 ELSE 0 END) AS neutral_count,
                   SUM(CASE WHEN emotion_status = '消极' THEN 1 ELSE 0 END) AS negative_count
            FROM interview_expression_records WHERE interview_id = ?
        ''', (interview_id,))
        agg = cursor.fetchone()

        if agg and agg['total_records']:
            # 表情分布：{表情中文名: 出现次数}
            cursor.execute('''
                SELECT expression_cn, COUNT(*) AS cnt
                FROM interview_expression_records WHERE interview_id = ?
                GROUP BY expression_cn
            ''', (interview_id,))
            distribution = {r['expression_cn']: r['cnt'] for r in cursor.fetchall()}
            expression_summary = {
                "total_records": agg['total_records'],
                "avg_emotion_score": round(agg['avg_emotion_score'] or 0, 1),
                "avg_quality_score": round(agg['avg_quality_score'] or 0, 1),
                "avg_final_score": round(agg['avg_final_score'] or 0, 1),
                "positive_count": agg['positive_count'] or 0,
                "neutral_count": agg['neutral_count'] or 0,
                "negative_count": agg['negative_count'] or 0,
                "expression_distribution": distribution
            }

        # 报告生成（service 层返回 (dict, 状态码) 元组，内部会 commit、归还连接、
        # 把面试状态推进到 4；这里只负责把业务结果打包成 HTTP 响应）
        result, code = generate_interview_report(
            interview_id,
            candidate, position, questions, expression_summary, cursor, conn
        )
        return JSONResponse(status_code=code, content=result)

    except Exception as e:
        # 异常时归还连接（generate_interview_report 成功路径内部已归还，此处兜底）
        if conn:
            try:
                return_db(conn)
            except Exception:
                pass
        logger.error(f"[Evaluation] 生成评价失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )
