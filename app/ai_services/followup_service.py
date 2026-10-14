"""
追问决策智能体（followup_service）
====================================
功能：观察候选人刚提交的回答，自主决定「追问」还是「放行」。

设计原则：智能体只做决策，不写数据库——INSERT 由调用方（interview_api.py）
执行。好处有两个：
1. 本模块可以单独测试（决策对不对，跟写库成功与否解耦）
2. 失败兜底简单：任何异常都返回 None（= 放行），绝不会卡死面试主流程

智能体三要素的体现（答辩口径）：
- 自主决策：followup / next 的分支由 LLM 输出的 JSON 决定，不是代码写死的 if
- 感知上下文：题目、回答全文、面试类型、已问列表，全部实时查库获得
- 使用工具：查题、查回答、统计追问次数——都是进程内 SQL 函数调用
"""

import logging
from app.config.config import LLM_MODEL #选择使用的LLM
from app.ai_services.question_service import call_llm_api

logger = logging.getLogger(__name__)

MAX_FOLLOWUP_PER_INTERVIEW = 3
MAX_TOKENS_DECISION = 300 

def decide_followup(conn,interview_id,question_id,answer_text):
    """追问决策智能体主函数

    参数:
        conn         数据库连接（调用方持有，本函数只读、不写、不 commit）
        interview_id 面试 id
        question_id  刚被回答的题目 id
        answer_text  候选人刚提交的回答全文

    返回:
        None  → 放行（回答不需要追问，或任何环节失败走兜底）
        dict  → {"question": 追问文本, "score_standard": 追问的评分标准}
                注意：只返回决策结果，写库由调用方负责（职责分离）
    """
    try:
        cur = conn.cursor()
        # ========== 当前题本身是追问题 → 不再追问（每题最多 1 次） ==========
        cur.execute(
            '''SELECT question,question_type 
            FROM interview_questions 
            WHERE id = %s''', 
            (question_id,)
        )
        question_row = cur.fetchone()
        if not question_row:
            logger.error(f"Question {question_id} not found in database")
            return None
        if question_row['question_type'] == 'followup':
            return None
        # ========== 第二道硬闸：本场追问总数 >= 3 → 不在追问 ==========
        cur.execute(
            '''SELECT COUNT(*) AS n
            FROM interview_questions 
            WHERE interview_id = %s AND question_type = 'followup' 
            ''', 
            (interview_id,)
        )
        if cur.fetchone()['n'] >= MAX_FOLLOWUP_PER_INTERVIEW:
            return None

        # ========== 感知上下文：查库拼装智能体决策所需的全部信息 ==========
        cur.execute(
            '''SELECT interview_types.name AS type_name
            FROM interviews JOIN interview_types ON interviews.interview_type_id = interview_types.id
            WHERE interviews.id = %s''',
            (interview_id,)
        )
        type_row = cur.fetchone()
        type_name = type_row['type_name'] if type_row else '通用面试'
        cur.execute(
            '''SELECT question FROM interview_questions 
            WHERE interview_id = %s ORDER BY id ASC LIMIT 20''', 
            (interview_id,)
        )
        asked = [r['question'] for r in cur.fetchall()]

        system_prompt = (
            "你是一名经验丰富的面试官，正在评估候选人刚提交的回答，决定是否需要追问。"
            "严格输出 JSON，不要输出任何其他内容。"
        )
        user_prompt = f"""【面试类型】{type_name}
        【刚刚回答的题目】{question_row['question']}
        【候选人刚提交的回答】{answer_text[:1500]}
        【本场面试准备的问题】{'； '.join(asked)}
        决策规则（按优先级判断）：
        1. 回答含糊、缺少具体细节（例如只说"做了优化"却没说怎么做的）→ 追问，挖具体做法或数据
        2. 回答与题目明显跑偏 → 追问拉回主题
        3. 回答自相矛盾或真实性存疑（项目细节说不清、数据夸大）→ 追问验证
        4. 回答完整、具体、切题 → 放行
        5. 如果候选人回答的对象本身已是追问，一律放行（正常情况下代码硬闸已拦截）

        追问要求：只有一个问题；口语化自然，像真人面试官；不超过 60 字；不得与已问问题重复。

        严格输出 JSON：
        需要追问：{{"action": "followup",
        "text": "追问内容", 
        "score_standard": "这条追问考察什么、好的回答长什么样（50字内）"}}

        放行：{{"action": "next"}}"""

        # temperature 由 call_llm_api 内部固定 0.7（追问文本需要多样性，可接受）
        decision = call_llm_api(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=MAX_TOKENS_DECISION,
        )
        # ========== 解析决策结果（只要没catch住的问题全放行，避免问题））
        # 1) 调用失败/解析失败 → call_llm_api 返回 None → 放行
        # 2) action 不是 followup → 放行
        # 3) 追问文本为空 → 放行（防止插进一条空题）
        if not decision or decision.get("action") !="followup":
            return None
        text =(decision.get("text") or "").strip()
        if not text:
            return None
        return {"question": text, 
                "score_standard": (decision.get("score_standard") or 
                                "考察回答的真实性与深度").strip(),
                }
    except Exception as e:

        logger.error(f"[followup] 决策智能体失败，放行{e}")
        return None
