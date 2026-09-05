"""
记录生成不同岗位的提示词，将其送给大模型生成面试问题
采用openai格式

本模块是纯"提示词工厂"，不直接调大模型（调用逻辑在 question_service.py）：
    1. build_interview_prompt()  —— 核心：把候选人/岗位信息拼成大模型提示词
                                    （被 question_service.py 的面试主流程调用）
    2. get_default_questions()   —— 兜底：大模型失败时返回的默认问题
"""


def get_default_questions():
    """
    获取默认的面试问题

    当大模型调用失败时使用此函数返回默认问题
    （设计目的：保证面试流程"永远有题可问"，不因网络/密钥/解析问题而中断）

    Returns:
        list: 包含5个默认问题的列表
    """
    default_q = {
        "question": "大模型调用失败",
        "score_standard": "大模型调用失败",
        "question_type": "voice"  # 语音题：与正常问题的三字段结构保持一致，
                                  # 这样入库、前端渲染、语音合成都不会因结构不同而报错
    }
    # 必须用 .copy()：若直接 append 同一个 dict，列表里 5 个元素是同一个对象的引用，
    # 修改其中一个会导致"5 个全变"；copy() 让每个元素相互独立
    return [default_q.copy() for _ in range(5)]


def build_interview_prompt(candidate: dict, position: dict, resume_analysis: str = "") -> list:
    """
    构建 OpenAI 格式（messages 列表）的提示词，用于生成面试问题

    Args:
        candidate: 候选人信息字典。来源：用户在开始面试页填写的表单，
                   经 server.py 透传，如 {"name": "张三", "experience": "3年"}
        position: 职位信息字典。来源：用户创建面试时选择的岗位（存于 positions 表），
                  如 {"name": "Web开发工程师", "requirements": "...", "responsibilities": "..."}
        resume_analysis: 简历分析结果文本（可选）。来源：resume_analyzer 的分析结论，
                         作为出题侧重点；不传时默认空串

    Returns:
        list: OpenAI Chat Completions 接口的 messages 列表，固定两条消息：
              [0] system —— 设定面试官角色 + 规定 JSON 输出格式
              [1] user   —— 本次出题的具体素材（候选人/岗位/简历分析）
    """
    # system 消息：给模型定"人设"和"规矩"
    # 1) 角色设定（资深面试官）让提问更专业；2) 事先约定 JSON 结构，程序才能可靠解析
    system_prompt = (
        f"你是一位资深的{position.get('name', '未提供')}的面试官，擅长根据候选人简历和岗位需求生成针对性的面试问题。"#未提供是为了防止没有岗位名称时的err
        # ↑ .get('name', '未提供')：键不存在时返回默认值而不是抛 KeyError，防缺字段报错
        "要求问题专业、有区分度，并给出评分标准。总字数不能超过2000字。"
        "必须以 JSON 格式返回，结构为："
        '{"questions": [{"question": "问题内容", "score_standard": "评分标准", "question_type": "voice"}]}'# question_type为voice表示语音问题
        # ↑ 把期望的 JSON 结构直接写进提示词，字段与 validate_questions() 的校验一一对应
    )

    # user 消息：本次出题的全部"素材"，逐项列出便于模型针对性出题
    user_prompt = (
        f"候选人信息：\n"
        f"- 姓名：{candidate.get('name', '未提供')}\n"
        f"- 工作经验：{candidate.get('experience', '未提供')}\n\n"
        f"应聘职位：{position.get('name', '未提供')}\n"
        f"岗位要求：{position.get('requirements', '未提供')}\n"
        f"岗位职责：{position.get('responsibilities', '未提供')}\n\n"
        f"简历分析结果：\n{resume_analysis or '未提供简历分析信息'}\n\n"
        # ↑ or 兜底：resume_analysis 为 None/空串时显示占位文案，避免出现空白段落
        f"请根据以上信息生成 5 个高质量的面试问题，每个问题需包含评分标准。"
        # ↑ 明确数量要求（5个），与 question_service.validate_questions 的 valid[:5] 上限一致
    )

    # OpenAI 格式的 messages 列表
    messages = [
        {"role": "system", "content": system_prompt},  # 系统消息：角色设定 + 输出格式约束
        {"role": "user", "content": user_prompt},      # 用户消息：具体出题素材
    ]
    return messages
