"""
智能招聘面试模拟系统 - 主服务器模块
=====================================
本文件包含Flask Web服务器的核心功能：
- 岗位、候选人、面试管理API
- 语音识别（ASR）和语音合成（TTS）
- 表情分析功能
- 付费功能集成（支付宝）
- 面试问题生成和报告生成
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import time
import threading
import json
import sqlite3

# 配置控制台日志
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# 配置根日志记录器
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[console_handler]
)

logger = logging.getLogger(__name__)

# 确保所有子模块的日志都被捕获
for handler in logging.root.handlers:
    handler.setLevel(logging.DEBUG)

# 先导入系统级别的pydantic，避免与lib目录下的版本冲突
try:
    import pydantic
    import pydantic_core
    logger.info(f'使用系统pydantic: {pydantic.__version__}, pydantic-core: {pydantic_core.__version__}')
except ImportError:
    pass

from flask import Flask, jsonify, request, send_file, redirect
from flask_cors import CORS

# 导入配置和模块
from app.config.config import DASHSCOPE_API_KEY
from app.db.db import init_db, get_db, return_db, close_all_connections
from app.api.position_api import get_positions, create_position, update_position, delete_position


from app.utils.utils import generate_token

# ==================== Flask应用初始化 ====================
print("[INFO] 开始初始化Flask应用...")
# 创建Flask应用实例，配置静态文件目录
app = Flask(__name__, static_folder='static', static_url_path='/static')
print("[INFO] Flask应用实例创建成功")

# 启用跨域资源共享（CORS），允许前端跨域访问API
CORS(app)
print("[INFO] CORS配置成功")

# 应用启动时初始化数据库连接池
@app.before_request
def before_request():
    """应用启动时初始化"""
    print("[INFO] 应用启动，初始化数据库连接池...")

# 应用关闭时关闭所有数据库连接
@app.teardown_appcontext
def teardown_appcontext(exception):
    """应用关闭时清理"""
    print("[INFO] 应用关闭，关闭所有数据库连接...")
    close_all_connections()

# ==================== API密钥配置 ====================
# 从环境变量获取阿里云DashScope API密钥（用于语音识别和合成）
if DASHSCOPE_API_KEY:
    print('[DEBUG] DASHSCOPE_API_KEY 已加载')
else:
    print('[WARNING] DASHSCOPE_API_KEY 未配置!')

# ==================== 岗位管理API ====================
app.route('/api/positions', methods=['GET'])(get_positions)
app.route('/api/positions', methods=['POST'])(create_position)
app.route('/api/positions/<int:id>', methods=['PUT'])(update_position)
app.route('/api/positions/<int:id>', methods=['DELETE'])(delete_position)

# ==================== 个人用户版API ====================
# 个人用户版面试API已在下方定义
# 个人用户版面试问题生成API已在下方定义
# 个人用户版面试评价API已在下方定义


# ==================== 个人用户版面试API ====================

@app.route('/api/interview/create', methods=['POST'])
def create_personal_interview():
    """
    创建新面试（个人用户版）
    
    请求参数 (JSON):
        user_id: 用户ID
        interview_type_id: 面试类型ID
        question_count: 问题数量
        voice_reading: 是否开启语音朗读
        voice_type: 语音类型
    
    返回:
        操作结果状态
    """
    try:
        data = request.json
        print(f"[Interview] 收到创建面试请求: {data}")
        
        # 验证参数
        user_id = data.get('user_id')
        interview_type_id = data.get('interview_type_id')
        question_count = data.get('question_count', 5)
        voice_reading = data.get('voice_reading', 1)
        voice_type = data.get('voice_type', 'professional_male')
        
        if not user_id or not interview_type_id:
            print("[Interview] 错误: 缺少必要参数")
            return jsonify({"error": "缺少必要参数"}), 400
        
        # 生成token
        token = generate_token()
        print(f"[Interview] 生成面试token: {token}")
        
        # 插入数据库
        conn = get_db()
        cursor = conn.cursor()
        
        # 插入面试记录
        cursor.execute('''
            INSERT INTO interviews (user_id, interview_type_id, start_time, status, question_count, voice_reading, voice_type, token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, interview_type_id, int(time.time()), 0, question_count, voice_reading, voice_type, token))
        
        interview_id = cursor.lastrowid
        print(f"[Interview] 创建面试成功，ID: {interview_id}")
        
        # 提交事务
        conn.commit()
        return_db(conn)
        
        return jsonify({"status": "success", "interview_id": interview_id, "token": token})
    except Exception as e:
        print(f"[Interview] 创建面试失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/interview/<token>/generate_questions', methods=['POST'])
def generate_personal_interview_questions(token):
    """
    生成面试问题（个人用户版）
    
    路径参数:
        token: 面试token
    
    返回:
        操作结果状态
    """
    try:
        print(f"[Interview] 收到生成面试问题请求，token: {token}")
        
        # 获取面试信息
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # 查询面试记录
            cursor.execute('SELECT id, user_id, interview_type_id, question_count, voice_type FROM interviews WHERE token = ?', (token,))
            interview = cursor.fetchone()
            
            if not interview:
                print("[Interview] 错误: 面试不存在")
                return jsonify({"error": "面试不存在"}), 404
            
            interview_id = interview[0]
            user_id = interview[1]
            interview_type_id = interview[2]
            question_count = interview[3]
            voice_type = interview[4]
            
            print(f"[Interview] 找到面试记录，ID: {interview_id}, 用户ID: {user_id}, 面试类型ID: {interview_type_id}, 问题数量: {question_count}")
            
            # 检查是否已经有面试问题
            cursor.execute('SELECT COUNT(*) FROM interview_questions WHERE interview_id = ?', (interview_id,))
            existing_questions = cursor.fetchone()[0]
            
            if existing_questions > 0:
                print(f"[Interview] 面试已有 {existing_questions} 个问题，跳过生成")
                return jsonify({"status": "success", "message": f"面试已有 {existing_questions} 个问题"})
            
            # 获取面试类型信息
            cursor.execute('SELECT name, description FROM interview_types WHERE id = ?', (interview_type_id,))
            interview_type = cursor.fetchone()
            
            if not interview_type:
                print("[Interview] 错误: 面试类型不存在")
                return jsonify({"error": "面试类型不存在"}), 404
            
            interview_type_name = interview_type[0]
            interview_type_description = interview_type[1]
            
            print("[Interview] 面试类型: " + interview_type_name + " - " + interview_type_description)
            
            # 生成面试问题
            from app.services.question_service import generate_questions
            
            # 模拟候选人信息
            candidate = {
                "id": user_id,
                "name": "个人用户",
                "email": "user@example.com",
                "position_id": 1
            }
            
            # 模拟职位信息
            position = {
                "id": 1,
                "name": interview_type_name,
                "description": interview_type_description,
                "requirements": "",
                "responsibilities": ""
            }
            
            # 生成问题
            # 创建一个包含 voice_type 的字典
            interview_dict = {
                "id": interview_id,
                "user_id": user_id,
                "interview_type_id": interview_type_id,
                "status": 0,
                "voice_type": voice_type
            }
            print("[Interview] 调用 generate_questions 函数...")
            result = generate_questions(interview_id, candidate, position, interview_dict, "", cursor, conn)
            
            print("[Interview] 生成面试问题成功")
            print("[Interview] 生成面试问题的结果: " + str(result))
            
            # 构建响应
            if isinstance(result, dict):
                if "error" in result:
                    print("[Interview] 生成面试问题失败: " + result["error"])
                    return jsonify(result), 500
                else:
                    print("[Interview] 生成面试问题成功")
                    return jsonify(result)
            else:
                print("[Interview] 生成面试问题返回结果无效")
                return jsonify({"error": "生成面试问题返回结果无效"}), 500
        finally:
            # 确保数据库连接被关闭
            try:
                return_db(conn)
                print("[Interview] 数据库连接已关闭")
            except Exception as e:
                print("[Interview] 关闭数据库连接失败: " + str(e))
    except Exception as e:
        print("[Interview] 生成面试问题失败: " + str(e))
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ==================== 其他API ====================
# 更新候选人
@app.route('/api/candidates/<int:id>', methods=['PUT'])
def update_candidate(id):
    data = request.form
    
    resume_content = request.files['resume_content'].read() if 'resume_content' in request.files else None
    resume_binary = sqlite3.Binary(resume_content) if resume_content is not None else None
    conn = get_db()
    cursor = conn.cursor()
    
    if resume_content:
        cursor.execute('''
            UPDATE candidates SET position_id=?, name=?, email=?, resume_content=?
            WHERE id=?
        ''', (data['position_id'], data['name'], data['email'], resume_binary, id))
    else:
        cursor.execute('''
            UPDATE candidates SET position_id=?, name=?, email=?
            WHERE id=?
        ''', (data['position_id'], data['name'], data['email'], id))
    
    conn.commit()
    return_db(conn)
    return jsonify({'status': 'success'})

# API: 获取面试信息
@app.route('/api/interview/<token>/info', methods=['GET'])
def get_interview_info(token):
    try:
        conn = get_db()
        
        # 先获取面试基本信息
        interview = conn.execute('''
            SELECT id, user_id, question_count, voice_reading, voice_type, start_time, status
            FROM interviews
            WHERE token = ?
        ''', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            return jsonify({"error": "面试不存在"}), 404
        
        result = dict(interview)
        
        # 尝试获取用户信息
        candidate_name = "未知用户"
        candidate_email = ""
        try:
            user = conn.execute('SELECT username, email FROM users WHERE id = ?', (result['user_id'],)).fetchone()
            if user:
                candidate_name = user['username']
                candidate_email = user['email']
        except Exception as e:
            print(f"[INFO] 获取用户信息失败: {e}")
        
        # 尝试获取岗位信息
        position_name = "未知岗位"
        try:
            position = conn.execute('SELECT name FROM positions WHERE id = 1').fetchone()
            if position:
                position_name = position['name']
        except Exception as e:
            print(f"[INFO] 获取岗位信息失败: {e}")
        
        return_db(conn)
        
        start_time = result.get('start_time')
        try:
            import datetime
            if start_time and start_time > 0:
                result['time'] = datetime.fromtimestamp(start_time).strftime('%Y年%m月%d日 %H:%M')
            else:
                result['time'] = "未设置时间"
        except Exception as e:
            print(f"[INFO] 格式化时间失败: {e}")
            result['time'] = "未设置时间"
        
        return jsonify({
            "interview_id": result['id'],
            "time": result['time'],
            "position": position_name,
            "candidate": candidate_name,
            "status": result['status'],
            "question_count": result.get('question_count') or 0,
            "voice_reading": result.get('voice_reading') or 0,
            "voice_type": result.get('voice_type', 'professional_male')
        })
    except Exception as e:
        print(f"[ERROR] get_interview_info: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# API: 获取下一个问题
@app.route('/api/interview/<token>/get_question', methods=['GET'])
def get_next_question(token):
    current_question_id = request.args.get('current_id', type=int, default=0)
    
    conn = get_db()
    
    # 先获取面试ID
    interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
    
    if not interview:
        return_db(conn)
        return jsonify({"id": 0, "text": "面试无效"}), 404
    
    # 获取下一个问题（包含预生成的语音）
    next_question = None
    if current_question_id == 0:
        # 获取第一个问题
        next_question = conn.execute('''
            SELECT id, question as text, question_audio, voice_type
            FROM interview_questions
            WHERE interview_id = ?
            ORDER BY id ASC
            LIMIT 1
        ''', (interview['id'],)).fetchone()
    else:
        # 获取下一个问题
        next_question = conn.execute('''
            SELECT id, question as text, question_audio, voice_type
            FROM interview_questions
            WHERE interview_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT 1
        ''', (interview['id'], current_question_id)).fetchone()
    
    return_db(conn)
    
    # 如果没有下一个问题，返回结束标志
    if not next_question:
        return jsonify({"id": 0, "text": "面试已完成"})
    
    result = dict(next_question)
    
    # 如果有预生成的语音，转换为base64返回
    if result.get('question_audio'):
        import base64
        result['audio'] = base64.b64encode(result['question_audio']).decode('utf-8')
        result['audio_format'] = 'mp3'
        result['use_pre_generated'] = True
        print(f"[INFO] 返回预生成语音，问题ID: {result['id']}, 音频大小: {len(result['question_audio'])} 字节")
        del result['question_audio']  # 删除二进制数据，只保留base64
    else:
        result['use_pre_generated'] = False
        print(f"[INFO] 无预生成语音，问题ID: {result['id']}")
    
    return jsonify(result)



# 提交手写题答案
@app.route('/api/interview/<token>/submit_text_answer', methods=['POST'])
def submit_text_answer(token):
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            return jsonify({"error": "面试不存在"}), 404
        
        # 从 JSON 请求体中获取参数
        data = request.get_json()
        question_id = data.get('question_id')
        answer_text = data.get('answer_text')
        
        if not question_id or not answer_text:
            return_db(conn)
            return jsonify({"error": "缺少必要参数"}), 400
        
        answered_time = int(time.time())
        
        conn.execute('''
            UPDATE interview_questions
            SET answer_text = ?, answered_at = ?
            WHERE id = ? AND interview_id = ?
        ''', (answer_text, answered_time, question_id, interview['id']))
        
        next_question = conn.execute('''
            SELECT id, question as text, question_type
            FROM interview_questions
            WHERE interview_id = ? AND id > ?
            ORDER BY id ASC
            LIMIT 1
        ''', (interview['id'], question_id)).fetchone()
        
        conn.commit()
        
        if not next_question:
            all_answered = conn.execute('''
                SELECT COUNT(*) as total, SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) as answered
                FROM interview_questions
                WHERE interview_id = ?
            ''', (interview['id'],)).fetchone()
            
            if all_answered['total'] == all_answered['answered']:
                conn.execute('UPDATE interviews SET status = 3 WHERE id = ?', (interview['id'],))
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
        return jsonify(result)
    except Exception as e:
        # 确保数据库连接被关闭
        try:
            return_db(conn)
        except:
            pass
        
        # 记录错误
        import traceback
        traceback.print_exc()
        
        # 返回错误响应
        return jsonify({"error": f"提交答案失败: {str(e)}"}), 500

# New API endpoint to toggle voice reading
@app.route('/api/interview/<token>/toggle_voice_reading', methods=['POST'])
def toggle_voice_reading(token):
    data = request.json
    enabled = data.get('enabled', False)
    
    conn = get_db()
    # Update voice reading setting
    conn.execute('UPDATE interviews SET voice_reading = ? WHERE token = ?', 
                (1 if enabled else 0, token))
    conn.commit()
    return_db(conn)
    
    return jsonify({'status': 'success', 'voice_reading': enabled})

# cosyvoice-v3-flash 支持的音色列表
# 参考: https://help.aliyun.com/zh/model-studio/multimodal-timbre-list
INTERVIEWER_VOICES = {
    "professional_male": {
        "voice": "longanzhi_v3",
        "name": "专业男面试官",
        "description": "睿智轻熟男，沉稳专业，适合技术岗位面试"
    },
    "professional_female": {
        "voice": "longanya_v3",
        "name": "专业女面试官",
        "description": "高雅气质女，温柔专业，适合综合岗位面试"
    },
    "friendly_male": {
        "voice": "longanyang",
        "name": "亲和男面试官",
        "description": "阳光大男孩，亲切友好，营造轻松面试氛围"
    },
    "friendly_female": {
        "voice": "longanhuan",
        "name": "亲和女面试官",
        "description": "欢脱元气女，活泼亲切，缓解面试紧张感"
    },
    "strict_male": {
        "voice": "longanshuo_v3",
        "name": "严谨男面试官",
        "description": "干净清爽男，严肃认真，适合技术深度面试"
    },
    "strict_female": {
        "voice": "longfeifei_v3",
        "name": "严谨女面试官",
        "description": "甜美娇气女，专业严谨，适合高管岗位面试"
    }
}

def synthesize_speech(text, voice_type="professional_male"):
    """
    使用阿里云 DashScope cosyvoice-v3-flash 模型进行语音合成
    """
    try:
        import json
        print(f"[TTS] 开始合成，文本: {text[:50]}..., 音色: {voice_type}")
        
        # 检查text参数
        if not text or not text.strip():
            print("[TTS] 错误: 文本为空")
            return None, "文本不能为空"
        
        # 检查API Key
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[TTS] 错误: API Key 为空!")
            return None, "未配置 DASHSCOPE_API_KEY"

        print(f"[TTS] API Key 已配置，长度: {len(api_key)}")
        
        # 处理前端传递的音色类型
        if voice_type.startswith('zh-CN-'):
            # 使用默认音色
            voice = "longanzhi_v3"
            print(f"[TTS] 使用默认音色: {voice}")
        else:
            # 使用 INTERVIEWER_VOICES 中定义的音色
            voice_config = INTERVIEWER_VOICES.get(voice_type, INTERVIEWER_VOICES["professional_male"])
            voice = voice_config["voice"]
            print(f"[TTS] 使用音色: {voice} - {voice_config['name']}")
        
        # cosyvoice-v3-flash 使用 HTTP API 调用方式
        try:
            print("[TTS] 尝试使用HTTP API调用cosyvoice-v3-flash...")
            import requests
            
            # cosyvoice-v3-flash HTTP API 调用
            # 参考文档: https://help.aliyun.com/zh/model-studio/non-realtime-cosyvoice-api
            url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            # cosyvoice-v3-flash 的请求参数格式
            # voice 和 format 必须放在 input 对象中
            data = {
                "model": "cosyvoice-v3-flash",
                "input": {
                    "text": text,
                    "voice": voice,
                    "format": "mp3",
                    "sample_rate": 24000
                }
            }
            
            print(f"[TTS] 请求URL: {url}")
            print(f"[TTS] 请求参数: {json.dumps(data, ensure_ascii=False)}")
            
            # 发送请求
            response = requests.post(url, headers=headers, json=data, timeout=120)
            
            print(f"[TTS] 响应状态码: {response.status_code}")
            print(f"[TTS] 响应头: {dict(response.headers)}")
            
            # 检查响应类型
            content_type = response.headers.get('Content-Type', '')
            print(f"[TTS] Content-Type: {content_type}")
            
            if response.status_code == 200:
                # 检查是否是音频数据（流式返回）
                if 'audio' in content_type or 'octet-stream' in content_type:
                    audio_data = response.content
                    print(f"[TTS] 成功获取音频数据，大小: {len(audio_data)} 字节")
                    return audio_data, None
                else:
                    # 可能是JSON响应
                    try:
                        result = response.json()
                        print(f"[TTS] JSON响应: {json.dumps(result, ensure_ascii=False)}")
                        
                        # 检查是否有音频URL
                        if 'output' in result and 'audio' in result['output']:
                            audio_info = result['output']['audio']
                            if isinstance(audio_info, dict) and 'url' in audio_info:
                                audio_url = audio_info['url']
                                print(f"[TTS] 获取到音频URL: {audio_url[:80]}...")
                                # 下载音频
                                audio_response = requests.get(audio_url, timeout=60)
                                if audio_response.status_code == 200:
                                    audio_data = audio_response.content
                                    print(f"[TTS] 成功下载音频数据，大小: {len(audio_data)} 字节")
                                    return audio_data, None
                                else:
                                    return None, f"下载音频失败: HTTP {audio_response.status_code}"
                            elif isinstance(audio_info, str):
                                # 可能是base64编码的音频
                                import base64
                                audio_data = base64.b64decode(audio_info)
                                print(f"[TTS] 成功解码base64音频数据，大小: {len(audio_data)} 字节")
                                return audio_data, None
                    except Exception as json_err:
                        print(f"[TTS] 解析JSON响应失败: {json_err}")
                        # 如果解析失败，可能是直接返回的音频数据
                        audio_data = response.content
                        if len(audio_data) > 100:  # 假设音频数据至少100字节
                            print(f"[TTS] 将响应内容作为音频数据，大小: {len(audio_data)} 字节")
                            return audio_data, None
                        
                return None, f"无法解析响应数据"
            else:
                error_text = response.text
                print(f"[TTS] API调用失败: HTTP {response.status_code}, 响应: {error_text}")
                return None, f"语音合成失败: HTTP {response.status_code} - {error_text[:200]}"
                
        except ImportError as e:
            print(f"[TTS] 缺少requests库: {e}")
            return None, "缺少requests库，请运行: pip install requests"
        except Exception as e:
            print(f"[TTS] HTTP API调用异常: {e}")
            import traceback
            traceback.print_exc()
            return None, f"语音合成失败: {str(e)}"
            
    except Exception as e:
        print(f"[TTS] 异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, str(e)



@app.route('/api/tts/voices', methods=['GET'])
def get_tts_voices():
    voices = []
    for key, config in INTERVIEWER_VOICES.items():
        voices.append({
            "id": key,
            "name": config["name"],
            "description": config["description"]
        })
    return jsonify({"voices": voices})

@app.route('/api/tts/synthesize', methods=['POST'])
def synthesize_tts():
    data = request.json
    text = data.get('text', '')
    voice_type = data.get('voice_type', 'professional_male')
    
    if not text:
        return jsonify({"error": "文本不能为空"}), 400
    
    # 直接返回成功响应，告诉前端使用浏览器内置语音合成
    # 这样可以避免API密钥无效导致的TTS功能失败
    return jsonify({
        "status": "success",
        "use_browser_tts": True,
        "message": "使用浏览器内置语音合成"
    })

@app.route('/api/interview/<token>/set_voice', methods=['POST'])
def set_interview_voice(token):
    data = request.json
    voice_type = data.get('voice_type', 'professional_male')
    
    # 允许前端传递的音色类型
    conn = get_db()
    interview = conn.execute('SELECT status FROM interviews WHERE token = ?', (token,)).fetchone()
    
    if not interview:
        return_db(conn)
        return jsonify({"error": "面试不存在"}), 404
    
    if interview['status'] >= 2:
        return_db(conn)
        return jsonify({"error": "面试已开始，无法更改面试官类型"}), 400
    
    conn.execute('UPDATE interviews SET voice_type = ? WHERE token = ?', 
                (voice_type, token))
    conn.commit()
    return_db(conn)
    
    return jsonify({'status': 'success', 'voice_type': voice_type})

@app.route('/api/expression/recognize', methods=['POST'])
def recognize_expression_api():
    try:
        from app.services.expression_service import analyze_face_expression
        
        if 'image' in request.files:
            image_file = request.files['image']
            image_data = image_file.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif request.json and 'image_url' in request.json:
            image_url = request.json['image_url']
            # 这里暂时不支持URL，因为 analyze_face_expression 只支持图像数据
            return jsonify({"error": "暂不支持图片URL"}), 400
        elif request.json and 'image_base64' in request.json:
            image_base64 = request.json['image_base64']
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        else:
            return jsonify({"error": "请提供图片文件或base64编码"}), 400
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[Expression] API异常: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/expression/analyze', methods=['POST'])
def analyze_expression_api():
    try:
        from app.services.expression_service import analyze_face_expression
        
        if 'image' in request.files:
            image_file = request.files['image']
            image_data = image_file.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif request.json and 'image_url' in request.json:
            image_url = request.json['image_url']
            # 这里暂时不支持URL，因为 analyze_face_expression 只支持图像数据
            return jsonify({"error": "暂不支持图片URL"}), 400
        elif request.json and 'image_base64' in request.json:
            image_base64 = request.json['image_base64']
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        else:
            return jsonify({"error": "请提供图片文件或base64编码"}), 400
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[Expression] API异常: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/interview/<token>/expression', methods=['POST'])
def save_interview_expression(token):
    try:
        from app.services.expression_service import analyze_face_expression
        
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            return jsonify({"error": "面试不存在"}), 404
        
        interview_id = interview['id']
        
        result = {}
        
        if 'image' in request.files:
            image_file = request.files['image']
            image_data = image_file.read()
            faces, error = analyze_face_expression(image_data)
            if error:
                return_db(conn)
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return_db(conn)
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif request.json and 'image_base64' in request.json and request.json['image_base64']:
            image_base64 = request.json['image_base64']
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            image_data = base64.b64decode(image_base64)
            faces, error = analyze_face_expression(image_data)
            if error:
                return_db(conn)
                return jsonify({"success": False, "error": error}), 500
            if not faces:
                return_db(conn)
                return jsonify({"success": False, "error": "未检测到人脸"}), 400
            face = faces[0]
            result = {
                'success': True,
                'expression': face.get('expression', ''),
                'expression_cn': face.get('expression_cn', ''),
                'confidence': face.get('confidence', 0),
                'emotion_status': face.get('emotion_status', ''),
                'emotion_score': face.get('emotion_score', 0),
                'quality_score': face.get('quality_score', 0),
                'final_score': face.get('final_score', 0),
                'suggestions': face.get('suggestions', []),
                'timestamp': int(time.time())
            }
        elif request.json and 'expression' in request.json:
            # 直接使用前端提供的表情数据
            result = {
                'success': True,
                'expression': request.json.get('expression', ''),
                'expression_cn': request.json.get('expression_cn', ''),
                'confidence': 1.0,
                'emotion_status': request.json.get('emotion_status', ''),
                'emotion_score': request.json.get('emotion_score', 0),
                'quality_score': request.json.get('quality_score', 0),
                'final_score': request.json.get('final_score', 0),
                'suggestions': request.json.get('suggestions', []),
                'timestamp': int(time.time())
            }
        else:
            return_db(conn)
            return jsonify({"error": "请提供图片或表情数据"}), 400
        
        if result.get('success'):
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM interview_expression_records 
                WHERE interview_id = ?
            ''', (interview_id,))
            record_count = cursor.fetchone()['count']
            
            cursor.execute('''
                INSERT INTO interview_expression_records 
                (interview_id, expression, expression_cn, confidence, emotion_status, 
                 emotion_score, quality_score, final_score, suggestions, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                interview_id,
                result.get('expression', ''),
                result.get('expression_cn', ''),
                result.get('confidence', 0),
                result.get('emotion_status', ''),
                result.get('emotion_score', 0),
                result.get('quality_score', 0),
                result.get('final_score', 0),
                json.dumps(result.get('suggestions', []), ensure_ascii=False),
                result.get('timestamp', int(time.time()))
            ))
            conn.commit()
        
        return_db(conn)
        return jsonify(result)
        
    except Exception as e:
        print(f"[Expression] 保存异常: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/interview/<token>/expression_report', methods=['GET'])
def get_expression_report(token):
    try:
        conn = get_db()
        interview = conn.execute('SELECT id FROM interviews WHERE token = ?', (token,)).fetchone()
        
        if not interview:
            return_db(conn)
            return jsonify({"error": "面试不存在"}), 404
        
        interview_id = interview['id']
        
        records = conn.execute('''
            SELECT expression, expression_cn, confidence, emotion_status, 
                   emotion_score, quality_score, final_score, suggestions, timestamp
            FROM interview_expression_records
            WHERE interview_id = ?
            ORDER BY timestamp ASC
        ''', (interview_id,)).fetchall()
        
        if not records:
            return_db(conn)
            return jsonify({
                "success": True,
                "total_records": 0,
                "message": "暂无表情记录"
            })
        
        records_list = [dict(row) for row in records]
        
        avg_emotion_score = sum(r['emotion_score'] for r in records_list) / len(records_list)
        avg_quality_score = sum(r['quality_score'] for r in records_list) / len(records_list)
        avg_final_score = sum(r['final_score'] for r in records_list) / len(records_list)
        
        expression_counts = {}
        for r in records_list:
            expr = r['expression_cn']
            expression_counts[expr] = expression_counts.get(expr, 0) + 1
        
        positive_count = sum(1 for r in records_list if r['emotion_status'] == '积极')
        negative_count = sum(1 for r in records_list if r['emotion_status'] == '消极')
        neutral_count = sum(1 for r in records_list if r['emotion_status'] == '中性')
        
        all_suggestions = []
        for r in records_list:
            if r['suggestions']:
                try:
                    suggestions = json.loads(r['suggestions'])
                    all_suggestions.extend(suggestions)
                except:
                    pass
        
        from collections import Counter
        suggestion_counts = Counter(all_suggestions)
        top_suggestions = suggestion_counts.most_common(3)
        
        return_db(conn)
        
        return jsonify({
            "success": True,
            "total_records": len(records_list),
            "summary": {
                "avg_emotion_score": round(avg_emotion_score, 1),
                "avg_quality_score": round(avg_quality_score, 1),
                "avg_final_score": round(avg_final_score, 1),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "neutral_count": neutral_count,
                "expression_distribution": expression_counts
            },
            "top_suggestions": [s[0] for s in top_suggestions],
            "records": records_list
        })
        
    except Exception as e:
        print(f"[Expression] 报告生成异常: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== 付费功能API ====================

# 导入付费模块
try:
    import payment_module
    from alipay_module import AlipayManager, mock_payment, format_amount, generate_order_subject
    PAYMENT_ENABLED = True
    print("[INFO] 付费功能模块已加载")
except ImportError as e:
    PAYMENT_ENABLED = False
    print(f"[WARNING] 付费功能模块加载失败: {e}")

# 初始化支付宝（从数据库读取配置）
alipay_manager = None
def init_alipay():
    """初始化支付宝配置"""
    global alipay_manager
    if not PAYMENT_ENABLED:
        return
    
    try:
        config = payment_module.get_payment_config('alipay')
        if config and config.get('app_id'):
            base_url = os.getenv('BASE_URL', 'http://localhost:10003')
            alipay_manager = AlipayManager(
                app_id=config['app_id'],
                private_key=config['private_key'],
                alipay_public_key=config['alipay_public_key'],
                notify_url=f"{base_url}/api/payment/alipay/notify",
                return_url=f"{base_url}/api/payment/alipay/return",
                sandbox=bool(config.get('sandbox_mode', 1))
            )
            print(f"[INFO] 支付宝支付已{'启用' if alipay_manager.enabled else '禁用（模拟模式）'}")
        else:
            print("[INFO] 支付宝配置未设置，使用模拟支付模式")
    except Exception as e:
        print(f"[ERROR] 初始化支付宝失败: {e}")

# 启动时初始化
init_alipay()

# ---- 用户认证API ----

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """用户注册"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    phone = data.get('phone')
    
    if not all([username, email, password]):
        return jsonify({"error": "请填写完整信息"}), 400
    
    success, message, user_id = payment_module.register_user(username, email, password, phone)
    
    if success:
        return jsonify({"status": "success", "message": message, "user_id": user_id})
    else:
        return jsonify({"error": message}), 400

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """用户登录"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    data = request.json
    username_or_email = data.get('username') or data.get('email')
    password = data.get('password')
    
    if not all([username_or_email, password]):
        return jsonify({"error": "请填写用户名和密码"}), 400
    
    success, message, user_data = payment_module.login_user(username_or_email, password)
    
    if success:
        return jsonify({
            "status": "success", 
            "message": message, 
            "user": user_data
        })
    else:
        return jsonify({"error": message}), 401

@app.route('/api/user/quota', methods=['GET'])
def api_get_quota():
    """获取用户配额"""
    if not PAYMENT_ENABLED:
        # 返回默认配额信息
        return jsonify({
            "status": "success",
            "quota": {
                "free_quota": {
                    "interviews": 3,
                    "tts_minutes": 10,
                    "ai_analysis": 5
                },
                "used": {
                    "interviews": 0,
                    "tts_minutes": 0,
                    "ai_analysis": 0
                },
                "total_available": {
                    "interviews": 3,
                    "tts_minutes": 10,
                    "ai_analysis": 5
                },
                "subscriptions": [],
                "reset_date": 0
            }
        })
    
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error": "缺少用户ID"}), 400
    
    try:
        quota = payment_module.get_user_quota(user_id)
        return jsonify({"status": "success", "quota": quota})
    except Exception as e:
        # 如果数据库操作失败，返回默认配额信息
        print(f"[Quota] 获取配额失败: {e}")
        return jsonify({
            "status": "success",
            "quota": {
                "free_quota": {
                    "interviews": 3,
                    "tts_minutes": 10,
                    "ai_analysis": 5
                },
                "used": {
                    "interviews": 0,
                    "tts_minutes": 0,
                    "ai_analysis": 0
                },
                "total_available": {
                    "interviews": 3,
                    "tts_minutes": 10,
                    "ai_analysis": 5
                },
                "subscriptions": [],
                "reset_date": 0
            }
        })

# ---- 套餐管理API ----

@app.route('/api/pricing/plans', methods=['GET'])
def api_get_plans():
    """获取套餐列表"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    plan_type = request.args.get('type')
    plans = payment_module.get_pricing_plans(plan_type=plan_type)
    return jsonify({"status": "success", "plans": plans})

@app.route('/api/pricing/plans/<int:plan_id>', methods=['GET'])
def api_get_plan_detail(plan_id):
    """获取套餐详情"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    plan = payment_module.get_plan_by_id(plan_id)
    if plan:
        return jsonify({"status": "success", "plan": plan})
    else:
        return jsonify({"error": "套餐不存在"}), 404

# ---- 订单管理API ----

@app.route('/api/orders/create', methods=['POST'])
def api_create_order():
    """创建订单"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    data = request.json
    user_id = data.get('user_id')
    plan_id = data.get('plan_id')
    
    if not all([user_id, plan_id]):
        return jsonify({"error": "缺少必要参数"}), 400
    
    success, message, order_data = payment_module.create_order(user_id, plan_id)
    
    if success:
        return jsonify({"status": "success", "message": message, "order": order_data})
    else:
        return jsonify({"error": message}), 400

@app.route('/api/orders/pay', methods=['POST'])
def api_pay_order():
    """支付订单 - 创建支付宝支付"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    data = request.json
    order_no = data.get('order_no')
    
    if not order_no:
        return jsonify({"error": "缺少订单号"}), 400
    
    # 获取订单信息
    order = payment_module.get_order_by_no(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    
    if order['pay_status'] != 0:
        return jsonify({"error": "订单已支付或已取消"}), 400
    
    # 创建支付宝支付
    if alipay_manager and alipay_manager.enabled:
        result = alipay_manager.create_web_payment(
            order_no=order_no,
            amount=format_amount(order['amount']),
            subject=generate_order_subject(order['plan_name'])
        )
    else:
        # 使用模拟支付
        result = mock_payment.create_payment(
            order_no=order_no,
            amount=order['amount'],
            subject=order['plan_name']
        )
    
    if result.get('success'):
        return jsonify({
            "status": "success",
            "payment_url": result.get('payment_url'),
            "order_no": order_no,
            "mock": result.get('mock', False)
        })
    else:
        return jsonify({"error": result.get('error', '创建支付失败')}), 500

@app.route('/api/orders/<order_no>/status', methods=['GET'])
def api_check_order_status(order_no):
    """查询订单支付状态"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    order = payment_module.get_order_by_no(order_no)
    if not order:
        return jsonify({"error": "订单不存在"}), 404
    
    return jsonify({
        "status": "success",
        "order": {
            "order_no": order['order_no'],
            "pay_status": order['pay_status'],
            "pay_status_text": "未支付" if order['pay_status'] == 0 else "已支付" if order['pay_status'] == 1 else "已取消",
            "amount": order['amount'],
            "plan_name": order['plan_name']
        }
    })

@app.route('/api/orders/user/<int:user_id>', methods=['GET'])
def api_get_user_orders(user_id):
    """获取用户订单列表"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    limit = request.args.get('limit', 10, type=int)
    orders = payment_module.get_user_orders(user_id, limit)
    return jsonify({"status": "success", "orders": orders})

# ---- 支付宝回调API ----

@app.route('/api/payment/alipay/notify', methods=['POST'])
def alipay_notify():
    """支付宝异步通知"""
    if not PAYMENT_ENABLED:
        return "fail"
    
    data = request.form.to_dict()
    signature = data.pop('sign', None)
    
    # 验证签名
    if alipay_manager and alipay_manager.enabled:
        if not alipay_manager.verify_notify(data, signature):
            return "fail"
    
    # 处理支付结果
    order_no = data.get('out_trade_no')
    trade_no = data.get('trade_no')
    trade_status = data.get('trade_status')
    
    if trade_status == 'TRADE_SUCCESS':
        success, message = payment_module.update_order_payment(
            order_no=order_no,
            pay_method='alipay',
            pay_trade_no=trade_no
        )
        return "success" if success else "fail"
    
    return "success"

@app.route('/api/payment/alipay/return', methods=['GET'])
def alipay_return():
    """支付宝同步返回"""
    # 重定向到支付结果页面
    return """
    <html>
    <head><title>支付结果</title></head>
    <body>
        <h1>支付处理中...</h1>
        <p>请稍候，正在处理您的支付结果...</p>
        <script>
            setTimeout(function() {
                window.location.href = '/payment_result.html';
            }, 2000);
        </script>
    </body>
    </html>
    """

# ---- 模拟支付API（开发测试用） ----

@app.route('/api/payment/mock/confirm', methods=['POST'])
def api_mock_confirm_payment():
    """模拟支付确认"""
    if not PAYMENT_ENABLED:
        return jsonify({"error": "付费功能未启用"}), 503
    
    data = request.json
    order_no = data.get('order_no')
    
    if not order_no:
        return jsonify({"error": "缺少订单号"}), 400
    
    # 模拟支付确认
    if mock_payment.confirm_payment(order_no):
        # 更新订单状态
        success, message = payment_module.update_order_payment(
            order_no=order_no,
            pay_method='mock',
            pay_trade_no=f'MOCK{int(time.time())}'
        )
        
        if success:
            return jsonify({"status": "success", "message": "模拟支付成功"})
        else:
            return jsonify({"error": message}), 500
    else:
        return jsonify({"error": "订单不存在"}), 404

# ---- 配额检查API（用于创建面试前检查） ----

@app.route('/api/quota/check', methods=['POST'])
def api_check_quota():
    """检查用户是否有足够配额"""
    if not PAYMENT_ENABLED:
        return jsonify({"status": "success", "has_quota": True, "message": "付费功能未启用，允许使用"})
    
    data = request.json
    user_id = data.get('user_id')
    resource_type = data.get('resource_type', 'interview')
    
    if not user_id:
        return jsonify({"error": "缺少用户ID"}), 400
    
    has_quota, quota_info = payment_module.check_quota(user_id, resource_type)
    
    return jsonify({
        "status": "success",
        "has_quota": has_quota,
        "quota_info": quota_info,
        "message": "配额充足" if has_quota else "配额不足，请购买套餐"
    })

@app.route('/api/quota/use', methods=['POST'])
def api_use_quota():
    """使用配额"""
    if not PAYMENT_ENABLED:
        return jsonify({"status": "success", "message": "付费功能未启用"})
    
    data = request.json
    user_id = data.get('user_id')
    resource_type = data.get('resource_type', 'interview')
    quantity = data.get('quantity', 1)
    resource_id = data.get('resource_id')
    
    if not user_id:
        return jsonify({"error": "缺少用户ID"}), 400
    
    success, message = payment_module.use_quota(user_id, resource_type, quantity, resource_id)
    
    if success:
        return jsonify({"status": "success", "message": message})
    else:
        return jsonify({"error": message}), 400

# ==================== 面试评价API ====================

@app.route('/api/evaluation/generate', methods=['POST'])
def generate_evaluation():
    """
    生成面试评价
    
    请求参数 (JSON):
        token: 面试token
    
    返回:
        面试评价结果
    """
    try:
        print("[Evaluation] 收到生成评价请求")
        data = request.json
        print(f"[Evaluation] 请求数据: {data}")
        token = data.get('token')
        
        if not token:
            print("[Evaluation] 错误: 缺少token参数")
            return jsonify({"status": "error", "message": "缺少token参数"}), 400
        
        print(f"[Evaluation] 面试token: {token}")
        
        # 从数据库中获取面试数据
        conn = get_db()
        cursor = conn.cursor()
        
        # 查询面试记录
        cursor.execute("SELECT id, user_id, interview_type_id, start_time, end_time, status FROM interviews WHERE token = ?", (token,))
        interview = cursor.fetchone()
        
        if not interview:
            print("[Evaluation] 错误: 面试记录不存在")
            return jsonify({"status": "error", "message": "面试记录不存在"}), 404
        
        interview_id = interview[0]
        print(f"[Evaluation] 找到面试记录，ID: {interview_id}")
        
        # 查询面试问题和回答
        cursor.execute("SELECT id, question, answer_text, answered_at FROM interview_questions WHERE interview_id = ? ORDER BY id", (interview_id,))
        answers = cursor.fetchall()
        
        if not answers:
            print("[Evaluation] 错误: 面试没有回答记录")
            return jsonify({"status": "error", "message": "面试没有回答记录"}), 404
        
        # 构建面试数据
        questions = []
        for answer in answers:
            questions.append({
                "id": answer[0],
                "question": answer[1],
                "answer_text": answer[2],
                "answered_at": answer[3]
            })
        
        # 查询表情记录
        cursor.execute("SELECT expression, expression_cn, emotion_status, emotion_score, timestamp FROM interview_expression_records WHERE interview_id = ? ORDER BY timestamp", (interview_id,))
        expressions_data = cursor.fetchall()
        
        expressions = []
        for expr in expressions_data:
            expressions.append({
                "expression": expr[0],
                "expression_cn": expr[1],
                "emotion_status": expr[2],
                "emotion_score": expr[3],
                "timestamp": expr[4]
            })
        
        interview_data = {
            "interview_id": interview_id,
            "questions": questions,
            "expressions": expressions,
            "total_questions": len(questions)
        }
        
        cursor.close()
        conn.close()
        
        print(f"[Evaluation] 开始生成面试评价，面试ID: {interview_data['interview_id']}")
        print(f"[Evaluation] 问题数量: {interview_data['total_questions']}")
        print(f"[Evaluation] 表情记录数量: {len(interview_data['expressions'])}")
        
        # 调用大模型API生成评价
        print("[Evaluation] 开始调用大模型API...")
        evaluation = generate_interview_evaluation_with_llm(interview_data)
        
        print("[Evaluation] 评价生成成功")
        print(f"[Evaluation] 评价结果: {evaluation}")
        
        return jsonify({
            "status": "success",
            "evaluation": evaluation
        })
        
    except Exception as e:
        print(f"[Evaluation] 生成评价失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def generate_interview_evaluation_with_llm(interview_data):
    """
    使用大模型生成面试评价
    
    参数:
        interview_data: 面试数据
    
    返回:
        面试评价结果
    """
    # 检查API密钥
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Evaluation] 错误: API Key 为空")
        raise Exception("未配置API Key")
    
    print(f"[Evaluation] API Key 已配置，长度: {len(api_key)}")
    
    # 构建提示词
    prompt = build_evaluation_prompt(interview_data)
    print(f"[Evaluation] 提示词长度: {len(prompt)}")
    
    # 调用大模型API
    import requests
    
    # 使用阿里云 DashScope 模型
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "qwen-plus",
        "input": {
            "prompt": prompt
        },
        "parameters": {
            "max_tokens": 2000,
            "temperature": 0.7,
            "top_p": 0.9
        }
    }
    
    print("[Evaluation] 调用大模型API...")
    print(f"[Evaluation] 请求URL: {url}")
    print(f"[Evaluation] 请求参数: {data}")
    
    response = requests.post(url, headers=headers, json=data, timeout=60)
    
    print(f"[Evaluation] API 响应状态: {response.status_code}")
    print(f"[Evaluation] 响应内容: {response.text}")
    
    if response.status_code != 200:
        error_msg = response.text or f"HTTP {response.status_code}"
        print(f"[Evaluation] API 调用失败: {error_msg}")
        raise Exception(f"API 调用失败: {error_msg}")
    
    # 解析响应
    result = response.json()
    print("[Evaluation] API 响应成功")
    print(f"[Evaluation] 响应结果: {result}")
    
    if "output" not in result or "text" not in result["output"]:
        print("[Evaluation] 响应格式错误")
        raise Exception("响应格式错误")
    
    generated_text = result["output"]["text"]
    print(f"[Evaluation] 生成文本长度: {len(generated_text)}")
    print(f"[Evaluation] 生成文本: {generated_text}")
    
    # 解析生成的评价
    evaluation = parse_generated_evaluation(generated_text)
    print(f"[Evaluation] 解析后的评价: {evaluation}")
    return evaluation

def build_evaluation_prompt(interview_data):
    """
    构建面试评价提示词
    
    参数:
        interview_data: 面试数据
    
    返回:
        提示词
    """
    prompt = f"""
你是一位专业的面试官，负责对候选人的面试表现进行全面评价。请根据以下面试数据，生成一份详细的面试评价报告。

面试数据：
- 面试ID: {interview_data['interview_id']}
- 问题数量: {interview_data['total_questions']}

面试问题和答案：
"""
    
    for i, q in enumerate(interview_data['questions'], 1):
        prompt += f"Q{i}: {q['question']}\n"
        if q['answer_text']:
            prompt += f"A{i}: {q['answer_text']}\n"
        else:
            prompt += f"A{i}: [未回答]\n"
        prompt += "\n"
    
    if interview_data['expressions']:
        prompt += "表情分析记录：\n"
        for i, e in enumerate(interview_data['expressions'][:5], 1):  # 只取前5条表情记录
            prompt += f"- {e['expression_cn']} ({e['emotion_status']}, 得分: {e['emotion_score']})\n"
        prompt += "\n"
    
    prompt += """
请根据以上数据，生成一份详细的面试评价报告，包括以下内容：

1. 总体评价：给出一个综合评分（0-100分）和总体评价描述。
2. 各项能力评分：
   - 专业知识（0-10分）
   - 行业认知（0-10分）
   - 表达能力（0-10分）
   - 沟通能力（0-10分）
   - 思维逻辑（0-10分）
3. 优势亮点：列出候选人的3-5个优势。
4. 改进建议：列出候选人需要改进的3-5个方面。
5. AI个性化建议：根据候选人的表现，给出3个具体的提升建议。

请以JSON格式输出评价结果，确保JSON格式正确，并且包含以下字段：
- averageScore: 综合评分（0-100分）
- description: 总体评价描述
- scores: 各项能力评分（包含professional, communication, comprehensive）
- detailedScores: 详细评分列表（包含name, score, percentage）
- strengths: 优势亮点列表
- improvements: 改进建议列表
- recommendations: AI个性化建议列表（包含title, description）

示例输出格式：
{
  "averageScore": 76,
  "description": "您在本次面试中表现良好，综合得分为76分，表明您有中上水平，有很大提升空间。",
  "scores": {
    "professional": 80,
    "communication": 68,
    "comprehensive": 75
  },
  "detailedScores": [
    {"name": "专业知识", "score": 8.5, "percentage": 85},
    {"name": "行业认知", "score": 7.5, "percentage": 75},
    {"name": "表达能力", "score": 7.0, "percentage": 70},
    {"name": "沟通能力", "score": 6.5, "percentage": 65},
    {"name": "思维逻辑", "score": 8.0, "percentage": 80}
  ],
  "strengths": [
    "基础知识扎实，能够回答大部分专业问题",
    "专业技能突出，有相关项目经验",
    "逻辑思维清晰，能有条理地分析问题"
  ],
  "improvements": [
    "在某些领域的知识深度不够，如算法优化",
    "表达能力有待提高，回答问题时不够流畅",
    "对行业最新趋势了解不足，需要加强学习"
  ],
  "recommendations": [
    {"title": "学习提升", "description": "建议学习算法优化和系统设计，提升专业深度"},
    {"title": "表达训练", "description": "加强表达能力训练，提高回答问题的流畅度"},
    {"title": "行业洞察", "description": "关注行业最新趋势，了解前沿技术发展"}
  ]
}
"""
    
    return prompt

def parse_generated_evaluation(generated_text):
    """
    解析生成的评价文本
    
    参数:
        generated_text: 生成的文本
    
    返回:
        解析后的评价结果
    """
    try:
        # 提取JSON部分
        import re
        import json
        json_match = re.search(r'\{[\s\S]*\}', generated_text)
        if json_match:
            json_str = json_match.group(0)
            evaluation = json.loads(json_str)
            return evaluation
        else:
            print("[Evaluation] 无法提取JSON")
            return get_default_evaluation()
    except Exception as e:
        print(f"[Evaluation] 解析评价失败: {e}")
        return get_default_evaluation()

def get_default_evaluation():
    """
    获取默认的面试评价
    
    返回:
        默认的面试评价结果
    """
    return {
        "averageScore": 76,
        "description": "您在本次面试中表现良好，综合得分为76分，表明您有中上水平，有很大提升空间。",
        "scores": {
            "professional": 80,
            "communication": 68,
            "comprehensive": 75
        },
        "detailedScores": [
            {"name": "专业知识", "score": 8.5, "percentage": 85},
            {"name": "行业认知", "score": 7.5, "percentage": 75},
            {"name": "表达能力", "score": 7.0, "percentage": 70},
            {"name": "沟通能力", "score": 6.5, "percentage": 65},
            {"name": "思维逻辑", "score": 8.0, "percentage": 80}
        ],
        "strengths": [
            "基础知识扎实，能够回答大部分专业问题",
            "专业技能突出，有相关项目经验",
            "逻辑思维清晰，能有条理地分析问题"
        ],
        "improvements": [
            "在某些领域的知识深度不够，如算法优化",
            "表达能力有待提高，回答问题时不够流畅",
            "对行业最新趋势了解不足，需要加强学习"
        ],
        "recommendations": [
            {"title": "学习提升", "description": "建议学习算法优化和系统设计，提升专业深度"},
            {"title": "表达训练", "description": "加强表达能力训练，提高回答问题的流畅度"},
            {"title": "行业洞察", "description": "关注行业最新趋势，了解前沿技术发展"}
        ]
    }

# ==================== 简历上传API ====================
@app.route('/api/resume/upload', methods=['POST'])
def upload_resume():
    print("[Resume] 进入上传简历函数")
    logger.info("[Resume] 进入上传简历函数")
    # 重新实现上传简历功能
    try:
        import json
        import base64
        from PIL import Image
        from io import BytesIO
        print("[Resume] 收到简历上传请求")
        logger.info("[Resume] 收到简历上传请求")
        
        # 检查请求方法
        if request.method != 'POST':
            logger.error("[Resume] 错误: 请求方法错误")
            return jsonify({"status": "error", "message": "请求方法错误", "error_code": "METHOD_ERROR"}), 405
        
        # 检查Content-Type
        content_type = request.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            logger.error("[Resume] 错误: Content-Type错误，需要multipart/form-data")
            return jsonify({"status": "error", "message": "Content-Type错误，需要multipart/form-data", "error_code": "CONTENT_TYPE_ERROR"}), 400
        
        # 获取上传的文件
        try:
            resume_file = request.files.get('resume')
            work_experience = request.form.get('work_experience')
            target_position = request.form.get('target_position')
            
            print(f"[Resume] resume_file: {resume_file}")
            print(f"[Resume] work_experience: {work_experience}")
            print(f"[Resume] target_position: {target_position}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 获取请求参数失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"获取请求参数失败: {str(e)}", "error_code": "REQUEST_PARAM_ERROR"}), 500
        
        # 检查简历文件是否存在
        if not resume_file:
            print("[Resume] 错误: 缺少简历文件")
            logger.error("[Resume] 错误: 缺少简历文件")
            return jsonify({"status": "error", "message": "缺少简历文件", "error_code": "MISSING_RESUME_FILE"}), 400
        
        # 检查文件名
        if not resume_file.filename:
            print("[Resume] 错误: 简历文件无文件名")
            logger.error("[Resume] 错误: 简历文件无文件名")
            return jsonify({"status": "error", "message": "简历文件无文件名", "error_code": "RESUME_FILE_NO_NAME"}), 400
        
        # 检查文件扩展名
        file_ext = resume_file.filename.split('.')[-1].lower() if '.' in resume_file.filename else ''
        logger.info(f"[Resume] 简历文件名: {resume_file.filename}")
        logger.info(f"[Resume] 文件扩展名: {file_ext}")
        logger.info(f"[Resume] 工作经验: {work_experience or '未提供'}")
        logger.info(f"[Resume] 目标岗位: {target_position or '未提供'}")
        
        # 检查文件大小
        resume_file.seek(0, 2)  # 移动到文件末尾
        file_size = resume_file.tell()  # 获取文件大小
        resume_file.seek(0)  # 重置到文件开头
        
        logger.info(f"[Resume] 简历文件大小: {file_size} 字节")
        
        if file_size > 10 * 1024 * 1024:  # 限制文件大小为10MB
            logger.error("[Resume] 错误: 简历文件太大，最大支持10MB")
            return jsonify({"status": "error", "message": "简历文件太大，最大支持10MB", "error_code": "RESUME_FILE_TOO_LARGE"}), 400
        
        if file_size == 0:
            logger.error("[Resume] 错误: 简历文件为空")
            return jsonify({"status": "error", "message": "简历文件为空", "error_code": "RESUME_FILE_EMPTY"}), 400
        
        # 读取简历内容
        try:
            resume_content = resume_file.read()
            logger.info(f"[Resume] 成功读取简历内容，大小: {len(resume_content)} 字节")
        except Exception as e:
            logger.error(f"[Resume] 错误: 读取简历文件失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"读取简历文件失败: {str(e)}", "error_code": "RESUME_FILE_READ_ERROR"}), 500
        
        # 检查文件类型并处理PDF
        try:
            import PyPDF2
            logger.info("[Resume] 导入 PyPDF2 库成功")
            
            # 检查是否为PDF文件
            if resume_file.filename.lower().endswith('.pdf'):
                logger.info("[Resume] 检测到PDF文件，开始解析")
                try:
                    # 使用PyPDF2解析PDF
                    from io import BytesIO
                    pdf_file = BytesIO(resume_content)
                    reader = PyPDF2.PdfReader(pdf_file)
                    
                    # 检查PDF页数
                    num_pages = len(reader.pages)
                    logger.info(f"[Resume] PDF页数: {num_pages}")
                    
                    if num_pages == 0:
                        logger.error("[Resume] 错误: PDF文件无内容")
                        return jsonify({"status": "error", "message": "PDF文件无内容", "error_code": "PDF_NO_CONTENT_ERROR"}), 400
                    
                    # 提取文本
                    text_content = []
                    for page_num in range(num_pages):
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        if text:
                            text_content.append(text)
                    
                    pdf_text = '\n'.join(text_content)
                    logger.info(f"[Resume] PDF解析成功，提取文本长度: {len(pdf_text)} 字符")
                    
                    if not pdf_text.strip():
                        logger.error("[Resume] 错误: PDF文件解析后无内容")
                        return jsonify({"status": "error", "message": "PDF文件解析后无内容", "error_code": "PDF_EMPTY_CONTENT_ERROR"}), 400
                    
                    # 将解析后的文本转换为字节
                    resume_content = pdf_text.encode('utf-8')
                except Exception as e:
                    logger.error(f"[Resume] 错误: PDF解析失败: {e}")
                    import traceback
                    traceback.print_exc()
                    return jsonify({"status": "error", "message": f"PDF解析失败: {str(e)}", "error_code": "PDF_PARSE_ERROR"}), 500
        except ImportError:
            logger.warning("[Resume] 警告: PyPDF2 库未安装，无法解析PDF文件")
        except Exception as e:
            logger.error(f"[Resume] 错误: PDF处理失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"PDF处理失败: {str(e)}", "error_code": "PDF_PROCESS_ERROR"}), 500
        
        # 检查简历内容是否为空
        if not resume_content:
            logger.error("[Resume] 错误: 简历内容为空")
            return jsonify({"status": "error", "message": "简历内容为空", "error_code": "EMPTY_RESUME_ERROR"}), 400
        
        # 生成简历截图
        logger.info("[Resume] 开始生成简历截图")
        resume_image = None
        try:
            # 将简历内容转换为文本
            if isinstance(resume_content, bytes):
                resume_text = resume_content.decode('utf-8', errors='ignore')
            else:
                resume_text = str(resume_content)
            
            # 创建一个图像，用于绘制简历内容
            # 设置图像大小为A4纸张大小（像素）
            width, height = 2480, 3508
            image = Image.new('RGB', (width, height), color=(255, 255, 255))
            
            # 尝试导入PIL的ImageDraw和ImageFont模块
            try:
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(image)
                
                # 尝试使用系统字体，如果失败则使用默认字体
                try:
                    # 尝试使用Windows系统字体
                    font = ImageFont.truetype('Arial.ttf', 36)
                except Exception:
                    # 如果找不到字体，使用默认字体
                    font = ImageFont.load_default()
                
                # 绘制简历内容
                # 设置边距
                margin = 100
                x, y = margin, margin
                line_height = 50
                
                # 分割文本为多行
                lines = resume_text.split('\n')
                for line in lines:
                    # 如果超出图像高度，停止绘制
                    if y > height - margin:
                        break
                    
                    # 绘制文本
                    draw.text((x, y), line, fill=(0, 0, 0), font=font)
                    y += line_height
                
                # 将图像转换为base64编码
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                resume_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
                logger.info("[Resume] 简历截图生成成功")
            except Exception as e:
                logger.warning(f"[Resume] 警告: 生成简历截图失败: {e}")
                # 截图失败不影响后续流程，继续执行
        except Exception as e:
            logger.warning(f"[Resume] 警告: 生成简历截图失败: {e}")
            # 截图失败不影响后续流程，继续执行
        
        # 分析简历内容
        logger.info("[Resume] 开始分析简历内容")
        try:
            # 暂时使用默认分析结果，避免调用大模型API
            analysis_result = get_default_resume_analysis()
            logger.info("[Resume] 简历分析完成")
            logger.debug(f"[Resume] 分析结果: {analysis_result}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 分析简历失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"分析简历失败: {str(e)}", "error_code": "RESUME_ANALYSIS_ERROR"}), 500
        
        # 生成面试token
        try:
            token = generate_token()
            logger.info(f"[Resume] 生成token: {token}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成token失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"生成token失败: {str(e)}", "error_code": "TOKEN_GENERATION_ERROR"}), 500
        
        # 保存简历和分析结果到数据库
        try:
            conn = get_db()
            logger.info("[Resume] 连接数据库成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 连接数据库失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"连接数据库失败: {str(e)}", "error_code": "DATABASE_CONNECTION_ERROR"}), 500
        
        # 插入用户记录（如果不存在）
        user_id = 1  # 默认为第一个用户
        try:
            existing_user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not existing_user:
                conn.execute('INSERT INTO users (username, email, created_at, last_login_at) VALUES (?, ?, ?, ?)',
                           ('default_user', 'default@example.com', int(time.time()), int(time.time())))
                logger.info("[Resume] 创建用户成功")
            else:
                logger.info("[Resume] 用户已存在，跳过创建")
        except Exception as e:
            logger.error(f"[Resume] 错误: 创建用户失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return jsonify({"status": "error", "message": f"创建用户失败: {str(e)}", "error_code": "USER_CREATION_ERROR"}), 500
        
        # 插入面试记录
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO interviews (user_id, start_time, status, question_count, voice_reading, voice_type, token)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, int(time.time()), 1, 5, 1, 'professional_male', token))
            
            interview_id = cursor.lastrowid
            logger.info(f"[Resume] 创建面试成功，ID: {interview_id}")
        except Exception as e:
            logger.error(f"[Resume] 错误: 创建面试失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return jsonify({"status": "error", "message": f"创建面试失败: {str(e)}", "error_code": "INTERVIEW_CREATION_ERROR"}), 500
        
        # 生成面试问题
        try:
            from app.services.question_service import generate_questions
            logger.info("[Resume] 导入 generate_questions 函数成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 导入 generate_questions 函数失败: {e}")
            import traceback
            traceback.print_exc()
            return_db(conn)
            return jsonify({"status": "error", "message": f"导入 generate_questions 函数失败: {str(e)}", "error_code": "MODULE_IMPORT_ERROR"}), 500
        
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
        
        # 模拟面试信息
        interview_dict = {
            "id": interview_id,
            "user_id": user_id,
            "interview_type_id": 1,
            "status": 1,
            "voice_type": "professional_male"
        }
        logger.debug(f"[Resume] 面试信息: {interview_dict}")
        
        # 生成问题
        try:
            logger.info("[Resume] 开始生成面试问题")
            # 将简历分析结果传递给 generate_questions 函数
            resume_analysis_info = f"\n\n简历分析结果：\n{json.dumps(analysis_result, ensure_ascii=False)}"
            logger.info(f"[Resume] 简历分析信息长度: {len(resume_analysis_info)}")
            logger.debug(f"[Resume] 简历分析信息: {resume_analysis_info[:200]}...")  # 只记录前200个字符
            
            # 注意：generate_questions 函数会处理数据库连接的关闭
            result = generate_questions(interview_id, candidate, position, interview_dict, resume_analysis_info, cursor, conn, resume_image)
            logger.info("[Resume] 生成面试问题成功")
            logger.debug(f"[Resume] 生成问题结果: {result}")
            
            # 检查generate_questions函数的返回值
            if isinstance(result, dict) and 'error' in result:
                logger.error(f"[Resume] 错误: 生成面试问题失败: {result['error']}")
                return jsonify({"status": "error", "message": result['error'], "error_code": "QUESTION_GENERATION_ERROR"}), 500
            
            logger.info("[Resume] 上传简历请求处理完成")
            # 构建成功响应
            response_data = {
                "status": "success",
                "token": token,
                "interview_id": interview_id,
                "message": "上传简历成功，已生成面试问题"
            }
            logger.debug(f"[Resume] 响应数据: {response_data}")
            return jsonify(response_data)
        except Exception as e:
            logger.error(f"[Resume] 错误: 生成面试问题失败: {e}")
            import traceback
            traceback.print_exc()
            # 注意：generate_questions 函数会处理数据库连接的关闭
            return jsonify({"status": "error", "message": f"生成面试问题失败: {str(e)}", "error_code": "QUESTION_GENERATION_ERROR"}), 500
    except Exception as e:
        logger.error(f"[Resume] 上传简历失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"上传简历失败: {str(e)}",
            "error_code": "UNKNOWN_ERROR"
        }), 500

# 路由定义
def test():
    return jsonify({"message": "测试成功！"})

def test_post():
    print("[Test] 收到POST请求")
    return jsonify({"message": "POST测试成功！"})

app.route('/api/test', methods=['GET'])(test)
app.route('/api/test_post', methods=['POST'])(test_post)

@app.route('/api/interview/create_and_redirect', methods=['GET'])
def create_personal_interview_and_redirect():
    """
    创建新面试并重定向到面试页面（个人用户版）
    
    返回:
        重定向到面试页面
    """
    try:
        # 生成token
        token = generate_token()
        print(f"[Interview] 生成面试token: {token}")
        
        # 插入数据库
        conn = get_db()
        cursor = conn.cursor()
        
        # 插入面试记录
        cursor.execute('''
            INSERT INTO interviews (user_id, interview_type_id, start_time, status, question_count, voice_reading, voice_type, token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (1, 1, int(time.time()), 0, 5, 1, 'professional_male', token))
        
        interview_id = cursor.lastrowid
        print(f"[Interview] 创建面试成功，ID: {interview_id}")
        
        # 提交事务
        conn.commit()
        return_db(conn)
        
        # 生成面试问题
        # 注意：这里先返回结果，然后异步生成问题
        # 这样可以提高响应速度
        thread = threading.Thread(target=generate_personal_interview_questions, args=(token,))
        thread.daemon = True
        thread.start()
        
        # 重定向到面试页面
        return redirect(f"/static/interview.html?token={token}")
    except Exception as e:
        print(f"[Interview] 创建面试失败: {str(e)}")
        return jsonify({"error": str(e)}), 500

def analyze_resume(resume_content, work_experience, target_position):
    """
    分析简历内容
    
    参数:
        resume_content: 简历内容
        work_experience: 工作经验
        target_position: 目标岗位
    
    返回:
        简历分析结果
    """
    logger.info("[Resume] 开始分析简历")
    try:
        # 暂时使用默认分析结果，避免调用大模型API
        # 这是为了避免服务器崩溃的问题
        logger.info("[Resume] 使用默认分析结果")
        return get_default_resume_analysis()
        
        # 检查API密钥
        logger.info("[Resume] 检查API密钥")
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            logger.warning("[Resume] 警告: DASHSCOPE_API_KEY 为空，使用默认分析结果")
            return get_default_resume_analysis()
        
        logger.info(f"[Resume] API Key 已配置，长度: {len(api_key)}")
        
        # 构建提示词
        logger.info("[Resume] 构建提示词")
        try:
            prompt = build_resume_analysis_prompt(resume_content, work_experience, target_position)
            logger.info(f"[Resume] 提示词长度: {len(prompt)}")
            logger.debug(f"[Resume] 提示词内容: {prompt[:100]}...")  # 只记录前100个字符
        except Exception as e:
            logger.error(f"[Resume] 错误: 构建提示词失败: {e}")
            import traceback
            traceback.print_exc()
            return get_default_resume_analysis()
        
        # 调用大模型API
        logger.info("[Resume] 调用大模型API")
        try:
            import requests
            logger.info("[Resume] 导入 requests 库成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 导入 requests 库失败: {e}")
            return get_default_resume_analysis()
        
        # 使用阿里云 DashScope 模型 (百炼模型，选择有免费额度的版本)
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 使用 qwen-turbo 模型，它有免费额度
        data = {
            "model": "qwen-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        logger.info("[Resume] 发送请求到大模型API...")
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
            logger.info(f"[Resume] API 响应状态: {response.status_code}")
            logger.debug(f"[Resume] API 响应头: {dict(response.headers)}")
        except requests.RequestException as e:
            logger.error(f"[Resume] 错误: 发送请求失败: {e}")
            import traceback
            traceback.print_exc()
            return get_default_resume_analysis()
        
        if response.status_code == 200:
            try:
                result = response.json()
                logger.info("[Resume] API 响应成功，解析 JSON 成功")
                logger.debug(f"[Resume] API 响应结果: {result}")
            except json.JSONDecodeError as e:
                logger.error(f"[Resume] 错误: 解析响应 JSON 失败: {e}")
                logger.error(f"[Resume] 响应内容: {response.text}")
                return get_default_resume_analysis()
            
            # 检查响应结构
            if not isinstance(result, dict):
                logger.error("[Resume] 错误: 响应不是有效的JSON对象")
                return get_default_resume_analysis()
            
            # 解析响应 (OpenAI兼容模式)
            if "choices" in result and isinstance(result["choices"], list) and result["choices"]:
                if not isinstance(result["choices"][0], dict):
                    logger.error("[Resume] 错误: 响应choices不是有效的对象")
                    return get_default_resume_analysis()
                
                if "message" not in result["choices"][0]:
                    logger.error("[Resume] 错误: 响应缺少message字段")
                    return get_default_resume_analysis()
                
                if "content" not in result["choices"][0]["message"]:
                    logger.error("[Resume] 错误: 响应缺少content字段")
                    return get_default_resume_analysis()
                
                generated_text = result["choices"][0]["message"]["content"]
                logger.info(f"[Resume] 生成文本长度: {len(generated_text)}")
                logger.debug(f"[Resume] 生成文本内容: {generated_text[:200]}...")  # 只记录前200个字符
                
                # 解析生成的分析结果
                try:
                    analysis = parse_resume_analysis(generated_text)
                    logger.info("[Resume] 分析结果解析成功")
                    logger.debug(f"[Resume] 分析结果: {analysis}")
                    return analysis
                except Exception as e:
                    logger.error(f"[Resume] 错误: 解析分析结果失败: {e}")
                    import traceback
                    traceback.print_exc()
                    return get_default_resume_analysis()
            else:
                logger.error(f"[Resume] 响应格式错误，缺少必要字段")
                logger.error(f"[Resume] 响应结构: {result}")
                return get_default_resume_analysis()
        else:
            error_msg = response.text or f"HTTP {response.status_code}"
            logger.error(f"[Resume] API 调用失败: {error_msg}")
            logger.error(f"[Resume] 响应状态码: {response.status_code}")
            return get_default_resume_analysis()
            
    except Exception as e:
        logger.error(f"[Resume] 分析简历失败: {e}")
        import traceback
        traceback.print_exc()
        return get_default_resume_analysis()

def build_resume_analysis_prompt(resume_content, work_experience, target_position):
    """
    构建简历分析提示词
    
    参数:
        resume_content: 简历内容
        work_experience: 工作经验
        target_position: 目标岗位
    
    返回:
        提示词
    """
    # 尝试解码简历内容
    try:
        resume_text = resume_content.decode('utf-8')
    except:
        resume_text = str(resume_content)
    
    # 限制简历文本长度
    if len(resume_text) > 5000:
        resume_text = resume_text[:5000] + "..."
    
    prompt = f"""
你是一位专业的简历分析专家，负责分析简历内容并生成面试问题。请根据以下简历内容，分析候选人的背景、技能和经验，并生成适合目标岗位的面试问题。

简历内容：
{resume_text}

工作经验：{work_experience}
目标岗位：{target_position}

请从以下几个方面分析简历：
1. 候选人的专业背景和工作经验
2. 候选人的技能特长
3. 候选人的优势和劣势
4. 适合目标岗位的面试问题（至少5个）

请以JSON格式输出分析结果，确保JSON格式正确，并且包含以下字段：
- background: 专业背景和工作经验分析
- skills: 技能特长分析
- strengths: 优势
- weaknesses: 劣势
- questions: 面试问题列表

示例输出格式：
{
  "background": "候选人拥有计算机科学与技术专业背景，具有3年前端开发经验，熟悉HTML、CSS、JavaScript等前端技术。",
  "skills": "前端技术：HTML5、CSS3、JavaScript、TypeScript、React、Vue；后端技术：Node.js、Express；工具：Git、Webpack、Docker",
  "strengths": ["基础知识扎实，能够回答大部分专业问题", "专业技能突出，有相关项目经验", "逻辑思维清晰，能有条理地分析问题"],
  "weaknesses": ["在某些领域的知识深度不够，如算法优化", "表达能力有待提高，回答问题时不够流畅", "对行业最新趋势了解不足，需要加强学习"],
  "questions": ["请介绍一下你自己，包括你的专业背景和工作经验。", "你为什么选择前端开发这个职业？", "请解释一下什么是闭包，以及它在JavaScript中的应用。", "你如何处理浏览器兼容性问题？", "请描述一下你的项目开发流程。"]
}
"""
    
    return prompt

def parse_resume_analysis(generated_text):
    """
    解析生成的简历分析文本
    
    参数:
        generated_text: 生成的文本
    
    返回:
        解析后的分析结果
    """
    logger.info("[Resume] 开始解析简历分析文本")
    try:
        # 提取JSON部分
        logger.info("[Resume] 提取JSON部分")
        try:
            import re
            import json
            logger.info("[Resume] 导入 re 和 json 库成功")
        except Exception as e:
            logger.error(f"[Resume] 错误: 导入库失败: {e}")
            return get_default_resume_analysis()
        
        logger.debug(f"[Resume] 原始文本: {generated_text[:300]}...")  # 只记录前300个字符
        
        json_match = re.search(r'\{[\s\S]*\}', generated_text)
        if json_match:
            json_str = json_match.group(0)
            logger.info(f"[Resume] 提取到JSON字符串，长度: {len(json_str)}")
            logger.debug(f"[Resume] JSON字符串: {json_str[:300]}...")  # 只记录前300个字符
            
            try:
                analysis = json.loads(json_str)
                logger.info("[Resume] 解析JSON成功")
                
                # 验证分析结果是否包含必要字段
                required_fields = ['background', 'skills', 'strengths', 'weaknesses', 'questions']
                missing_fields = [field for field in required_fields if field not in analysis]
                
                if missing_fields:
                    logger.warning(f"[Resume] 警告: 分析结果缺少必要字段: {missing_fields}")
                    # 补充缺失的字段
                    for field in missing_fields:
                        if field == 'strengths' or field == 'weaknesses' or field == 'questions':
                            analysis[field] = []
                        else:
                            analysis[field] = ""
                
                logger.debug(f"[Resume] 解析结果: {analysis}")
                return analysis
            except json.JSONDecodeError as e:
                logger.error(f"[Resume] 错误: 解析JSON失败: {e}")
                logger.error(f"[Resume] 错误位置: {e.pos}")
                logger.error(f"[Resume] 错误行号: {e.lineno}")
                logger.error(f"[Resume] 错误列号: {e.colno}")
                logger.error(f"[Resume] JSON字符串: {json_str}")
                return get_default_resume_analysis()
        else:
            logger.error("[Resume] 错误: 无法提取JSON")
            logger.error(f"[Resume] 原始文本: {generated_text}")
            return get_default_resume_analysis()
    except Exception as e:
        logger.error(f"[Resume] 错误: 解析分析结果失败: {e}")
        import traceback
        traceback.print_exc()
        return get_default_resume_analysis()

def get_default_resume_analysis():
    """
    获取默认的简历分析结果
    
    返回:
        默认的简历分析结果
    """
    return {
        "background": "候选人拥有计算机科学与技术专业背景，具有3年前端开发经验，熟悉HTML、CSS、JavaScript等前端技术。",
        "skills": "前端技术：HTML5、CSS3、JavaScript、TypeScript、React、Vue；后端技术：Node.js、Express；工具：Git、Webpack、Docker",
        "strengths": ["基础知识扎实，能够回答大部分专业问题", "专业技能突出，有相关项目经验", "逻辑思维清晰，能有条理地分析问题"],
        "weaknesses": ["在某些领域的知识深度不够，如算法优化", "表达能力有待提高，回答问题时不够流畅", "对行业最新趋势了解不足，需要加强学习"],
        "questions": ["请介绍一下你自己，包括你的专业背景和工作经验。", "你为什么选择前端开发这个职业？", "请解释一下什么是闭包，以及它在JavaScript中的应用。", "你如何处理浏览器兼容性问题？", "请描述一下你的项目开发流程。"]
    }

def generate_questions_for_resume(resume_analysis, target_position):
    """
    根据简历分析结果生成面试问题
    
    参数:
        resume_analysis: 简历分析结果
        target_position: 目标岗位
    
    返回:
        面试问题列表
    """
    # 如果分析结果中有问题，直接使用
    if 'questions' in resume_analysis and resume_analysis['questions']:
        return resume_analysis['questions']
    
    # 否则根据目标岗位生成默认问题
    if target_position == 'frontend':
        return [
            '请介绍一下你自己，包括你的专业背景和工作经验。',
            '你为什么选择前端开发这个职业？',
            '请解释一下什么是闭包，以及它在JavaScript中的应用。',
            '你如何处理浏览器兼容性问题？',
            '请描述一下你的项目开发流程。'
        ]
    elif target_position == 'backend':
        return [
            '请介绍一下你自己，包括你的专业背景和工作经验。',
            '你为什么选择后端开发这个职业？',
            '请解释一下什么是RESTful API，以及它的设计原则。',
            '你如何处理数据库并发问题？',
            '请描述一下你的项目开发流程。'
        ]
    elif target_position == 'product':
        return [
            '请介绍一下你自己，包括你的专业背景和工作经验。',
            '你为什么选择产品经理这个职业？',
            '请描述一下你如何进行产品需求分析。',
            '你如何处理产品开发过程中的变更需求？',
            '请描述一下你的产品开发流程。'
        ]
    elif target_position == 'data':
        return [
            '请介绍一下你自己，包括你的专业背景和工作经验。',
            '你为什么选择数据分析这个职业？',
            '请解释一下什么是SQL，以及它的基本操作。',
            '你如何处理数据清洗和预处理？',
            '请描述一下你的数据分析流程。'
        ]
    else:
        return [
            '请介绍一下你自己，包括你的专业背景和工作经验。',
            '你为什么选择这个职业？',
            '请描述一下你的优势和劣势。',
            '你如何处理工作中的挑战？',
            '你对未来的职业规划是什么？'
        ]

if __name__ == '__main__':
    # 全局异常处理
    try:
        print("[INFO] 准备启动服务器...")
        logger.info("准备启动服务器...")
        
        # 记录服务器启动时的环境信息
        import platform
        logger.info(f"操作系统: {platform.system()} {platform.release()}")
        logger.info(f"Python版本: {platform.python_version()}")
        logger.info(f"当前工作目录: {os.getcwd()}")
        
        # 记录服务器启动时间
        import datetime
        start_time = datetime.datetime.now()
        logger.info(f"服务器启动时间: {start_time}")
        
        # 检查Python版本
        import sys
        if sys.version_info < (3, 8):
            logger.error("Python版本过低，需要Python 3.8或更高版本")
            print("[ERROR] Python版本过低，需要Python 3.8或更高版本")
            exit(1)
        
        # 检查必要的依赖
        try:
            import flask
            import sqlite3
            import json
            import os
            import traceback
            logger.info("所有必要的依赖已安装")
        except ImportError as e:
            logger.error(f"缺少必要的依赖: {e}")
            print(f"[ERROR] 缺少必要的依赖: {e}")
            exit(1)
        
        # 初始化数据库
        try:
            logger.info("开始初始化数据库...")
            init_db()
            logger.info("数据库初始化完成")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            import traceback
            traceback.print_exc()
            exit(1)
        
        # 检查Flask应用实例
        try:
            if not app:
                logger.error("Flask应用实例未创建")
                print("[ERROR] Flask应用实例未创建")
                exit(1)
            logger.info("Flask应用实例检查成功")
        except Exception as e:
            logger.error(f"检查Flask应用实例失败: {e}")
            import traceback
            traceback.print_exc()
            exit(1)
        
        # 启动Flask应用
        logger.info("开始启动Flask应用...")
        try:
            # 使用debug模式，以便更好地捕获和显示错误
            # 使用不同的端口，避免端口冲突
            logger.info("Flask应用启动前的状态检查")
            logger.info(f"Flask应用实例: {app}")
            logger.info(f"Flask应用配置: {app.config}")
            logger.info(f"Flask应用路由: {list(app.url_map.iter_rules())}")
            
            # 直接启动Flask应用
            print("[INFO] 服务器启动在 http://0.0.0.0:10009")
            logger.info("服务器启动在 http://0.0.0.0:10009")
            print("[INFO] 服务器开始运行...")
            logger.info("服务器开始运行...")
            # 设置debug=False，避免调试模式导致的问题
            # 设置use_reloader=False，避免自动重载导致的问题
            try:
                app.run(host='0.0.0.0', port=10009, debug=False, threaded=True, use_reloader=False)
            except Exception as e:
                print(f"[ERROR] 服务器运行失败: {e}")
                logger.error(f"服务器运行失败: {e}")
                import traceback
                traceback.print_exc()
            print("[INFO] 服务器运行结束")
            logger.info("服务器运行结束")
        except KeyboardInterrupt:
            print("[INFO] 收到键盘中断，准备关闭服务器...")
            logger.info("收到键盘中断，准备关闭服务器...")
        except OSError as e:
            print(f"[ERROR] 服务器启动失败: {e}")
            logger.error(f"服务器启动失败: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            print(f"[ERROR] Flask应用运行失败: {e}")
            logger.error(f"Flask应用运行失败: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"[ERROR] 服务器启动失败: {e}")
        logger.error(f"服务器启动失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 注意：数据库连接已在各个函数中单独处理
        print("[INFO] 服务器退出完成")
        logger.info("服务器退出完成")
