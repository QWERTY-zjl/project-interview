"""
面试管理API模块
=================

本模块是面试流程的核心接口层：查面试信息、逐题取题、提交答案、
切换语音设置、创建面试、生成题目。所有按 token 定位的接口，
token 都是这场面试的对外标识（32 位随机串，防猜解）。

【错误处理两段式】主动失败先 return_db(conn) 归还连接再 raise HTTPException
（顺序反了连接就泄漏）；函数末尾 except HTTPException: raise 是把
上面主动抛的 404/400 "原样放行"，不被下面的兜底逻辑改写成 500

【本文件涉及的 4 张表】（字段全貌见建表脚本 app/db/create_personal_interview_system_db.py）
- interviews（面试场次表）：一场面试一行。id 自增主键（从 1 开始、只增不复用）；
  token 是对外标识；user_id / interview_type_id 是外键；
  status 是状态字段（0=待出题，3=已完成，各值含义见建表脚本注释）
- interview_questions（面试题目表）：一道题一行。interview_id 指向
  interviews.id；answer_text / answered_at
  在考生交答案时才写入；question_audio 存预生成的语音二进制（BLOB）
- users（用户表）：注册用户一行，username / email / password_hash 等
- interview_types（面试类型字典表）：面试种类一行（如"Python 后端"），
  出题时拿它的 name / description 给 LLM 当背景资料
表间关系：本文件查多表从不写 JOIN，全靠 WHERE 列 = %s 手动关联——
interviews.user_id 对 users.id；interview_questions.interview_id 对 interviews.id
"""

import logging
# json：my_records / detail 接口用来解析 interviews.report_content
# ——那是一个存进数据库的 JSON 字符串，要还原成字典才能取字段
import json
import time

from fastapi import APIRouter, Path, Query, Body, HTTPException, Request
# JSONResponse：手工指定状态码 + JSON 内容（项目主流返回写法）
from fastapi.responses import JSONResponse

# 数据库连接池入口（实现在 app/db/db.py，线程本地连接模式）
from app.db.db import get_db, return_db
# get_auth_user：从请求头 Authorization: Bearer <token> 解析当前登录用户
# （my_records 接口鉴权用，见 app/api/deps.py）
from app.api.deps import get_auth_user
# 生成 32 位随机 token 的工具函数（app/utils/utils.py），底层用 secrets 模块
# 保证密码学安全——面试链接全靠它防遍历猜解（防 IDOR 漏洞）
from app.utils.utils import generate_token

logger = logging.getLogger(__name__)

# 面试流程路由：本文件所有面试接口共用
router = APIRouter(tags=["面试流程"])


# 路径用 /info 对齐前端契约：interview.html 3 处调用 /api/interview/{token}/info
@router.get("/api/interview/{token}/info", summary="获取面试信息")
async def get_interview_info(token: str = Path(...)):
    """获取面试信息（时间、岗位名、候选人、状态、题目数、语音设置）"""
    try:
        conn = get_db()

        # 只挑要用的列（不写 * 全取）；%s 占位符 + 元组传参，防 SQL 注入
        interview = conn.execute('''
            SELECT id, user_id, question_count, voice_reading, voice_type, start_time, status
            FROM interviews
            WHERE token = %s
        ''', (token,)).fetchone()

        if not interview:
            # 顺序关键：先还连接、再抛异常。raise 之后的代码不会执行，
            # 若先 raise，连接会泄漏
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        result = dict(interview)

        # 尝试获取用户信息；try/except 是"防御性降级"：用户查不到不影响主流程，
        # 名字退化为"未知用户"
        candidate_name = "未知用户"
        candidate_email = ""
        try:
            user = conn.execute('SELECT username, email FROM users WHERE id = %s', (result['user_id'],)).fetchone()
            if user:
                candidate_name = user['username']
                candidate_email = user['email']
        except Exception as e:
            logger.error(f"[INFO] 获取用户信息失败: {e}")

        # 个人版无岗位表，岗位名用固定占位
        position_name = "模拟面试"

        return_db(conn)

        # 格式化面试时间：Unix 时间戳 → "2026年10月01日 14:30" 可读格式
        start_time = result.get('start_time')
        try:
            import datetime   # 函数内延迟导入，只在需要时加载
            if start_time and start_time > 0:
                result['time'] = datetime.datetime.fromtimestamp(start_time).strftime('%Y年%m月%d日 %H:%M')
            else:
                result['time'] = "未设置时间"
        except Exception as e:
            logger.error(f"[INFO] 格式化时间失败: {e}")
            result['time'] = "未设置时间"

        # JSONResponse 手工打包响应；result.get('question_count') or 0：
        # 键不存在时兜底 0，前端拿到的永远是数字
        return JSONResponse(
            status_code=200,
            content={
                "interview_id": result['id'],
                "time": result['time'],
                "position": position_name,
                "candidate": candidate_name,
                "status": result['status'],
                "question_count": result.get('question_count') or 0,
                "voice_reading": result.get('voice_reading') or 0,
                "voice_type": result.get('voice_type', 'professional_male')
            }
        )
    except HTTPException:
        # 裸 raise：把上面主动抛的 404 原样再抛出去——如果没有这句，
        # 404 会被下面的兜底 except 捕获改写成 500，前端就分不清"不存在"和"出错了"
        raise
    except Exception as e:
        # 兜底捕获：没预料到的异常统一转成 500，避免服务器直接崩掉；
        # traceback 打印完整调用栈，是排查 500 的第一手线索
        logger.error(f"[ERROR] get_interview_info: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/interview/{token}/get_question", summary="获取下一题")
async def get_next_question(token: str = Path(...), current_id: int = Query(0)):
    """获取下一个面试问题（current_id=0 取第一题）

    没有下一题时返回 {"id": 0, "text": "面试已完成"} 完成信号。
    """
    try:
        conn = get_db()

        # 用对外 token 换出内部 id：后续所有查询都用面试内部的 id 关联，
        # token 只在"入口"这一步用来定位面试
        interview = conn.execute('SELECT id FROM interviews WHERE token = %s', (token,)).fetchone()

        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        # 获取下一个问题（包含预生成的语音）
        # question as text：数据库列名叫 question，返回给前端时键名改成
        # text——前端统一读 text 字段
        next_question = None
        # 两分支查同一张表，只差 WHERE 条件：
        #   current_id == 0 → 优先取第一道"未答"的题（断点续答）
        #   否则 → WHERE id > current_id 再取最小 id（下一题）
        if current_id == 0:
            # 【断点续答】current_id=0 有两种来路：首次开考（一题未答）和中途
            # 退出后重新进入（可能已答过几题）。answer_text IS NULL 即"没答过"
            # （submit_text_answer 校验过非空才写入，答过必非 NULL）：
            # 首次开考时第一道未答题就是第一题（行为不变），续面时从断点继续，
            # 不会把答过的题再问一遍
            next_question = conn.execute('''
                SELECT id, question as text, question_audio, voice_type
                FROM interview_questions
                WHERE interview_id = %s AND answer_text IS NULL
                ORDER BY id ASC
                LIMIT 1
            ''', (interview['id'],)).fetchone()

            # 一道未答题都查不到 = 全部已答（比如答完最后一题、报告还没生成完
            # 就关闭页面的"孤儿场"）→ 返回 id=0 完成信号，前端据此走
            # "面试完成 → 生成报告"收尾流程，而不是把第一题再问一遍
            if not next_question:
                return_db(conn)
                return JSONResponse(
                    status_code=200,
                    content={"id": 0, "text": "面试已完成"}
                )
        else:
            next_question = conn.execute('''
                SELECT id, question as text, question_audio, voice_type
                FROM interview_questions
                WHERE interview_id = %s AND id > %s
                ORDER BY id ASC
                LIMIT 1
            ''', (interview['id'], current_id)).fetchone()

        return_db(conn)

        # 约定 id=0 是"面试完成"信号，前端靠它收尾
        if not next_question:
            return JSONResponse(
                status_code=200,
                content={"id": 0, "text": "面试已完成"}
            )

        result = dict(next_question)

        # 有预生成的语音则转 base64：question_audio 是二进制（bytes），JSON 只能装文本；
        # base64 编码成纯文本，前端解码后交给 <audio> 播放
        if result.get('question_audio'):
            import base64
            result['audio'] = base64.b64encode(result['question_audio']).decode('utf-8')
            result['audio_format'] = 'mp3'
            result['use_pre_generated'] = True
            logger.info(f"[INFO] 返回预生成语音，问题ID: {result['id']}, 音频大小: {len(result['question_audio'])} 字节")
            # 删原始二进制：bytes 无法 JSON 序列化，不删会直接报错
            del result['question_audio']  # 删除二进制数据，只保留base64
        else:
            result['use_pre_generated'] = False
            logger.info(f"[INFO] 无预生成语音，问题ID: {result['id']}")

        return JSONResponse(
            status_code=200,
            content=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] get_next_question: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 两个 Body 参数各对应 JSON 里的一个键（多个 Body 参数时框架自动按键名拆分）
@router.post("/api/interview/{token}/submit_text_answer", summary="提交文本答案")
async def submit_text_answer(token: str = Path(...), question_id: int = Body(...), answer_text: str = Body(...)):
    """提交文本答案并返回下一题（next_question.id=0 表示面试完成）"""
    try:
        conn = get_db()
        # token 换内部 id，同时起到鉴权作用：token 查不到 = 没资格操作任何面试 → 404
        interview = conn.execute('SELECT id FROM interviews WHERE token = %s', (token,)).fetchone()

        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        # 业务校验：题目 id 和答案文本都不能为空（...必填只保证"传了"，
        # 传 null/空串仍会进到这里，所以要手动挡一层）
        if not question_id or not answer_text:
            return_db(conn)
            raise HTTPException(status_code=400, detail="缺少必要参数")

        answered_time = int(time.time())

        # WHERE 同时限定 id 和 interview_id 是安全设计：即使 question_id 被伪造，
        # 只要不属于这场面试就更新不到任何行（防越权写）
        conn.execute('''
            UPDATE interview_questions
            SET answer_text = %s, answered_at = %s
            WHERE id = %s AND interview_id = %s
        ''', (answer_text, answered_time, question_id, interview['id']))

        # 立刻查下一题一并返回——前端交一次答案就能直接展示下一题，省一次请求
        next_question = conn.execute('''
            SELECT id, question as text, question_type
            FROM interview_questions
            WHERE interview_id = %s AND id > %s
            ORDER BY id ASC
            LIMIT 1
        ''', (interview['id'], question_id)).fetchone()

        # 提交事务：上面的 UPDATE 到此才真正落盘；不 commit 连接归还后改动会丢
        conn.commit()

        if not next_question:
            # 已是最后一题 → 统计是否全部答完（total=总题数，answered=已答题数）
            all_answered = conn.execute('''
                SELECT COUNT(*) as total, SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) as answered
                FROM interview_questions
                WHERE interview_id = %s
            ''', (interview['id'],)).fetchone()

            # 总题数 == 已答题数 → 面试完成
            if all_answered['total'] == all_answered['answered']:
                # status=3：已完成（状态终态）
                conn.execute('UPDATE interviews SET status = 3 WHERE id = %s', (interview['id'],))
                conn.commit()

            result = {
                "status": "success",
                "message": "答案已提交",
                "audio_text": answer_text[:100] + "..." if len(answer_text) > 100 else answer_text,
                "next_question": {"id": 0, "text": "面试已完成"}
            }
        else:
            result = {
                "status": "success",
                "message": "答案已提交",
                "audio_text": answer_text[:100] + "..." if len(answer_text) > 100 else answer_text,
                "next_question": dict(next_question)
            }

        return_db(conn)
        return JSONResponse(
            status_code=200,
            content=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] submit_text_answer: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# embed=True：从 JSON 对象 {"enabled": true} 里按键名取值，与前端契约一致
# （裸标量 Body 会导致 422）
@router.post("/api/interview/{token}/toggle_voice_reading", summary="切换语音朗读")
async def toggle_voice_reading(token: str = Path(...), enabled: bool = Body(..., embed=True)):
    """切换语音朗读开关"""
    try:
        conn = get_db()
        # 注意本接口没先查面试是否存在，token 不存在时 UPDATE 静默影响 0 行，
        # 仍返回 success——宽松实现，实际无碍（开关不存在的面试没有意义）
        conn.execute('UPDATE interviews SET voice_reading = %s WHERE token = %s',
                    (1 if enabled else 0, token))
        conn.commit()
        return_db(conn)

        return JSONResponse(
            status_code=200,
            content={'status': 'success', 'voice_reading': enabled}
        )
    except Exception as e:
        logger.error(f"[ERROR] toggle_voice_reading: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# embed=True 同 toggle_voice_reading：接受 {"voice_type": "..."} 对象形态
@router.post("/api/interview/{token}/set_voice", summary="设置面试官音色")
async def set_interview_voice(token: str = Path(...), voice_type: str = Body(..., embed=True)):
    """设置面试官音色（面试开始前）"""
    try:
        conn = get_db()
        interview = conn.execute('SELECT status FROM interviews WHERE token = %s', (token,)).fetchone()

        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        # 状态门槛：status >= 2 表示面试已进入开始后的阶段，音色不允许再改——
        # 题目语音是按音色预生成的，中途换音色会导致语音和文字对不上
        if interview['status'] >= 2:
            return_db(conn)
            raise HTTPException(status_code=400, detail="面试已开始，无法更改面试官类型")

        conn.execute('UPDATE interviews SET voice_type = %s WHERE token = %s',
                    (voice_type, token))
        conn.commit()
        return_db(conn)

        return JSONResponse(
            status_code=200,
            content={'status': 'success', 'voice_type': voice_type}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] set_interview_voice: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 个人版开始面试的唯一入口 = 登录后在工作台上传简历（/api/resume/upload，已鉴权），
# 本模块不提供匿名创建面试的接口


def _generate_questions_business(token: str):
    """
    生成面试问题的业务实现（同步函数，供路由共用）

    【为什么拆出来】出题要调大模型（耗时几十秒），把业务逻辑和路由函数
    分开写：路由函数只负责接请求、调业务、包响应，逻辑清晰也方便复用。

    返回 (dict, 状态码) 元组，由调用方打包成 HTTP 响应。
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        try:
            # 查询面试记录：一次取齐出题要用的 5 个字段，按 token 精确定位
            cursor.execute('SELECT id, user_id, interview_type_id, question_count, voice_type FROM interviews WHERE token = %s', (token,))
            interview = cursor.fetchone()

            if not interview:
                # 本函数不直接发 HTTP 响应，返回 (内容, 状态码) 交给调用方打包
                return {"error": "面试不存在"}, 404

            interview_id = interview["id"]
            user_id = interview["user_id"]
            interview_type_id = interview["interview_type_id"]
            question_count = interview["question_count"]
            voice_type = interview["voice_type"]

            logger.info(f"[Interview] 找到面试记录，ID: {interview_id}, 用户ID: {user_id}")

            # 幂等：已有题就直接返回成功，用户重复请求/页面刷新不会生成两套题
            cursor.execute('SELECT COUNT(*) AS cnt FROM interview_questions WHERE interview_id = %s', (interview_id,))
            existing_questions = cursor.fetchone()["cnt"]

            if existing_questions > 0:
                logger.info(f"[Interview] 面试已有 {existing_questions} 个问题，跳过生成")
                return {"status": "success", "message": f"面试已有 {existing_questions} 个问题"}, 200

            # 获取面试类型信息：name / description 给出题 LLM 当背景资料
            cursor.execute('SELECT name, description FROM interview_types WHERE id = %s', (interview_type_id,))
            interview_type = cursor.fetchone()

            if not interview_type:
                return {"error": "面试类型不存在"}, 404

            interview_type_name = interview_type["name"]
            interview_type_description = interview_type["description"]

            # 生成面试问题：函数内延迟导入，服务器启动阶段不背这个加载成本
            from app.ai_services.question_service import generate_questions

            # 个人用户版：没有候选人/岗位表关联，用模拟信息占位（与 server.py 现役实现一致）
            # candidate/position 两个字典是给出题 LLM 看的"背景资料"
            candidate = {
                "id": user_id,
                "name": "个人用户",
                "email": "user@example.com",
                "position_id": 1
            }
            position = {
                "id": 1,
                "name": interview_type_name,
                "description": interview_type_description,
                "requirements": "",
                "responsibilities": ""
            }

            # 组装面试信息字典（含 voice_type，供语音预生成使用）
            interview_dict = {
                "id": interview_id,
                "user_id": user_id,
                "interview_type_id": interview_type_id,
                "status": 0,
                "voice_type": voice_type
            }
            logger.info("[Interview] 调用 generate_questions 函数...")
            # 把 cursor 和 conn 也传进去：出题逻辑要在同一个事务里写题库
            result = generate_questions(interview_id, candidate, position, interview_dict, "", cursor, conn)

            logger.info(f"[Interview] 生成面试问题完成: {result}")

            if isinstance(result, dict):
                if "error" in result:
                    return result, 500
                else:
                    return result, 200
            else:
                return {"error": "生成面试问题返回结果无效"}, 500
        finally:
            # 确保数据库连接被归还
            try:
                return_db(conn)
            except Exception as e:
                logger.error(f"[Interview] 关闭数据库连接失败: {str(e)}")
    except Exception as e:
        logger.error(f"[Interview] 生成面试问题失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}, 500


# 注意这是 def 而不是 async def：
# def 同步函数会被 FastAPI 自动丢进线程池执行——出题要调大模型、阻塞几十秒，
# 放线程池里不会卡住事件循环；如果写成 async def，同步阻塞会把整个服务卡死。
# "重 IO 接口用 def"是本项目验证过的经验教训
@router.post("/api/interview/{token}/generate_questions", summary="生成面试问题")
def generate_questions(token: str = Path(...)):
    """为面试生成问题（个人用户版，出题要调大模型，用同步函数走线程池）"""
    result, code = _generate_questions_business(token)
    return JSONResponse(status_code=code, content=result)


# ==================== 面试统计（只读接口） ====================
# status 状态机（见建表脚本注释）：0=未开始 1=试题已备好 2=面试进行中(预留)
# 3=面试完毕 4=报告已生成

@router.get("/api/interview/stats", summary="面试统计（总数+status分布，可选?days=N）")
def get_interview_stats(days: int = Query(None)):
    """只读统计接口：返回 interviews 表总场数和 status 分布"""
    conn = get_db()
    # 时间基准在 Python 里算好再传参（time.time() 是 Python 函数，写进 SQL 会报错）
    cutoff = int(time.time()) - days * 24 * 60 * 60
    rows = conn.execute('''
        SELECT status, COUNT(*) AS count
        FROM interviews
        WHERE start_time >= %s
        GROUP BY status
    ''', (cutoff,)).fetchall()
    return_db(conn)    # 只读操作，用完立刻归还连接

    distribution = {row["status"]: row["count"] for row in rows}
    # 分布之和 = 总数，省一次 COUNT(*) 查询
    total = sum(distribution.values())

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "total": total,
            # 注意：JSON 的键只能是字符串，int 键 0 会自动变成 "0"，前端读到字符串键
            "status_distribution": distribution,
            # 含义对照：调试/展示时不用翻建表脚本就知道每个数字代表什么
            "status_meaning": {
                "0": "未开始",
                "1": "试题已备好",
                "2": "面试进行中(预留，当前代码从未写入)",
                "3": "面试完毕",
                "4": "报告已生成",
            },
        },
    )


@router.get("/api/interview/my_records", summary="查询某用户的面试记录列表（工作台用）")
async def get_my_records(request: Request):
    """查询某用户的最近面试记录 + 汇总统计

    为 admin.html 工作台提供 interviews 表的真实场次数据；岗位名和得分不单独
    存表，而是从 interviews.report_content 这个 JSON 字符串里解析出来
    （报告生成时写进去的）。

    身份从请求头 Authorization: Bearer <token> 解析当前登录用户（见 deps.py），
    未登录或 token 无效一律 401，没有 user_id 参数。

    返回 records（最近 10 场，新的在前，含 token / start_time 秒级时间戳 /
    status / position_name / score）与 stats（累计场数、平均分）。
    平均分只统计已生成报告的场次（status=4 且 report_content 能解析出分数）；
    一场都没有时 records 为空列表、average_score 为 None。
    """
    # 身份鉴权：token 反查用户，查不到（未登录/凭证失效）直接 401 拦截
    user = get_auth_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"error": "请先登录"}
        )
    try:
        conn = get_db()

        # 最近 10 场的真实记录。ORDER BY id DESC：id 自增，倒序即"新的在前"；
        # LIMIT 10：个人版展示用，取最近 10 场足够，不做分页
        rows = conn.execute('''
            SELECT token, start_time, status, report_content
            FROM interviews
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 10
        ''', (user['id'],)).fetchall()

        # 累计场数：COUNT(*) 数该用户的全部行（不只最近 10 场），作为"累计 X 场"指标
        total_count = conn.execute(
            'SELECT COUNT(*) AS cnt FROM interviews WHERE user_id = %s', (user['id'],)
        ).fetchone()["cnt"]

        # 逐场解析 report_content，抽出岗位名和得分
        records = []
        scores = []  # 收集所有有效得分，最后算平均
        for row in rows:
            position_name = None
            score = None
            # report_content 可能是 NULL（没走到报告环节的场次），
            # row['report_content'] 取出 None 时跳过解析，两字段保持 None
            if row['report_content']:
                try:
                    report = json.loads(row['report_content'])
                    # 顶层 position_name 由 report_service 写入（如"AI应用经理"）
                    position_name = report.get('position_name')
                    # 得分在 evaluation 子对象里；解析出的值必须是数字才算有效，
                    # 防御报告 JSON 结构异常（如 score 是字符串"44"）污染统计
                    ev = report.get('evaluation') or {}
                    raw_score = ev.get('averageScore')
                    if isinstance(raw_score, (int, float)):
                        score = raw_score
                        scores.append(score)
                except (json.JSONDecodeError, TypeError) as e:
                    # JSON 解析失败只影响这一场的岗位/得分展示，不让整个接口挂掉
                    logger.error(f"[MY_RECORDS] 解析 report_content 失败: {e}")

            records.append({
                "token": row['token'],
                "start_time": row['start_time'],  # 秒级时间戳，前端负责格式化
                "status": row['status'],
                "position_name": position_name,
                "score": score,
            })

        return_db(conn)

        # 没有任何已出报告的场次时 average_score 为 None
        average_score = round(sum(scores) / len(scores), 1) if scores else None

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "records": records,
                "stats": {"total_count": total_count, "average_score": average_score},
            },
        )
    except Exception as e:
        logger.error(f"[MY_RECORDS] 查询面试记录失败: {e}")
        return JSONResponse(status_code=500, content={"detail": f"查询失败: {str(e)}"})


@router.get("/api/interview/{token}/detail", summary="查询某场面试的完整详情（题目+回答+报告）")
async def get_interview_detail(token: str = Path(...)):
    """查询某场面试的完整详情，供独立的记录详情页展示

    【返回什么】一场面试的三大块内容：
    1. questions：题目列表（题目原文 + 评分标准 + 考生的回答文本）
    2. report：完整评价报告（总分 / 三维小分 / 优势 / 改进 / 建议 / 逐题点评）
    3. interview：基本信息（岗位名、时间、状态）
    报告数据全部来自 interviews.report_content（生成报告时一次性写入的 JSON）；
    未生成报告的场次 report 为 null，前端据此显示"报告未生成"。
    """
    try:
        conn = get_db()

        # 基本信息：一场面试一行。id 列必须查——下面查题目时要用它当 interview_id
        interview = conn.execute('''
            SELECT id, token, start_time, status, question_count, report_content
            FROM interviews
            WHERE token = %s
        ''', (token,)).fetchone()

        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        # 题目列表：一场面试对多道题（一对多），按 id 正序 = 出题顺序。
        # answer_text：考生交答案时写入，未答的题为 NULL——前端显示"未回答"
        question_rows = conn.execute('''
            SELECT id, question, score_standard, answer_text
            FROM interview_questions
            WHERE interview_id = %s
            ORDER BY id ASC
        ''', (interview['id'],)).fetchall()

        questions = [
            {
                "id": q['id'],
                "question": q['question'],
                "score_standard": q['score_standard'],
                # answer_text 原样透传（未答为 null），前端判空展示"未回答"
                "answer_text": q['answer_text'],
            }
            for q in question_rows
        ]

        # 解析报告 JSON：未生成（NULL）或解析失败时 report 保持 None
        report = None
        if interview['report_content']:
            try:
                report = json.loads(interview['report_content'])
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"[DETAIL] 解析 report_content 失败: {e}")

        return_db(conn)

        return JSONResponse(
            status_code=200,
            content={
                "interview": {
                    "token": interview['token'],
                    "start_time": interview['start_time'],
                    "status": interview['status'],
                    "question_count": interview['question_count'],
                },
                "questions": questions,
                "report": report,
            },
        )
    except HTTPException:
        # 主动抛的 404 原样放行（见文件头"错误处理两段式"），不被兜底改写成 500
        raise
    except Exception as e:
        logger.error(f"[DETAIL] 查询面试详情失败: {e}")
        return JSONResponse(status_code=500, content={"detail": f"查询失败: {str(e)}"})


@router.post("/api/interview/{token}/hint", summary="AI辅助：针对当前题目生成答题思路提示")
async def get_ai_hint(token: str, body: dict = Body(...)):
    """生成当前题目的答题思路提示（前端"AI辅助"按钮）

    真调用大模型（qwen-flash），针对题目原文生成个性化提示；失败时诚实降级
    为通用建议并在前端标注"AI暂不可用"，不装成 AI 生成的。

    【安全设计】题号必须属于当前 token 对应的那场面试（WHERE 同时校验两列），
    防止拿别场的题目 id 来接口白嫖提示。

    body 为 JSON 对象 {"question_id": 题目id}（dict 整体接收，无单标量 422 问题）。
    """
    # 函数内延迟 import：与 generate_questions 的引用方式保持一致（631 行同款惯例）
    from app.ai_services.question_service import generate_question_hint

    question_id = body.get("question_id")
    if not question_id:
        raise HTTPException(status_code=422, detail="缺少 question_id")

    try:
        conn = get_db()

        interview = conn.execute(
            'SELECT id FROM interviews WHERE token = %s', (token,)
        ).fetchone()
        if not interview:
            return_db(conn)
            raise HTTPException(status_code=404, detail="面试不存在")

        # 查题目原文：id 和 interview_id 双条件——题目既要存在又要属于这场面试
        q = conn.execute('''
            SELECT question FROM interview_questions
            WHERE id = %s AND interview_id = %s
        ''', (question_id, interview['id'])).fetchone()
        return_db(conn)

        if not q:
            raise HTTPException(status_code=404, detail="题目不存在")

        # 调大模型生成提示；失败走"诚实降级"：文案明确说 AI 不可用，给通用建议
        hint, err = generate_question_hint(q['question'])
        if err or not hint:
            logger.error(f"[HINT] 生成提示失败，降级为通用建议: {err}")
            return JSONResponse(
                status_code=200,
                content={
                    "hint": "AI提示生成失败，先给你几条通用建议：\n"
                            "1. 结合自己的真实项目经验作答\n"
                            "2. 先讲结论再展开细节\n"
                            "3. 适当提及踩过的坑和解决过程",
                    "degraded": True,
                },
            )

        return JSONResponse(status_code=200, content={"hint": hint, "degraded": False})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HINT] AI辅助接口异常: {e}")
        return JSONResponse(status_code=500, content={"detail": f"生成失败: {str(e)}"})
