"""
面试问题生成服务模块
====================
本模块负责调用prompt.py文件中的build_interview_prompt函数生成面试问题
基于阿里云 DashScope qwen-flash 文本模型（OpenAI 兼容接口）
简历由 resume_parser.py 解析成 markdown 文本后作为上下文传入

【一条面试问题的完整旅程】（帮助理解各函数如何配合）
    server.py（收到"开始面试"请求）
        └→ generate_questions()          本模块主入口，串起整个流程
            ├→ build_interview_prompt()  prompt.py：把候选人/岗位信息拼成提示词
            ├→ call_llm_api()            本模块：把提示词发给 qwen-flash，拿回 JSON
            │    ├→ _get_client()           首次调用时创建客户端（懒加载单例）
            │    └→ _parse_json_content()   解析模型返回的 JSON（含剥围栏兜底）
            ├→ validate_questions()         校验问题格式，统一成固定三字段
            ├→ save_questions_to_db()       每个问题先合成语音，再存入 SQLite
            └→ 任何一步失败 → get_default_questions() 返回兜底默认问题
"""

import json
import logging
import re
import os

from openai import OpenAI
# 直接用 openai 库 + DashScope 兼容端点即可调通通义模型，无需额外安装 dashscope SDK

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, LLM_MODEL
# 配置由 config.py 从项目根 .env 读取：API 密钥只存 .env 不入代码库；
# 模型用 qwen-flash（速度快、价格低，适合批量生成问题）

from app.ai_services.speech_service import synthesize_speech
# 每个问题预生成语音存库，面试播放时直接读库，候选人不用干等实时合成

from app.ai_services.prompt import build_interview_prompt, get_default_questions


logger = logging.getLogger(__name__)

# 匹配 ```json ... ``` 的md围栏（部分模型不遵守 response_format 时会带markdown格式的围栏返回）
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# DashScope 客户端懒加载单例（避免模块导入时就构造，防止未配置 key 时直接报错）
_client = None


def _get_client():
    """获取 DashScope（OpenAI 兼容）客户端，首次调用时创建

    单例：客户端只封装密钥和地址，创建后全程序复用，避免重复创建浪费资源；
    懒加载：若模块导入时就创建，.env 没配 key 会导致整个服务起不来，
    改为首次真正调用大模型时才创建，其他不依赖大模型的功能不受影响。
    """
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY,
            # 密钥来源优先级：先取环境变量（换 key 不用改代码），取不到再用 config.py 静态值兜底
            base_url=DASHSCOPE_BASE_URL,
        )
    return _client


def _parse_json_content(content):
    """
    解析大模型返回的 JSON 文本（两步兜底）

    请求时虽然指定了 response_format=json_object，但部分模型偶尔不遵守，
    返回内容会裹一层 ```json ... ``` 代码围栏，直接 json.loads 会失败，
    所以直接解析失败时先剥围栏再试一次。
    失败时返回 None，上层会改用默认问题，面试流程不中断。
    """
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        pass
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

    messages 为 OpenAI 格式消息列表（由 build_interview_prompt() 生成，
    末尾可追加候选人简历 markdown）；max_tokens 默认 2000：5 个问题+评分
    标准约需 800~1500 token，留足余量，且输出越长越慢越贵。
    返回解析后的 {"questions": [...]}，失败返回 None（不抛异常，由上层统一兜底）。
    """
    # 先检查密钥：没配置就不发请求，直接返回 None（快速失败，省一次注定失败的调用）
    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        logger.warning("[Question] 未配置DASHSCOPE_API_KEY")
        return None

    try:
        response = _get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            # ↑ 0.7 是出题场景的折中：太低（~0.2）问题千篇一律没区分度，
            #   太高（>1.0）容易跑题甚至胡编；0.7 兼顾多样性和稳定性
            response_format={"type": "json_object"},
            # ↑ 强制模型只输出合法 JSON；但模型偶尔不遵守，仍需 _parse_json_content 兜底
        )

        content = response.choices[0].message.content
        if not content:
            logger.error("[Question] 响应缺少content字段")
            return None

        return _parse_json_content(content)
    except Exception as e:
        # 网络超时、密钥无效、限流等所有异常统一在这里捕获：
        # 记日志并返回 None，让上层 generate_questions() 走默认问题兜底
        logger.error(f"[Question] 大模型生成问题的API调用失败: {e}")
        return None


def generate_question_hint(question_text):
    """
    针对单道面试题生成答题思路提示（前端"AI辅助"按钮的支撑）

    与出题/报告同用 LLM_MODEL（qwen-flash）+ 兼容端点，一次提示约几百
    token，成本可忽略。
    返回 (提示文本, 错误信息)：失败时文本为 None，上层据此降级
    （与 transcribe_audio_with_openai 同款约定）。
    """
    # 快速失败：没配密钥就不发请求，省一次注定失败的调用（与 call_llm_api 一致）
    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        return None, "未配置DASHSCOPE_API_KEY"

    try:
        # 不复用 call_llm_api 的原因：它强制 response_format=json_object（出题专用，
        # 返回 {"questions": [...]} 结构），而提示是给人看的自然语言，要纯文本输出。
        # 所以直接用 _get_client() 单例客户端自己调一次。
        response = _get_client().chat.completions.create(
            model=LLM_MODEL,           # 同一个便宜模型：出题/报告/提示三处统一
            messages=[
                {"role": "system", "content": (
                    "你是一位友善的面试教练。候选人正在模拟面试练习，遇到一道题想获取提示。"
                    "请给出3-4条答题思路提示（是思考方向，不是完整答案），每条一行、"
                    "以数字序号开头，总长度不超过120字，中文输出。"
                )},
                {"role": "user", "content": f"面试题目：{question_text}"}
            ],
            max_tokens=300,   # 提示文案很短，300 上限足够：响应快、费用低
            temperature=0.5,  # 提示要稳不要飘：比出题(0.7)略低
        )
        content = response.choices[0].message.content
        if not content:
            return None, "模型返回为空"
        return content.strip(), None
    except Exception as e:
        logger.error(f"[Hint] 生成提示失败: {e}")
        return None, str(e)


def validate_questions(questions):
    """
    验证并格式化问题列表

    大模型输出不受控——可能漏字段、类型错、数量超标，直接入库会导致
    语音合成或前端渲染崩溃；这里把每条问题规范成固定三字段结构再放行，
    全部无效时返回 None。
    """
    if not questions or not isinstance(questions, list):
        return None

    valid = []
    for q in questions:
        if not isinstance(q, dict) or 'question' not in q:
            continue

        validated = {
            'question': q.get('question', ''),
            'score_standard': q.get('score_standard', '考察候选人的专业能力和经验'),
            'question_type': q.get('question_type', 'voice')
        }
        valid.append(validated)

    # 限制最多5个问题：与提示词要求的"5个"对齐，防止模型超量输出拖慢语音生成
    return valid[:5] if valid else None


def save_questions_to_db(cursor, interview_id, questions, voice_type):
    """保存问题到数据库并预生成语音（voice_type 为用户创建面试时选择的音色），
    返回成功保存的问题数量"""
    saved_count = 0
    
    cnt = 0

    for q in questions:
        cnt += 1
        try:
            # 预生成语音：现在就把问题文本转成音频存库，
            # 面试播放时直接读库，避免候选人等待实时 TTS 合成
            audio_data, _ = synthesize_speech(q['question'], voice_type)

            # %s 占位符由 psycopg3 做参数转义，防 SQL 注入
            cursor.execute('''
                INSERT INTO interview_questions
                (interview_id, question, score_standard, question_type, question_audio, voice_type)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (interview_id, q['question'], q['score_standard'], q['question_type'], audio_data, voice_type))
            saved_count += 1
        except Exception as e:
            # 单个问题保存失败（如 TTS 超时）只记日志、继续处理后面的，
            # 不让一条问题拖垮整场面试
            logger.error(f"[Question] 保存问题{cnt}失败: {e}")

    return saved_count


def generate_questions(interview_id, candidate, position, interview, latest_tech_info, cursor, conn, resume_md=None):
    """
    生成面试问题的主函数：拼提示词 → 调大模型 → 校验 → 入库(含预生成语音) → 更新面试状态

    被 server.py 在用户点击"开始面试"后调用（异步线程中执行）。
    resume_md 为简历解析出的 markdown（MinerU 失败回退 PyPDF2，再失败则为 None，
    此时出题只依赖简历分析结论 latest_tech_info）。
    永远返回 status="success"：即使大模型失败也用默认问题兜底，保证面试一定能开始。
    """
    logger.info("[Question] 开始生成面试问题")

    try:
        # 1. 构建 prompt 并调用大模型
        messages = build_interview_prompt(candidate, position, latest_tech_info or "")
        # ↑ None 时兜底成空串，避免 prompt 里出现字面 "None"
        if resume_md:
            # messages[-1] 是最后一条消息（即 user 消息）：素材本就归属 user 消息；
            # 且经验上模型对提示词开头/结尾内容的利用率最高（Lost in the Middle 的 U 形曲线），
            # 追加在末尾比塞进中间更不容易被忽略
            messages[-1]["content"] += f"\n\n候选人简历原文（Markdown）：\n{resume_md}"
        llm_result = call_llm_api(messages)

        # 2. 获取并验证问题列表
        questions = None
        llm_success = False  # 标记：题目是否真的来自大模型（决定要不要扣配额）
        if llm_result and 'questions' in llm_result:
            questions = validate_questions(llm_result['questions'])
            if questions:
                llm_success = True

        # 3. 如果没有有效问题，使用默认问题
        #    （大模型失败/返回空/格式全错，都会落到这里）
        if not questions:
            logger.warning("[Question] 使用默认问题")
            questions = get_default_questions()

        # 4. 保存到数据库（每个问题会先预生成语音）
        voice_type = interview.get('voice_type', 'professional_male')
        # ↑ 音色缺失时给默认男声，保证流程不因配置缺失而中断
        saved_count = save_questions_to_db(cursor, interview_id, questions, voice_type)

        # 4.5 扣减用户面试配额：只有大模型真正出题成功才扣 1 次
        # 【为什么放这里】配额语义 = "调用大模型才消耗"——大模型挂了走默认题库兜底，
        # 用户没得到 AI 服务就不该扣；所以挂在 llm_success 分支而不是创建面试时。
        # 【为什么不用 interview.get('user_id')】不信任调用方传的 dict 结构是否带
        # user_id，直接用 interview_id 反查 interviews 表最稳（同库一次主键查询）。
        if llm_success:
            try:
                cursor.execute('SELECT user_id FROM interviews WHERE id = %s', (interview_id,))
                owner = cursor.fetchone()
                if owner and owner['user_id']:
                    # 扣 1 次但不下限到负数：GREATEST(配额-1, 0)——配额为 0 时不再变负
                    cursor.execute('''
                        UPDATE users
                        SET interview_quota = GREATEST(interview_quota - 1, 0)
                        WHERE id = %s
                    ''', (owner['user_id'],))
                    logger.info(f"[Question] 已扣减用户 {owner['user_id']} 的面试配额")
            except Exception as quota_err:
                # 扣减失败不阻断出题：配额系统是辅助功能，面试主流程优先
                logger.error(f"[Question] 扣减配额失败（不影响出题）: {quota_err}")

        # 5. 更新面试状态
        #    status=1 表示"已出题/面试进行中"；question_count 记录实际保存的题数
        cursor.execute('UPDATE interviews SET status = 1, question_count = %s WHERE id = %s',
                      (saved_count, interview_id))
        conn.commit()
        # ↑ PG autocommit 模式下每句 SQL 执行完已自动提交；commit() 保留为兼容写法，无害

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
