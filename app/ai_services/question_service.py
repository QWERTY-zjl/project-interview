"""
面试问题生成服务模块
====================
本模块负责调用prompt.py文件中的build_interview_prompt函数生成面试问题
基于阿里云 DashScope qwen-flash 文本模型（OpenAI 兼容接口）
简历由 resume_parser.py 解析成 markdown 文本后作为上下文传入（不再使用多模态截图）
"""

import json
import logging
import re

from openai import OpenAI

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, LLM_MODEL
from app.ai_services.speech_service import synthesize_speech
from app.ai_services.prompt import build_interview_prompt, get_default_questions


logger = logging.getLogger(__name__)# 日志记录器，用于记录程序运行时的事件和错误信息显示在控制台

# 匹配 ```json ... ``` 围栏（部分模型不遵守 response_format 时会带围栏返回）
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# DashScope 客户端懒加载单例（避免模块导入时就构造，防止未配置 key 时直接报错）
_client = None


def _get_client():
    """获取 DashScope（OpenAI 兼容）客户端，首次调用时创建"""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
        )
    return _client


def _parse_json_content(content):
    """
    解析大模型返回的 JSON 文本

    Args:
        content: 大模型返回的文本

    Returns:
        dict: 解析结果，失败时返回 None
    """
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        pass
    # 直接解析失败时，先剥掉 ```json 围栏再试一次
    if content:
        stripped = _JSON_FENCE_RE.sub("", content).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    logger.error("[Question] 返回内容不是合法 JSON")
    return None


def call_llm_api(messages, max_tokens=2000):
    """
    调用阿里云 DashScope 大模型 API（OpenAI 兼容接口，文本模型）

    Args: 参数说明
        messages: OpenAI 格式的消息列表 [{"role": ..., "content": ...}, ...]
        max_tokens: 最大生成 token 数

    Returns:
        dict: API 返回的 JSON 结果，失败时返回 None
    """
    import os# 函数内导入，避免顶层依赖顺序问题

    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        logger.warning("[Question] 未配置DASHSCOPE_API_KEY")
        return None

    try:
        response = _get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            logger.error("[Question] 响应缺少content字段")
            return None

        # 解析返回的 JSON
        return _parse_json_content(content)
    except Exception as e:
        logger.error(f"[Question] API调用失败: {e}")
        return None


def validate_questions(questions):
    """
    验证并格式化问题列表

    Args:
        questions: 大模型返回的问题列表

    Returns:
        list: 验证通过的问题列表，失败时返回 None
    """
    if not questions or not isinstance(questions, list):
        return None

    valid = []
    for q in questions:
        # 检查问题格式
        if not isinstance(q, dict) or 'question' not in q:
            continue

        # 格式化问题
        validated = {
            'question': q.get('question', ''),
            'score_standard': q.get('score_standard', '考察候选人的专业能力和经验'),
            'question_type': q.get('question_type', 'voice')
        }
        valid.append(validated)

    # 限制最多5个问题
    return valid[:5] if valid else None


def save_questions_to_db(cursor, interview_id, questions, voice_type):
    """
    保存问题到数据库并预生成语音

    Args:
        cursor: 数据库游标
        interview_id: 面试ID
        questions: 问题列表
        voice_type: 音色类型

    Returns:
        int: 成功保存的问题数量
    """
    saved_count = 0

    for q in questions:
        try:
            # 预生成语音
            audio_data, _ = synthesize_speech(q['question'], voice_type)

            # 保存到数据库
            cursor.execute('''
                INSERT INTO interview_questions
                (interview_id, question, score_standard, question_type, question_audio, voice_type)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (interview_id, q['question'], q['score_standard'], q['question_type'], audio_data, voice_type))
            saved_count += 1
        except Exception as e:
            logger.error(f"[Question] 保存问题失败: {e}")

    return saved_count


def generate_questions(interview_id, candidate, position, interview, latest_tech_info, cursor, conn, resume_md=None):
    """
    生成面试问题的主函数

    Args:
        interview_id: 面试ID
        candidate: 候选人信息
        position: 职位信息
        interview: 面试信息
        latest_tech_info: 简历分析结果
        cursor: 数据库游标
        conn: 数据库连接
        resume_md: 简历解析出的 markdown 文本（可选，由 MinerU/PyPDF2 生成）

    Returns:
        dict: 包含状态、消息和问题列表的响应字典
    """
    logger.info("[Question] 开始生成面试问题")

    try:
        # 1. 构建 prompt 并调用大模型
        messages = build_interview_prompt(candidate, position, latest_tech_info or "")
        if resume_md:
            # 把简历 markdown 追加到最后的 user 消息，让出题贴合候选人真实经历
            messages[-1]["content"] += f"\n\n候选人简历原文（Markdown）：\n{resume_md}"
        llm_result = call_llm_api(messages)

        # 2. 获取并验证问题列表
        questions = None
        if llm_result and 'questions' in llm_result:
            questions = validate_questions(llm_result['questions'])

        # 3. 如果没有有效问题，使用默认问题
        if not questions:
            logger.warning("[Question] 使用默认问题")
            questions = get_default_questions()

        # 4. 保存到数据库
        voice_type = interview.get('voice_type', 'professional_male')
        saved_count = save_questions_to_db(cursor, interview_id, questions, voice_type)

        # 5. 更新面试状态
        cursor.execute('UPDATE interviews SET status = 1, question_count = ? WHERE id = ?',
                      (saved_count, interview_id))
        conn.commit()

        logger.info(f"[Question] 完成，保存{saved_count}个问题")

        return {
            "status": "success",
            "message": f"成功生成{saved_count}个面试问题",
            "questions": questions
        }

    except Exception as e:
        logger.error(f"[Question] 生成失败: {e}")
        # 发生错误时返回默认问题，确保面试能继续进行
        return {
            "status": "success",
            "message": "生成面试问题完成（使用默认问题）",
            "questions": get_default_questions()
        }
