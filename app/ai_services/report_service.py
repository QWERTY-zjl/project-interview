"""
面试报告生成服务模块
====================
本模块负责生成面试报告：把面试问题、候选人回答、表情情绪数据打包成提示词，
交给大模型逐题评分并给出综合评价，结果以 JSON 存入 interviews.report_content

【模块定位】面试收尾环节的"报告生成器"：
候选人答完全部问题后（interviews.status 更新为 3，见 server.py 的 submit_text_answer
里"全部已回答"的判断），前端调用 /api/evaluation/generate，由 server.py 聚合好
问题/回答/表情数据后调用本模块的 generate_interview_report()，
大模型逐题评分并给出综合评价，结果存入 interviews.report_content，
状态推进到 4（报告已生成）。
状态流转：1 已出题 → 2 面试中 → 3 已答完 → 4 报告已生成

【与出题流程（question_service）的配置一致性】
统一走 DashScope 的 OpenAI 兼容端点（DASHSCOPE_BASE_URL + DASHSCOPE_API_KEY），
模型统一用 LLM_MODEL（默认 qwen-flash）——个人版成本优先：qwen-flash 是百炼
上最便宜的合理选择（输入 0.15 元/百万 token），且支持 JSON 输出与结构化评分

【一次返回两个视图】
  - evaluation：前端报告页直接使用的字段（averageScore/scores/detailedScores/
                strengths/improvements/recommendations，与 interview.html 的
                渲染字段一一对应，替换掉旧版 server.py 内联实现时保持兼容）
  - report：完整存档（evaluation + 逐题评价 + 环境信息 + 生成时间），
            序列化后存入 report_content，供后台查阅历史报告
"""

import time        # 标准库：time.time() 生成 Unix 时间戳，作为报告的 generated_at 字段
import json        # 标准库：序列化报告存库 / 解析大模型返回的 JSON
import re          # 标准库：正则剥掉模型返回里可能出现的 ```json 围栏
import os          # 标准库：读环境变量 DASHSCOPE_API_KEY（.env 由启动脚本加载进环境）
import requests    # 第三方 HTTP 库：调用大模型接口（server.py 等模块已在用，无新增依赖）
from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, LLM_MODEL
# ↑ 三个配置来自 app/config/config.py（从 .env 读取），与 question_service 完全一致：
#   DASHSCOPE_API_KEY  -> 阿里云百炼平台 API 密钥（鉴权用，只存 .env，不入代码库）
#   DASHSCOPE_BASE_URL -> DashScope 的 OpenAI 兼容端点，拼 /chat/completions 得完整地址
#   LLM_MODEL          -> 模型名（默认 qwen-flash），出题和报告统一用它，换模型只改 .env
from app.db.db import return_db
# ↑ 数据库辅助函数：关闭连接并从全局连接池 _connections 中移除。
#   本模块在"成功返回前"和"每个失败分支"都调用它——
#   若忘记调用，连接对象会一直挂在池里造成泄漏，所以失败路径也要归还

# 匹配 ```json ... ``` 的md围栏（部分模型不遵守 response_format 时会带markdown格式的围栏返回）
# 与 question_service 的兜底策略相同：直接解析失败时，剥掉围栏再试一次
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json_content(content):
    """
    解析大模型返回的 JSON 文本（两步兜底）

    Args:
        content: 大模型返回的文本。来源：下方 result['choices'][0]['message']['content']

    Returns:
        dict: 解析结果，失败时返回 None
    """
    try:
        return json.loads(content)# 第一步：直接按 JSON 解析
    except (TypeError, json.JSONDecodeError):
        pass
    if content:
        stripped = _JSON_FENCE_RE.sub("", content).strip()# 第二步：剥掉围栏再解析
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    print("[Report] 返回内容不是合法 JSON")
    return None


def _get_default_evaluation():
    """兜底评价结构：大模型返回缺字段时补齐，保证前端渲染不出现 undefined

    只做浅层合并（顶层键），嵌套结构以默认值整体兜底——
    宁可显示空数据也不让报告页崩溃，与项目"失败不中断"的设计一致
    """
    return {
        "averageScore": 0,
        "description": "本次面试评价生成不完整，请联系面试官查看详细记录。",
        "scores": {"professional": 0, "communication": 0, "comprehensive": 0},
        "detailedScores": [],
        "strengths": [],
        "improvements": [],
        "recommendations": [],
        "recommendation": "可以考虑"
    }


def generate_interview_report(interview_id, candidate, position, questions, expression_summary, cursor, conn):
    """
    生成面试报告
    设计流程：拼评估提示词 → 调大模型逐题评分 → 解析 JSON → 存入 interviews 表

    参数:
        interview_id: 面试ID。来源：interviews 表主键，标识本次评估属于哪场面试
        candidate: 候选人信息 dict。来源：candidates 表中该候选人的记录，
                   这里用 name（姓名）和 resume_content（简历文件二进制，
                   仅判断有无简历，不直接进提示词）
        position: 职位信息 dict。来源：positions 表（经 candidates.position_id 关联查出），
                  这里用 name（岗位名称）
        questions: 面试问题列表。来源：interview_questions 表按 interview_id 查出，
                   每项需含 question（问题）、score_standard（评分标准）、
                   answer_text（候选人回答文本）三个字段
        expression_summary: 表情分析摘要 dict。来源：server.py 对
                            interview_expression_records 表按 interview_id 聚合而成
                            （emotion_status 取值为中文：积极/中性/消极），
                            含 total_records / avg_emotion_score / avg_quality_score /
                            avg_final_score / positive_count / neutral_count /
                            negative_count / expression_distribution 八个字段；
                            无记录时为 None（如摄像头未开启），此时不纳入评估
        cursor: 数据库游标。来源：server.py 的 SQLite 连接，用于 UPDATE 报告内容
        conn: 数据库连接对象。来源：同上，用于 commit 和归还连接池

    返回:
        (dict, 状态码) 元组: 成功时含 evaluation（前端视图）和 report（完整存档）；
                  大模型调用/解析失败时返回 500 错误
                  （与 question_service 的"失败兜底"不同，本函数失败直接报错，
                  因为报告没有"默认报告"可用，失败必须让调用方感知）
                  注意：本函数只负责业务，不直接构造 HTTP 响应——
                  (dict, code) 由调用方（FastAPI 路由层）打包成 JSONResponse
    """
    # 先检查密钥：没配置就不发请求，直接返回 500（省一次注定失败的调用）
    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        return_db(conn)
        return {"error": "未配置DASHSCOPE_API_KEY"}, 500

    # 检查是否有简历
    # resume_content 是简历文件的二进制（BLOB）；有无简历决定提示词里是否附加简历背景段落
    has_resume = False
    if candidate.get('resume_content'):
        has_resume = True
        print(f"[Report] 候选人 {candidate['name']} 有简历")
    else:
        print(f"[Report] 候选人 {candidate['name']} 无简历")

    # 提示词第一部分：任务设定（角色 + 评估对象 + 评分规则）
    prompt = f"""你是一位专业的面试评估专家，需要对候选人"{candidate['name']}"应聘"{position['name']}"职位的面试表现进行评估。
请根据以下面试问题和候选人的回答，对每个问题进行评分和点评，并给出综合评价。
注意每个问题评分范围是0-100分，综合评分范围是0-100分。

"""

    # 添加简历信息
    # 有简历时提醒模型"结合背景评估"——比如候选人简历写熟悉某技术，回答却答反了，应扣分
    # （resume_content 是原始文件二进制无法直接进提示词，只传"已提供"状态）
    if has_resume:
        prompt += f"""
【候选人简历】
- 候选人姓名: {candidate['name']}
- 应聘职位: {position['name']}
- 简历状态: 已提供

请在评估时参考候选人的简历背景，结合面试表现给出更全面的评价。

"""

    # 逐题追加"问题 + 评分标准 + 回答"三要素
    # 评分标准是出题时生成的，这里回传给模型，让它按同一把尺子打分，评分才有依据
    # q.get(..., '未提供')：某字段缺失时给占位文案，避免提示词出现 None 或 KeyError
    for i, q in enumerate(questions, 1):
        # ↑ enumerate(..., 1)：从 1 开始编号，编号同时用于 JSON 返回里的 "id" 字段
        prompt += f"""问题{i}: {q.get('question', '未提供问题')}
评分标准: {q.get('score_standard', '未提供评分标准')}
候选人回答: {q.get('answer_text', '未提供回答')}

"""

    # 表情情绪数据：作为"情绪管理能力"维度的量化依据
    # 只有确实采集到了表情数据才附加，否则让模型凭空编会失真
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

请将表情与情绪分析数据纳入综合评估，作为"情绪管理"维度的评分依据。

"""

    # 提示词最后部分：规定返回 JSON 的结构和示例
    # 字段名与前端 interview.html 报告页的渲染字段一一对应（averageScore/scores/
    # detailedScores/strengths/improvements/recommendations），
    # 前端拿到 evaluation 可直接展开使用，无需二次转换；
    # question_evaluations/recommendation 为存档扩展字段，前端不渲染但不影响
    prompt += """请以JSON格式返回评估结果，包含以下内容：
1. 每个问题的评分(0-100)和评价
2. 综合评分 averageScore(0-100)和总体评价 description
3. 三大能力分 scores：professional(专业能力)/communication(沟通能力)/comprehensive(综合素养)，均为0-100
4. 细分能力 detailedScores：每项含 name(能力名)/score(0-10分)/percentage(0-100)，
   建议涵盖专业知识、表达能力、沟通能力、思维逻辑，有表情数据时增加情绪管理
5. 优势亮点 strengths：3-5条
6. 改进建议 improvements：3-5条
7. AI个性化建议 recommendations：3条，每条含 title 和 description
8. 录用建议 recommendation：推荐录用/可以考虑/不建议录用

重要：question_evaluations 只输出题号(id)、评分(score)、评语(comments)三个字段，
【严禁】复述题目原文、评分标准或回答原文——系统会自动从数据库回填，复述会把
输出撑到超长导致 JSON 被截断、解析失败（2026-10-07 实测踩坑）。

JSON格式示例:
{
    "question_evaluations": [
        {"id": 1, "score": 85, "comments": "回答详细..."}
    ],
    "averageScore": 85,
    "description": "候选人整体表现良好...",
    "scores": {"professional": 85, "communication": 80, "comprehensive": 83},
    "detailedScores": [
        {"name": "专业知识", "score": 8.5, "percentage": 85},
        {"name": "表达能力", "score": 8.0, "percentage": 80}
    ],
    "strengths": ["基础知识扎实...", "..."],
    "improvements": ["某些领域深度不够...", "..."],
    "recommendations": [{"title": "学习提升", "description": "建议学习..."}],
    "recommendation": "推荐录用"
}"""

    # 完整请求地址 = 基地址 + OpenAI 兼容的对话补全路径
    url = f"{DASHSCOPE_BASE_URL}/chat/completions"
    data = {
        # 模型统一走 config 的 LLM_MODEL（默认 qwen-flash）：
        # qwen-flash 是百炼上最便宜的合理选择（输入 0.15 元/百万 token，Qwen3 支持 JSON 输出），
        # 个人版以成本优先，出题和报告统一用一个模型，以后换模型只改 .env 一处
        "model": LLM_MODEL,
        "messages": [
            # system 定评估专家角色并强调 JSON 输出；user 放全部评估素材
            {"role": "system", "content": "你是一位专业的面试评估专家，负责评估技术面试表现。请返回JSON格式。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 6000,  # 综合评估+逐题评语输出较长；6000 防止 JSON 被截断
                             #（逐题原文回显时代 3000 曾实测截断导致解析失败，改精简输出后
                             #  仍留足余量；qwen-flash 最大输出 8192）
        "temperature": 0.7,  # 评估需要稳定：温度过高会让评分大幅波动
        # 指定 JSON 响应格式，方便直接 json.loads 解析
        "response_format": {"type": "json_object"}
    }

    headers = {
        # Bearer 认证：OpenAI 兼容接口的标准鉴权方式，密钥放请求头不进 URL（防日志泄露）
        "Authorization": f"Bearer {os.getenv('DASHSCOPE_API_KEY') or DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"# 请求体是 JSON，必须声明否则服务端可能解析失败
    }

    try:
        # timeout=120：报告要逐题评分，生成耗时远长于出题，给足 2 分钟；
        # 不设 timeout 的话，网络挂起会让整个请求线程永久卡死
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()  # 自动处理HTTP错误：4xx/5xx 状态码直接抛异常，进入下方 except
        result = response.json()     # 响应体本身也是 JSON（OpenAI 格式），先解析成字典
        result_text = result['choices'][0]['message']['content']
        # ↑ OpenAI 响应结构：choices[0] 取第一个候选回复，.message.content 是模型生成的评估 JSON 文本
    except requests.RequestException as e:
        # 网络错误、超时、HTTP 4xx/5xx 都会进这里
        print(f"[Report] 调用大模型失败: {e}")
        return_db(conn)# 失败也要归还数据库连接，否则连接池泄漏
        return {"error": f"调用大模型失败: {str(e)}"}, 500
        # ↑ 500：服务端错误，前端收到后会走本地默认评价兜底

    # 解析大模型响应（两步兜底：直接解析失败则剥围栏重试）
    evaluation_result = _parse_json_content(result_text)
    if not evaluation_result:
        print("[Report] 解析大模型响应失败")
        return_db(conn)
        return {"error": "解析大模型响应失败"}, 500

    # 与兜底结构浅合并：模型漏字段时补默认值，保证前端渲染不出现 undefined
    evaluation = {**_get_default_evaluation(), **evaluation_result}

    # 回填逐题原文：模型按约定只输出 id/score/comments（防输出截断），
    # 题目、评分标准、回答原文从 questions（进函数前查好的）按题号拼回，
    # 保证存档报告的 question_evaluations 字段完整，后续渲染逐题详情不缺数据
    for idx, qe in enumerate(evaluation.get('question_evaluations', []) or [], 1):
        # 优先按模型给的题号(id)对应；漏给 id 时退回按列表顺序对齐
        q_idx = qe.get('id') or idx
        if isinstance(q_idx, int) and 1 <= q_idx <= len(questions):
            q = questions[q_idx - 1]
            qe.setdefault('question', q.get('question', ''))
            qe.setdefault('score_standard', q.get('score_standard', ''))
            qe.setdefault('answer', q.get('answer_text', ''))

    # 组装报告数据：环境信息（谁、什么岗位）+ 评估结果 + 生成时间
    report_data = {
        "interview_id": interview_id,
        "candidate_name": candidate['name'],
        "position_name": position['name'],
        "evaluation": evaluation,# 大模型返回的逐题评分与综合评价
        "generated_at": int(time.time())# Unix 时间戳（秒），前端可格式化展示
    }

    # 保存报告到数据库
    # status=4 表示"报告已生成"（面试状态机的最终阶段）；
    # 报告整体 JSON 序列化后存入单列，读取时再反序列化，无需为报告建单独的表
    cursor.execute('''
        UPDATE interviews SET status = 4, report_content = %s WHERE id = %s
    ''', (json.dumps(report_data, ensure_ascii=False), interview_id))
    # ↑ ensure_ascii=False：中文原样存储，而不是 \uXXXX 转义，人读库时可直接看懂

    conn.commit()# PG autocommit 下 UPDATE 已自动提交；commit() 保留为兼容写法，无害
    return_db(conn)# 用完归还连接（关闭并移出连接池）

    return {
        "status": "success",
        "message": "面试报告生成成功",
        "evaluation": evaluation,# 前端报告页直接使用的评价字段
        "report": report_data# 完整存档（含逐题评价、环境信息、生成时间）
    }, 200
