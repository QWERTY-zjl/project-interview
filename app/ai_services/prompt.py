"""
记录生成不同岗位的提示词，将其送给大模型生成面试问题
采用openai格式
"""
import os
import json
from openai import OpenAI

# 配置 OpenAI API 密钥（建议通过环境变量注入，避免硬编码）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-xxxx")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def get_default_questions():
    """
    获取默认的面试问题

    当大模型调用失败时使用此函数返回默认问题

    Returns:
        list: 包含5个默认问题的列表
    """
    default_q = {
        "question": "大模型调用失败",
        "score_standard": "大模型调用失败",
        "question_type": "voice"
    }
    return [default_q.copy() for _ in range(5)]


def build_interview_prompt(candidate: dict, position: dict, resume_analysis: str = "") -> list:
    """
    构建 OpenAI 格式（messages 列表）的提示词，用于生成面试问题

    Args:
        candidate: 候选人信息字典，如 {"name": "张三", "experience": "3年"}
        position: 职位信息字典，如 {"name": "Web开发工程师", "requirements": "...", "responsibilities": "..."}
        resume_analysis: 简历分析结果文本（可选）

    Returns:
        list: OpenAI Chat Completions 接口的 messages 列表
    """
    system_prompt = (
        f"你是一位资深的{position.get('name', '未提供')}的面试官，擅长根据候选人简历和岗位需求生成针对性的面试问题。"#未提供是为了防止没有岗位名称时的err
        "要求问题专业、有区分度，并给出评分标准。"
        "必须以 JSON 格式返回，结构为："
        '{"questions": [{"question": "问题内容", "score_standard": "评分标准", "question_type": "voice"}]}'# question_type为voice表示语音问题
    )

    user_prompt = (
        f"候选人信息：\n"
        f"- 姓名：{candidate.get('name', '未提供')}\n"
        f"- 工作经验：{candidate.get('experience', '未提供')}\n\n"
        f"应聘职位：{position.get('name', '未提供')}\n"
        f"岗位要求：{position.get('requirements', '未提供')}\n"
        f"岗位职责：{position.get('responsibilities', '未提供')}\n\n"
        f"简历分析结果：\n{resume_analysis or '未提供简历分析信息'}\n\n"
        f"请根据以上信息生成 5 个高质量的面试问题，每个问题需包含评分标准。"
    )

    # OpenAI 格式的 messages 列表
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return messages


def generate_interview_questions(candidate: dict, position: dict, resume_analysis: str = "") -> list:
    """
    调用 OpenAI 接口生成面试问题
    大模型调用失败时，自动返回默认问题（get_default_questions）

    Args:
        参数同 build_interview_prompt

    Returns:
        list: 面试问题列表（5个）；大模型调用失败时返回默认问题
    """
    messages = build_interview_prompt(candidate, position, resume_analysis)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=2000,
            temperature=0.7,
            top_p=0.9,
            response_format={"type": "json_object"},
        )

        result_text = response.choices[0].message.content
        result = json.loads(result_text)

        # 从返回结果中取出问题列表
        questions = result.get("questions", [])
        if not questions:
            # 大模型未返回有效问题，使用默认问题
            return get_default_questions()
        return questions

    except Exception as e:
        # 任何异常（网络、解析、API错误等）都回退到默认问题，保证面试流程不中断
        print(f"[Prompt] 调用大模型失败: {e}，使用默认题库生成面试问题")
        return get_default_questions()
