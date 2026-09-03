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

# SQLite 数据库文件名
DATABASE_NAME = "interview_system.db"

# 日志级别（默认 DEBUG）
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# 临时文件目录
TEMP_DIR = os.getenv("TEMP_DIR", os.path.join(os.path.dirname(__file__), "..", "temp"))

# 确保临时目录存在
os.makedirs(TEMP_DIR, exist_ok=True)
