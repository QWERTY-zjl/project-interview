"""
面试问题生成服务模块
====================
本模块负责调用prompt.py文件中的build_interview_prompt函数生成面试问题
基于阿里云 DashScope qwen-flash 文本模型（OpenAI 兼容接口）
简历由 resume_parser.py 解析成 markdown 文本后作为上下文传入（不再使用多模态截图）

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

import json    # 标准库：把大模型返回的 JSON 字符串解析成 Python 字典
import logging # 标准库：记录运行日志（输出到控制台/文件）
import re      # 标准库：正则表达式，用于剥掉返回内容里的 ```json 围栏
import os      # 标准库：读取环境变量 DASHSCOPE_API_KEY（.env 由启动脚本加载进环境）

from openai import OpenAI
# ↑ 第三方库（版本固定 2.30.0）。DashScope 提供"OpenAI 兼容接口"，
#   所以直接用 openai 库、把 base_url 改成 DashScope 地址即可调通通义模型，
#   无需额外安装 dashscope SDK，外部依赖最少

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, LLM_MODEL
# ↑ 三个配置定义在 app/config/config.py，由它从项目根目录的 .env 文件读取：
#   DASHSCOPE_API_KEY  -> 阿里云百炼平台的 API 密钥（鉴权用，只存 .env，不入代码库）
#   DASHSCOPE_BASE_URL -> 接口地址（DashScope 的 OpenAI 兼容模式 endpoint）
#   LLM_MODEL          -> 模型名（qwen-flash：速度快、价格低，适合批量生成问题）

from app.ai_services.speech_service import synthesize_speech
# ↑ 语音合成函数（DashScope TTS）。这里用它把每个问题"预生成"成音频存库，
#   面试播放时直接读库，不用实时合成，候选人不用干等

from app.ai_services.prompt import build_interview_prompt, get_default_questions
# ↑ build_interview_prompt：拼提示词（告诉模型"你是面试官，出5道题，返回JSON"）
#   get_default_questions：兜底默认问题（大模型挂了也保证有题可问）


logger = logging.getLogger(__name__)# 日志记录器，用于记录程序运行时的事件和错误信息显示在控制台
# ↑ __name__ 是本模块名（app.ai_services.question_service），
#   日志会带上这个前缀，方便区分日志来自哪个文件

# 匹配 ```json ... ``` 的md围栏（部分模型不遵守 response_format 时会带markdown格式的围栏返回）
# 采用正则表达式的方式剥围栏
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# DashScope 客户端懒加载单例（避免模块导入时就构造，防止未配置 key 时直接报错）
# _client：全局唯一实例，None 表示"还没创建过"
_client = None


def _get_client():
    """获取 DashScope（OpenAI 兼容）客户端，首次调用时创建
    可有可无，本身只是一个容错机制
    为什么要"懒加载 + 单例"：
    - 单例：OpenAI 客户端只是封装了密钥和地址，创建后可反复使用，
      全程序共用一个即可，避免重复创建浪费内存
    - 懒加载：若在模块顶部就创建，.env 没配 key 时 import 本模块就会报错，
      整个服务都起不来；改为首次真正调用大模型时才创建，
      其他不依赖大模型的功能（如浏览历史记录）不受影响

    Returns:
        OpenAI: 配置好密钥与接口地址的客户端实例
    """
    global _client# 全局变量，用于存储 DashScope 客户端实例
    if _client is None:# 只在第一次调用时创建，之后所有调用复用同一实例
        _client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY,# 从环境变量或配置文件获取 API 密钥
            # ↑ 密钥来源优先级：先取环境变量（.env 加载后的运行时值，换 key 不用改代码），
            #   取不到（None/空串）再用 config.py 里的静态值兜底
            #getenv就是去.env文件里取的方法
            base_url=DASHSCOPE_BASE_URL,# 接口地址指向 DashScope 兼容端点——这是"用 openai 库调通义模型"的关键
        )
    return _client


def _parse_json_content(content):
    """
    解析大模型返回的 JSON 文本

    为什么单独写解析函数：请求时虽然指定了 response_format=json_object，
    但部分模型偶尔不遵守，返回内容会裹一层 ```json ... ``` 代码围栏，
    直接 json.loads 会失败，所以这里做"两步解析"兜底

    Args:
        content: 大模型返回的文本。
                 来源：call_llm_api() 中 response.choices[0].message.content

    Returns:
        dict: 解析结果（形如 {"questions": [...]}），失败时返回 None
              （返回 None 后上层会改用默认问题，面试流程不中断）
    """
    try:
        return json.loads(content)# 第一步：直接按 JSON 解析
    except (TypeError, json.JSONDecodeError):# 捕获类型错误和 JSON 解码错误
        # TypeError:        content 不是字符串（如模型返回了 None）
        # JSONDecodeError:  是字符串但不是合法 JSON（典型：带 ``` 围栏）
        pass
    # 直接解析失败时，先剥掉 ```json 围栏再试一次
    if content:# 检查内容是否为空（None/空串没必要再试）
        stripped = _JSON_FENCE_RE.sub("", content).strip()# 移除 ```json ... ``` 围栏并首尾去空格
        try:
            return json.loads(stripped)# 第二步：剥掉围栏后再解析
        except json.JSONDecodeError:
            pass
    logger.error("[Question] 返回内容不是合法 JSON")# 两步都失败：记日志便于排查模型输出问题
    return None


def call_llm_api(messages, max_tokens=2000):
    """
    调用阿里云 DashScope 大模型 API（OpenAI 兼容接口，文本模型）

    Args: 参数说明
        messages: OpenAI 格式的消息列表 [{"role": ..., "content": ...}, ...]
                  来源：generate_questions() 里由 build_interview_prompt() 生成，
                  并在末尾追加了候选人简历 markdown，形如：
                  [{"role": "system", "content": "你是资深面试官..."},
                   {"role": "user",   "content": "候选人信息+岗位+简历原文"}]
        max_tokens: 最大生成 token 数，默认 2000。
                    5 个问题+评分标准约需 800~1500 token，2000 留足余量；
                    不设太大是因为输出越长越慢且越贵

    Returns:
        dict: API 返回的 JSON 结果（形如 {"questions": [...]}），失败时返回 None
              （约定"失败返回 None 而不抛异常"，由上层统一兜底）
    """
    # 先检查密钥：没配置就不发请求，直接返回 None（快速失败，省一次注定失败的调用）
    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        logger.warning("[Question] 未配置DASHSCOPE_API_KEY")
        return None

    try:
        response = _get_client().chat.completions.create(#chat.completions.create 方法是用于生成大模型的文本完成的 API 方法
            model=LLM_MODEL,# 模型名称，这里使用 qwen-flash 文本模型
            messages=messages,# 输入的消息列表，包含角色和内容
            max_tokens=max_tokens,# 回答长度上限：防止输出过长导致等待久、费用高
            temperature=0.7,# 温度参数，控制生成文本的随机性，默认值为 0.7
            # ↑ 0.7 是出题场景的折中：太低（~0.2）问题千篇一律没区分度，
            #   太高（>1.0）容易跑题甚至胡编；0.7 兼顾多样性和稳定性
            response_format={"type": "json_object"},# 响应格式，这里指定为 JSON 对象
            # ↑ 强制模型只输出合法 JSON，省去从普通文本里抠 JSON 的功夫；
            #   但模型偶尔不遵守，所以拿到内容仍要过 _parse_json_content 兜底
        )

        content = response.choices[0].message.content# .choices[0]是第一个选择，.message.content是生成的文本
        # ↑ 响应结构：response.choices 是候选回复列表（本次只生成一个，取第 0 个），
        #   .message.content 即模型生成的纯文本（应当是一段 JSON 字符串）
        if not content:
            logger.error("[Question] 响应缺少content字段")
            return None

        # 解析返回的 JSON
        return _parse_json_content(content)
    except Exception as e:
        # 网络超时、密钥无效、限流等所有异常统一在这里捕获：
        # 记日志并返回 None，让上层 generate_questions() 走默认问题兜底
        logger.error(f"[Question] 大模型生成问题的API调用失败: {e}")
        return None


def generate_question_hint(question_text):
    """
    针对单道面试题生成答题思路提示（前端"AI辅助"按钮的支撑）

    与出题/报告同用 LLM_MODEL（qwen-flash）+ 兼容端点，成本可忽略：
    一次提示约几百 token，按 2026-10 价格折算不到 0.001 元。

    Args:
        question_text: 题目原文。来源 interview_questions.question 列

    Returns:
        (提示文本, 错误信息) 元组：成功时错误为 None；失败时文本为 None
        （与 transcribe_audio_with_openai 同款约定：(结果, error)，上层据此降级）
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

    为什么需要校验：大模型输出不受控——可能漏字段、类型错、数量超标；
    直接入库会导致语音合成或前端渲染崩溃。
    这里把每条问题规范成固定三字段结构再放行。

    Args:
        questions: 大模型返回的问题列表。
                   来源：call_llm_api() 解析出的 dict 中的 'questions' 键
                   （见 generate_questions() 第 2 步）

    Returns:
        list: 验证通过的问题列表，每项固定为
              {"question": ..., "score_standard": ..., "question_type": ...}
              全部无效时返回 None
    """
    if not questions or not isinstance(questions, list):
        return None# 不是列表（如模型误返回字符串）直接判失败

    valid = []
    for q in questions:
        # 检查问题格式：必须是字典且必须有 question 字段，缺了就跳过这条
        if not isinstance(q, dict) or 'question' not in q:
            continue

        # 格式化问题：用 .get() 补齐缺失字段，保证入库数据结构统一
        validated = {
            'question': q.get('question', ''),# 问题正文（必填，上面已检查存在）
            'score_standard': q.get('score_standard', '考察候选人的专业能力和经验'),# 评分标准，缺失时给通用文案
            'question_type': q.get('question_type', 'voice')# 问题类型，默认语音题
        }
        valid.append(validated)

    # 限制最多5个问题：与提示词要求的"5个"对齐，防止模型超量输出拖慢语音生成
    return valid[:5] if valid else None


def save_questions_to_db(cursor, interview_id, questions, voice_type):
    """
    保存问题到数据库并预生成语音

    Args:
        cursor: 数据库游标。来源：server.py 创建的 SQLite 连接，用于执行 SQL 语句
        interview_id: 面试ID。来源：interviews 表主键，标记这批问题属于哪场面试
        questions: 问题列表。来源：validate_questions() 校验后的问题
                   （或大模型失败时的默认问题）
        voice_type: 音色类型。来源：interviews 表的 voice_type 字段
                    （用户创建面试时选择的，如 'professional_male'）

    Returns:
        int: 成功保存的问题数量（回填到 interviews.question_count）
    """
    saved_count = 0
    
    cnt = 0#记录问题编号

    for q in questions:
        cnt += 1
        try:
            # 预生成语音：现在就把问题文本转成音频存库，
            # 面试播放时直接读库，避免候选人等待实时 TTS 合成
            audio_data, _ = synthesize_speech(q['question'], voice_type)

            # 保存到数据库：%s 是占位符，由 psycopg3 做参数转义，防 SQL 注入
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
    生成面试问题的主函数
    pipelines式的拼接之前的函数
    被谁调用：server.py 在用户点击"开始面试"后调用（异步线程中执行）
    流程：拼提示词 → 调大模型 → 校验 → 入库(含预生成语音) → 更新面试状态

    Args:
        interview_id: 面试ID。来源：server.py 创建面试记录后得到的 interviews 表主键
        candidate: 候选人信息 dict。来源：前端表单提交，形如
                   {"name": "张三", "experience": "3年"}
        position: 职位信息 dict。来源：用户选择的岗位（positions 表），形如
                  {"name": "Web开发工程师", "requirements": "...", "responsibilities": "..."}
        interview: 面试配置 dict。来源：interviews 表中该场面试的整行记录，
                   这里主要用 voice_type（音色）
        latest_tech_info: 简历分析结论文本。来源：resume_analyzer 的分析结果，
                          作为出题侧重点；可能为 None（用 or "" 兜底成空串）
        cursor: 数据库游标。来源：server.py 的 SQLite 连接，执行 INSERT/UPDATE
        conn: 数据库连接对象。来源：同上，用于 commit 提交事务
        resume_md: 简历解析出的 markdown 文本（可选，由 MinerU/PyPDF2 生成）
                   来源：resume_parser.py；MinerU 失败回退 PyPDF2，
                   再失败则为 None（此时出题只依赖 latest_tech_info）

    Returns:
        dict: 状态+消息+问题列表。注意永远返回 status="success"：
              即使大模型失败也用默认问题兜底，保证面试一定能开始
    """
    logger.info("[Question] 开始生成面试问题")

    try:
        # 1. 构建 prompt 并调用大模型
        messages = build_interview_prompt(candidate, position, latest_tech_info or "")
        # ↑ latest_tech_info or ""：None 时兜底成空串，避免 prompt 里出现字面 "None"
        if resume_md:
            # messages[-1] 是最后一条消息（即 user 消息）：素材本就归属 user 消息；
            # 且经验上模型对提示词开头/结尾内容的利用率最高（Lost in the Middle 的 U 形曲线），
            # 追加在末尾比塞进中间更不容易被忽略    
            messages[-1]["content"] += f"\n\n候选人简历原文（Markdown）：\n{resume_md}"
        llm_result = call_llm_api(messages)#调用大模型生成面试问题

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
