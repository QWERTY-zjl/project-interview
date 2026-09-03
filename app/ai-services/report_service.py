"""
面试报告生成服务模块
====================
本模块负责生成面试报告
"""

import time
import urllib.request
import json
from flask import jsonify
from app.config.config import OPENAI_API_KEY, OPENAI_BASE_URL
from app.db.db import return_db


def generate_interview_report(interview_id, interview, candidate, position, questions, expression_summary, cursor, conn):
    """
    生成面试报告
    
    参数:
        interview_id: 面试ID
        interview: 面试信息
        candidate: 候选人信息
        position: 职位信息
        questions: 面试问题列表
        expression_summary: 表情分析摘要
        cursor: 数据库游标
        conn: 数据库连接
    
    返回:
        JSON响应
    """
    # 检查是否有简历
    has_resume = False
    if candidate.get('resume_content'):
        has_resume = True
        print(f"[DEBUG] 候选人 {candidate['name']} 有简历")
    else:
        print(f"[DEBUG] 候选人 {candidate['name']} 无简历")
    
    prompt = f"""你是一位专业的面试评估专家，需要对候选人"{candidate['name']}"应聘"{position['name']}"职位的面试表现进行评估。
面试官是{interview['interviewer']}。

请根据以下面试问题和候选人的回答，对每个问题进行评分和点评，并给出综合评价。
注意每个问题评分范围是0-100分，综合评分范围是0-100分。

"""
    
    # 添加简历信息
    if has_resume:
        prompt += f"""
【候选人简历】
- 候选人姓名: {candidate['name']}
- 应聘职位: {position['name']}
- 简历状态: 已提供

请在评估时参考候选人的简历背景，结合面试表现给出更全面的评价。

"""
    
    for i, q in enumerate(questions, 1):
        prompt += f"""问题{i}: {q.get('question', '未提供问题')}
评分标准: {q.get('score_standard', '未提供评分标准')}
候选人回答: {q.get('answer_text', '未提供回答')}

"""
    
    if expression_summary:
        prompt += f"""
【表情与情绪分析数据】
- 总记录数: {expression_summary['total_records']}次
- 平均情绪评分: {expression_summary['avg_emotion_score']}分
- 平均表情质量评分: {expression_summary['avg_quality_score']}分
- 平均综合评分: {expression_summary['avg_final_score']}分
- 积极情绪次数: {expression_summary['positive_count']}次
- 中性情绪次数: {expression_summary['neutral_count']}次
- 消极情绪次数: {expression_summary['negative_count']}次
- 表情分布: {expression_summary['expression_distribution']}

请将表情与情绪分析数据纳入综合评估，作为"情绪管理能力"的评分依据。

"""
    
    prompt += """请以JSON格式返回评估结果，包含以下内容：
1. 每个问题的评分和评价
2. 技术能力总分(满分100)
3. 沟通能力总分(满分100)
4. 情绪管理能力总分(满分100，基于表情与情绪分析数据)
5. 综合评分(满分100，综合以上各项)
6. 面试官评语(综合评价候选人的优缺点)
7. 录用建议(推荐录用/可以考虑/不建议录用)

JSON格式示例:
{
    "question_evaluations": [
        {"id": 1, "question": "[question]", "score_standard": "[score_standard]", "answer": "[answer_text]", "score": 85, "comments": "回答详细..."}
    ],
    "technical_score": 88,
    "communication_score": 90,
    "emotion_score": 75,
    "overall_score": 85,
    "comments": "候选人技术基础扎实...",
    "recommendation": "推荐录用"
}"""
    
    url = f"{OPENAI_BASE_URL}/chat/completions"
    data = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": "你是一位专业的面试评估专家，负责评估技术面试表现。请返回JSON格式。"},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    
    # 使用requests库发送请求，比urllib更简洁高效
    import requests
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()  # 自动处理HTTP错误
        result = response.json()
        result_text = result['choices'][0]['message']['content']
    except requests.RequestException as e:
        print(f"[ERROR] 调用大模型失败: {e}")
        return_db(conn)
        return jsonify({"error": f"调用大模型失败: {str(e)}"}), 500
    
    # 解析大模型响应
    try:
        evaluation_result = json.loads(result_text)
    except json.JSONDecodeError as e:
        print(f"[ERROR] 解析大模型响应失败: {e}")
        return_db(conn)
        return jsonify({"error": "解析大模型响应失败"}), 500
    
    report_data = {
        "interview_id": interview_id,
        "candidate_name": candidate['name'],
        "position_name": position['name'],
        "interviewer": interview['interviewer'],
        "evaluation": evaluation_result,
        "generated_at": int(time.time())
    }
    
    # 保存报告到数据库
    cursor.execute('''
        UPDATE interviews SET status = 4, report_content = ? WHERE id = ?
    ''', (json.dumps(report_data), interview_id))
    
    conn.commit()
    return_db(conn)
    
    return jsonify({
        "status": "success",
        "message": "面试报告生成成功",
        "report": report_data
    })
