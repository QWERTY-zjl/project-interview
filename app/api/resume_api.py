"""
简历上传API模块
"""

import json
import logging
import time
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.utils.utils import generate_token
from app.ai_services.resume_service import analyze_resume
# extract_resume_text：统一简历解析入口（PDF→pypdf，DOCX→python-docx，TXT→文本解码）
from app.ai_services.resume_parser import extract_resume_text
from app.ai_services.question_service import generate_questions
from app.db.db import get_db, return_db
# get_auth_user：从请求头 Authorization: Bearer <token> 解析当前登录用户
# （上传接口鉴权用：未登录不允许开始面试，见 app/api/deps.py）
from app.api.deps import get_auth_user
from app.api.tts_api import INTERVIEWER_VOICES

logger = logging.getLogger(__name__)

# 简历路由：本文件所有简历接口共用
router = APIRouter(tags=["简历"])

# 支持的简历格式白名单（扩展名小写）：
# - pdf  → pypdf 提取纯文本
# - docx → python-docx 提取段落与表格文本
# - txt  → 纯文本解码（utf-8 → gbk）
# 老版 .doc（二进制复合文档）不支持，前端会提示另存为 .docx 或 PDF
ALLOWED_RESUME_EXTS = {"pdf", "docx", "txt"}


@router.post("/api/resume/upload", summary="上传简历并分析")
async def upload_resume(
    request: Request,
    resume: UploadFile = File(...),
    work_experience: str = Form(...),
    target_position: str = Form(...),
    voice_type: str = Form("professional_male")
):
    """上传简历并分析，返回面试token（需登录；支持 PDF / DOCX / TXT，含内容级校验）"""
    logger.info("[Resume] 开始处理上传简历请求")

    # 开始面试必须登录：身份只认请求头里的登录 token，未登录/凭证无效一律 401
    user = get_auth_user(request)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "请先登录后再开始面试"}
        )

    # 配额闸门：面试剩余次数为 0 不允许开新面试。闸门放在最前面——
    # 简历分析本身就调大模型花钱，配额用尽的请求连分析都不该开始。
    # or 0 兜底 interview_quota 为 NULL 的数据
    conn = get_db()
    quota_row = conn.execute(
        'SELECT interview_quota FROM users WHERE id = %s', (user['id'],)
    ).fetchone()
    return_db(conn)
    remaining = (quota_row['interview_quota'] or 0) if quota_row else 0
    if remaining <= 0:
        logger.warning(f"[Resume] 用户 {user['username']}(id={user['id']}) 配额已用尽，拒绝开始面试")
        return JSONResponse(
            status_code=422,
            content={"detail": "面试剩余次数已用完，无法开始新面试。可在主页查看剩余次数"}
        )

    try:
        # 目标岗位必填校验：岗位是出题方向的主要依据，为空会触发后端"前端开发"兜底，
        # 导致丢什么简历都出前端题；strip() 去掉首尾空格，纯空格输入同样视为未填
        if not (target_position and target_position.strip()):
            return JSONResponse(
                status_code=422,
                content={"detail": "目标岗位不能为空，请填写后再上传（出题方向由岗位决定）"}
            )

        # 音色校验：必须在音色列表内，防止前端传入非法值导致 TTS 合成失败
        if voice_type not in INTERVIEWER_VOICES:
            voice_type = "professional_male"

        # 检查文件扩展名（白名单）
        file_ext = resume.filename.split('.')[-1].lower() if resume.filename else ''
        logger.info(f"[Resume] 文件扩展名: {file_ext}")

        if file_ext == 'doc':
            # 老版 Word 二进制格式没有轻量可靠的纯 Python 解析方案，明确引导转换
            return JSONResponse(
                status_code=400,
                content={"status": "error",
                         "message": "暂不支持老版 .doc 格式，请在 Word 中另存为 .docx 或 PDF 后再上传",
                         "error_code": "RESUME_FORMAT_DEPRECATED_DOC"}
            )
        if file_ext not in ALLOWED_RESUME_EXTS:
            return JSONResponse(
                status_code=400,
                content={"status": "error",
                         "message": "简历格式仅支持 PDF / Word(.docx) / TXT",
                         "error_code": "RESUME_FORMAT_NOT_SUPPORTED"}
            )
        # 读取文件内容
        try:
            file_content = await resume.read()
            logger.info(f"[Resume] 成功读取简历内容，大小: {len(file_content)} 字节")
        except Exception as e:
            logger.error(f"[Resume] 错误: 读取简历文件失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"读取简历文件失败: {str(e)}", "error_code": "RESUME_FILE_READ_ERROR"}
            )
        
        # 检查文件大小
        if len(file_content) > 10 * 1024 * 1024:  # 限制文件大小为10MB
            logger.error("[Resume] 错误: 简历文件太大，最大支持10MB")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件太大，最大支持10MB", "error_code": "RESUME_FILE_TOO_LARGE"}
            )
        
        if len(file_content) == 0:
            logger.error("[Resume] 错误: 简历文件为空")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件为空", "error_code": "RESUME_FILE_EMPTY"}
            )

        # 内容级校验（magic bytes）：按扩展名分流检查文件头，拦截改名伪装的文件
        # - PDF  真实文件头固定为 "%PDF-"
        # - DOCX 本质是 zip 容器，文件头为 "PK\x03\x04"
        # - TXT  尝试 utf-8/gbk 解码，解码失败说明是二进制文件（如改名的 exe/图片）
        if file_ext == 'pdf' and not file_content.startswith(b'%PDF-'):
            logger.error("[Resume] 错误: 文件内容不是有效的 PDF（缺少 %PDF- 文件头）")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件不是有效的 PDF（缺少 PDF 文件头）",
                         "error_code": "RESUME_NOT_PDF"}
            )
        if file_ext == 'docx' and not file_content.startswith(b'PK\x03\x04'):
            logger.error("[Resume] 错误: 文件内容不是有效的 DOCX（缺少 zip 文件头）")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "简历文件不是有效的 Word 文档（缺少 docx 文件头）",
                         "error_code": "RESUME_NOT_DOCX"}
            )
        if file_ext == 'txt':
            try:
                file_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    file_content.decode('gbk')
                except UnicodeDecodeError:
                    logger.error("[Resume] 错误: TXT 文件无法按 utf-8/gbk 解码，疑似二进制文件")
                    return JSONResponse(
                        status_code=400,
                        content={"status": "error", "message": "TXT 文件内容不是有效文本，请确认文件未损坏",
                                 "error_code": "RESUME_NOT_TEXT"}
                    )
        
        # 解析简历文件为文本（按文件头自动分流：PDF→pypdf，DOCX→python-docx，TXT→解码），
        # 先出干净文本再做正则分析，避免二进制内容直接当文本喂给分析器
        logger.info("[Resume] 开始解析简历文件")
        try:
            resume_text = extract_resume_text(file_content, resume.filename or "")
        except Exception as e:
            logger.error(f"[Resume] 错误: 解析简历文件异常: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"解析简历文件失败: {str(e)}", "error_code": "RESUME_PARSE_ERROR"}
            )

        if not (resume_text and resume_text.strip()):
            # 常见病因：扫描版/图片型 PDF（pypdf 提不出字）、加密 PDF、损坏文件
            logger.error(f"[Resume] 错误: 简历解析结果为空（{file_ext}）")
            return JSONResponse(
                status_code=422,
                content={"status": "error",
                         "message": "简历内容解析失败：可能是扫描版/图片型简历或文件损坏，请上传可复制文字的 PDF/DOCX/TXT",
                         "error_code": "RESUME_PARSE_EMPTY"}
            )
        logger.info(f"[Resume] 简历解析完成，文本长度: {len(resume_text)} 字符")

        # 分析简历内容（正则结构化：姓名/教育/工作/技能等，输入为上一步的干净文本）
        logger.info("[Resume] 开始分析简历内容")
        try:
            analysis_result = analyze_resume(resume_text, work_experience, target_position)
            logger.info("[Resume] 简历分析完成")
            logger.debug(f"[Resume] 分析结果: {analysis_result}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 分析简历失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"分析简历失败: {str(e)}", "error_code": "RESUME_ANALYSIS_ERROR"}
            )
        
        try:
            token = generate_token()
            logger.info(f"[Resume] 生成token: {token}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成token失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"生成token失败: {str(e)}", "error_code": "TOKEN_GENERATION_ERROR"}
            )
        
        # 保存简历和分析结果到数据库
        try:
            conn = get_db()
            logger.info("[Resume] 连接数据库成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 连接数据库失败: {e}")
            import traceback
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"连接数据库失败: {str(e)}", "error_code": "DATABASE_CONNECTION_ERROR"}
            )
        
        # 面试归属用户：登录态已在函数开头校验，归属人 = 请求头 token 反查出的
        # 登录用户，不信任前端传参
        user_id = user['id']
        logger.info(f"[Resume] 面试归属用户: {user_id} ({user['username']})")
        
        # 插入面试记录
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO interviews (user_id, start_time, status, question_count, voice_reading, voice_type, token)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (user_id, int(time.time()), 1, 5, 1, voice_type, token))
            
            interview_id = cursor.fetchone()["id"]
            logger.info(f"[Resume] 创建面试成功，ID: {interview_id}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 创建面试失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"创建面试失败: {str(e)}", "error_code": "INTERVIEW_CREATION_ERROR"}
            )
        
        # 模拟候选人信息
        candidate = {
            "id": user_id,
            "name": "个人用户",
            "email": "user@example.com",
            "position_id": 1
        }
        logger.debug(f"[Resume] 候选人信息: {candidate}")
        
        # 模拟职位信息
        position = {
            "id": 1,
            "name": target_position or "前端开发",
            "description": "前端开发岗位",
            "requirements": "",
            "responsibilities": ""
        }
        logger.debug(f"[Resume] 职位信息: {position}")
        
        # 模拟面试信息（voice_type 用上传接口收到的选定音色，
        # 出题时按它预生成每题语音）
        interview_dict = {
            "id": interview_id,
            "user_id": user_id,
            "interview_type_id": 1,
            "status": 1,
            "voice_type": voice_type
        }
        logger.debug(f"[Resume] 面试信息: {interview_dict}")
        
        # 生成问题
        try:
            logger.info("[Resume] 开始生成面试问题")
            resume_analysis_info = f"\n\n简历分析结果：\n{json.dumps(analysis_result, ensure_ascii=False)}"
            logger.info(f"[Resume] 简历分析信息长度: {len(resume_analysis_info)}")
            logger.debug(f"[Resume] 简历分析信息: {resume_analysis_info[:200]}...")  # 只记录前200个字符
            
            result = generate_questions(interview_id, candidate, position, interview_dict, resume_analysis_info, cursor, conn)
            logger.info("[Resume] 生成面试问题成功")
            logger.debug(f"[Resume] 生成问题结果: {result}")
            # 注意：generate_questions 函数已经关闭了数据库连接，所以这里不需要再执行 return_db(conn)
            logger.info("[Resume] 上传简历请求处理完成")
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "token": token,
                    "interview_id": interview_id,
                    "message": "上传简历成功，已生成面试问题"
                }
            )
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成面试问题失败: {e}")
            import traceback
            traceback.print_exc()
            # 注意：generate_questions 函数可能已经关闭了数据库连接，所以这里不需要再执行 return_db(conn)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"生成面试问题失败: {str(e)}", "error_code": "QUESTION_GENERATION_ERROR"}
            )
        
    except Exception as e:
        logger.error(f"[Resume] 上传简历失败: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"上传简历失败: {str(e)}",
                "error_code": "UNKNOWN_ERROR"
            }
        )
