"""
面试问题生成服务模块
====================
本模块负责调用prompt.py文件中的build_interview_prompt函数生成面试问题
基于阿里云 DashScope qwen-vl-plus 多模态模型
"""

import json
import logging
import os
import requests
from app.config.config import DASHSCOPE_API_KEY
from app.services.speech_service import synthesize_speech


logger = logging.getLogger(__name__)# 日志记录器，用于记录程序运行时的事件和错误信息显示在控制台

def call_llm_api(prompt, resume_image=None):
    """
    调用阿里云 DashScope 大模型 API
    
    Args: 参数说明
        prompt: 发送给大模型的提示文本
        resume_image: 简历截图（base64编码），可选
    
    Returns:
        dict: API 返回的 JSON 结果，失败时返回 None
    """
    # 从环境变量获取 API Key
    api_key = os.getenv('DASHSCOPE_API_KEY') or DASHSCOPE_API_KEY#os.getenv与DASHSCOPE_API_KEY是等价的
    
    if not api_key:
        logger.warning("[Question] 未配置DASHSCOPE_API_KEY")
        return None
    
    # 阿里云 DashScope API 地址（OpenAI 兼容模式）
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 构建消息内容（支持文本和图片）
    content = [{"type": "text", "text": prompt}]
    if resume_image:
        # 添加简历截图到消息中
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{resume_image}"}
        })
    
    # API 请求参数
    data = {
        "model": "qwen-vl-plus",  # 支持多模态的模型
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 2000,
        "temperature": 0.7
    }
    
    try:
        # 发送请求
        response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"[Question] API错误: {response.status_code}")
            return None
        
        response_json = response.json()
        
        # 验证响应格式
        if 'choices' not in response_json:
            logger.error("[Question] 响应缺少choices字段")
            return None
        
        message = response_json['choices'][0]['message']
        if 'content' not in message:
            logger.error("[Question] 响应缺少content字段")
            return None
        
        # 解析返回的 JSON
        return json.loads(message['content'])
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


def generate_questions(interview_id, candidate, position, interview, latest_tech_info, cursor, conn, resume_image=None):
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
        resume_image: 简历截图（base64编码）
    
    Returns:
        dict: 包含状态、消息和问题列表的响应字典
    """
    logger.info("[Question] 开始生成面试问题")
    
    try:
        # 1. 构建 prompt 并调用大模型
        prompt = build_prompt(candidate, position, latest_tech_info)
        llm_result = call_llm_api(prompt, resume_image)
        
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
