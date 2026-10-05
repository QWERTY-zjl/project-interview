"""
配置模块
==========
负责加载和管理应用配置
"""

import os
from dotenv import load_dotenv

# 加载 .env 环境变量文件
load_dotenv()

# 阿里云 DashScope API 密钥（同时支持 OPENAI_API_KEY 环境变量）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")

# OpenAI API 密钥（备用）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI API 地址（默认使用国内代理）
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")

# DashScope OpenAI 兼容接口地址（出题走这里）
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# 出题用的文本模型（qwen-flash 为 DashScope 上最便宜的文本模型）
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-flash")

# ==================== AI 服务配置（全部可在 .env 里覆盖，无需改代码）====================
# 使用者想换模型/换服务商时，只需要在 .env 里写同名变量，例如：
#   LLM_MODEL=qwen-turbo          # 换文本模型
#   TTS_MODEL=cosyvoice-v2        # 换语音合成模型
# 各项用途见下面每条注释；所有值都有默认值，不配也能跑（但 AI 功能需要 DASHSCOPE_API_KEY）

# DashScope 原生 API 端点（语音识别/语音合成/表情识别等「非 OpenAI 兼容」接口走这里；
# 出题和报告走上面的 DASHSCOPE_BASE_URL 兼容端点，两者不同，别混用）
DASHSCOPE_NATIVE_URL = os.getenv("DASHSCOPE_NATIVE_URL", "https://dashscope.aliyuncs.com")

# 语音识别模型（ASR：把面试录音转成文字）
ASR_MODEL = os.getenv("ASR_MODEL", "paraformer-v2")

# 语音合成模型（TTS：把面试题朗读出来）
TTS_MODEL = os.getenv("TTS_MODEL", "qwen-tts")

# 表情识别模型（面试中摄像头抓拍，分析候选人情绪）
EXPRESSION_MODEL = os.getenv("EXPRESSION_MODEL", "face-expression-detection")

# 默认朗读音色（当前端传来的音色类型不在映射表里时兜底用）
# qwen-tts 用英文别名音色（Cherry=女 / Ethan=男），不认 zh-CN-* 风格音色
DEFAULT_TTS_VOICE = os.getenv("DEFAULT_TTS_VOICE", "Cherry")

# SQLite 数据库文件路径（变量名叫 NAME，实际存的是完整路径）
# 【为什么要锚定】"interview_system.db" 这种裸文件名是相对路径，跟「进程启动目录」走：
#   从仓库根启动 → 连 <仓库根>/interview_system.db，从别处启动 → 又是另一个文件。
#   实际后果：服务器连到一个凭空生成的空库，所有查询报 no such table。
# 【从里到外拆开读】
#   __file__                  → 本文件 config.py 自己的路径（.../app/config/config.py）
#   os.path.dirname(__file__) → 上一级目录（.../app/config）
#   再套一层 dirname          → 再上一级（.../app）
#   os.path.join(..., 'db', 'interview_system.db') → 拼出 .../app/db/interview_system.db
# 和建表脚本的锚定方式一致：不管从哪个目录启动，连的都是同一个库文件
DATABASE_NAME = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'interview_system.db')

# 日志级别（默认 DEBUG）
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# 临时文件目录
TEMP_DIR = os.getenv("TEMP_DIR", os.path.join(os.path.dirname(__file__), "..", "temp"))

# 确保临时目录存在
os.makedirs(TEMP_DIR, exist_ok=True)
