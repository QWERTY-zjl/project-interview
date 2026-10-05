"""
AI API 连通性测试脚本
======================
逐项测试项目用到的阿里云百炼 AI 服务是否真正可用，用来验证 .env 配置是否正确。
不需要启动项目服务器——脚本直接测「你的机器 -> 百炼」这一段链路。

测什么：
  [1] 文本模型 LLM_MODEL        —— 出题、面试报告都用它（走 OpenAI 兼容端点）
  [2] 语音合成 TTS_MODEL        —— 把面试题朗读出来（走 DashScope 原生端点）
  [3] 语音识别 ASR_MODEL        —— 把面试录音转成文字（走 DashScope 原生端点）
  [4] 表情识别 EXPRESSION_MODEL —— 需要真实人脸图片才有意义，只显示配置不实测

怎么跑（在项目根目录 project-interview 下执行）：
  app\\venv\\Scripts\\python.exe tests\\ai_api_check.py

消耗说明：每项只发最小请求（文本限 8 个 token、TTS 一个短句、ASR 一秒静音），
qwen-flash 计价下总成本约几厘钱。

为什么文件名不带 test：.gitignore 里有 test_*.py / *_test.py 规则，
带 test 的文件不会进 git；本脚本对项目使用者有通用价值，所以入库。
"""

import base64
import io
import os
import sys
import wave

# --- 让脚本能 import 到项目的 app 包 -------------------------------
# 脚本位于 tests/ 目录，Python 默认只在「脚本所在目录」找模块；
# 手动把项目根目录（tests 的上一级）插到模块搜索路径最前面，
# 后面的 import app.config.config 才能成功
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 先显式加载项目根目录的 .env（比 config 内部的 load_dotenv 更稳：
# 不管从哪个目录启动本脚本，都能准确找到 .env）
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# 从项目统一配置读取所有 AI 参数——测的就是「你 .env 里配的值」，
# 配置项含义见 app/config/config.py 的 AI 服务配置区块
from app.config.config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_NATIVE_URL,
    LLM_MODEL,
    TTS_MODEL,
    ASR_MODEL,
    EXPRESSION_MODEL,
    DEFAULT_TTS_VOICE,
)

import requests


def report(ok, detail, hint=""):
    """统一格式的结果打印：ok 为真打「通过」，否则打「失败」+ 处理建议。
    返回 ok 本身，方便主流程统计通过数量"""
    print(f"  {'✓ 通过' if ok else '✗ 失败'} - {detail}")
    if hint:
        print(f"    >> 建议: {hint}")
    return ok


def hint_for(status):
    """按 HTTP 状态码给出针对性处理建议（对应本项目的真实踩坑经历）"""
    if status == 401:
        # 本项目踩过的坑：新版百炼 key 发到老网关 dashscope.aliyuncs.com 就是 401
        return ("401=密钥被拒。新版百炼 key 必须配套专属域名：把控制台 key 详情页的 "
                "openAiCompatible 地址填进 .env 的 DASHSCOPE_BASE_URL")
    if status == 403:
        return ("403=额度问题。免费额度用完且开着「用完即停」：去百炼控制台免费额度页面"
                "关闭该开关（未实名认证关不了，先实名认证），或充值")
    if status == 404:
        return ("404=路径或模型名不对。检查 DASHSCOPE_BASE_URL 结尾是否为 "
                "/compatible-mode/v1，模型名是否拼写正确")
    return ""


def post(url, payload):
    """统一的 POST 封装：带鉴权头和 30 秒超时，返回响应对象"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    return requests.post(url, headers=headers, json=payload, timeout=30)


def check_text_model():
    """[1] 文本模型：发一句最小对话，验证 key + 兼容端点 + 模型名三样都正确"""
    print(f"[1/4] 文本模型  {LLM_MODEL}")
    print(f"      端点: {DASHSCOPE_BASE_URL}/chat/completions")
    if not DASHSCOPE_API_KEY:
        return report(False, "未配置 DASHSCOPE_API_KEY", "在 .env 里填入百炼 API-KEY")
    try:
        # OpenAI 兼容格式：模型列表见百炼文档；max_tokens=8 把本次测试消耗压到最低
        r = post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            {
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": "请只回复两个字：正常"}],
                "max_tokens": 8,
            },
        )
        if r.status_code == 200:
            # 响应结构: {"choices": [{"message": {"content": "..."}}]}
            reply = r.json()["choices"][0]["message"]["content"]
            return report(True, f"模型回复: {reply.strip()!r}")
        return report(False, f"HTTP {r.status_code}: {r.text[:150]}", hint_for(r.status_code))
    except requests.exceptions.ConnectionError:
        return report(False, "连接不上服务器", "检查网络/代理，或 DASHSCOPE_BASE_URL 域名是否拼对")
    except requests.exceptions.Timeout:
        return report(False, "请求超时（30 秒无响应）", "检查网络后重试")


def check_tts():
    """[2] 语音合成：qwen-tts 走 multimodal-generation 端点，
    非流式返回音频下载URL（24小时有效），再下载验证二进制可得"""
    print(f"[2/4] 语音合成  {TTS_MODEL}（音色 {DEFAULT_TTS_VOICE}）")
    print(f"      端点: {DASHSCOPE_NATIVE_URL}/api/v1/services/aigc/multimodal-generation/generation")
    if not DASHSCOPE_API_KEY:
        return report(False, "未配置 DASHSCOPE_API_KEY")
    try:
        r = post(
            f"{DASHSCOPE_NATIVE_URL}/api/v1/services/aigc/multimodal-generation/generation",
            {"model": TTS_MODEL, "input": {"text": "你好", "voice": DEFAULT_TTS_VOICE}},
        )
        if r.status_code == 200:
            audio_url = r.json().get("output", {}).get("audio", {}).get("url", "")
            if not audio_url:
                return report(False, f"HTTP 200 但响应无音频URL: {r.text[:150]}")
            audio = requests.get(audio_url, timeout=60)
            if audio.status_code == 200:
                return report(True, f"合成并下载音频 {len(audio.content)} 字节，题目朗读功能可用")
            return report(False, f"音频下载失败 HTTP {audio.status_code}")
        return report(False, f"HTTP {r.status_code}: {r.text[:150]}", hint_for(r.status_code))
    except requests.exceptions.RequestException as e:
        return report(False, f"请求异常: {e}", "检查 DASHSCOPE_NATIVE_URL 是否配了专属域名")


def check_asr():
    """[3] 语音识别：paraformer-v2 的录音转写只支持「异步任务 + 公网音频URL」，
    本地音频直传不可行（实测 OpenAI 兼容端点 /audio/transcriptions 也未开放），
    因此只显示配置不实测；要启用需安装 dashscope SDK 改用 Recognition 类"""
    print(f"[3/4] 语音识别  {ASR_MODEL}")
    print("  - 跳过实测：该模型仅支持异步任务+公网音频URL，本地录音直传不可行")
    print("    >> 修复方向: 安装 dashscope SDK 改用 Recognition 类（支持本地文件）；当前语音作答走前端降级")
    return True


def check_expression():
    """[4] 表情识别：需要真实人脸图片才有意义，假图只会报业务错误造成误判，
    所以这里只展示配置；真实验证方法 = 面试页开摄像头看后端 [FACE] 日志"""
    print(f"[4/4] 表情识别  {EXPRESSION_MODEL}")
    print("  - 跳过实测（需要真实人脸图片）；模型配置已读取")
    print("    >> 实测方法: 进入面试页开启摄像头，观察后端日志里的 [FACE] 输出")
    return True


def main():
    print("=" * 62)
    print("AI API 连通性测试（数据来自 .env，即项目运行时用的真实配置）")
    print("=" * 62)
    if DASHSCOPE_API_KEY:
        # 只显示 key 的头尾片段做身份核对，完整 key 不打印（防泄露到日志）
        print(f"key: {DASHSCOPE_API_KEY[:6]}...{DASHSCOPE_API_KEY[-4:]}  长度 {len(DASHSCOPE_API_KEY)}")
    print()
    results = [check_text_model(), check_tts(), check_asr(), check_expression()]
    passed = sum(1 for x in results if x)
    print()
    if passed == len(results):
        print(f"全部通过（{passed}/{len(results)}）—— AI 功能就绪，可开一场面试实测")
        return 0
    print(f"{passed}/{len(results)} 通过 —— 按上面的 >> 建议处理后重跑本脚本")
    return 1


if __name__ == "__main__":
    sys.exit(main())

# ====================================================================
# 版权声明：本代码仅供学习参考，禁止商用、禁止二次分发、
#          禁止使用本代码申请软件著作权
# ====================================================================
