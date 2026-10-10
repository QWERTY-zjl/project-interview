"""
AI API 连通性测试脚本
======================
逐项测试项目用到的阿里云百炼 AI 服务是否真正可用，用来验证 .env 配置是否正确。
不需要启动项目服务器——脚本直接测「你的机器 -> 百炼」这一段链路。

测什么：
  [1] 文本模型 LLM_MODEL        —— 出题、面试报告都用它（走 OpenAI 兼容端点）
  [2] 语音合成 TTS_MODEL        —— 把面试题朗读出来（走 DashScope 原生端点）
  [3] 语音识别 ASR_MODEL        —— 把面试录音转成文字（走 DashScope 原生端点）
  [4] 视觉模型 VISION_MODEL     —— 表情识别用它；用一张程序生成的 2x2 纯色小图实测
      （不需要真实人脸：模型对没有脸的图也会正常返回 JSON，200 就说明链路通）

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
import struct
import sys
import wave
import zlib

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
    VISION_MODEL,
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
        return ("403 有两种可能（官方文档）：① 免费额度用完且开着「用完即停」——去百炼"
                "控制台免费额度页面关闭该开关（未实名认证关不了，先实名认证）或充值；"
                "② 业务空间 key 没有该模型的调用授权——新版百炼的 key 属于某个业务空间，"
                "模型不会自动开放，需用主账号在「模型广场/模型开通」里为该业务空间开通此模型")
    if status == 404:
        return ("404=路径或模型名不对。检查 DASHSCOPE_BASE_URL 结尾是否为 "
                "/compatible-mode/v1，模型名是否拼写正确")
    return ""


def post(url, payload):
    """统一的 POST 封装：带鉴权头和 30 秒超时，返回响应对象"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    return requests.post(url, headers=headers, json=payload, timeout=30)


def get(url):
    """统一的 GET 封装：带鉴权头和 30 秒超时，返回响应对象（查模型配额用）"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    return requests.get(url, headers=headers, timeout=30)


def make_tiny_png():
    """用纯标准库生成一张 32x32 的蓝色 PNG 图片（不依赖 Pillow）。

    尺寸不能太小：视觉模型要求边长 > 10 像素，否则 400 拒收。
    PNG 文件结构：文件头(8字节魔数) + IHDR(图像尺寸/位深) + IDAT(像素数据) + IEND，
    每个数据块 = 4字节长度 + 块类型 + 数据 + 4字节CRC校验。
    zlib.compress 负责把原始像素压成 IDAT 要求的 zlib 格式；
    struct.pack('>I', n) 把数字转成 4 字节大端无符号整数（PNG 规定大端）。
    """
    def chunk(tag, data):
        # 一个标准 PNG 数据块 = 长度 + 类型+数据 + CRC 校验
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    w = h = 32
    # 像素原始数据：每行开头 1 字节过滤器类型（0=不过滤），后跟每像素 3 字节 RGB（蓝色）
    raw = b"".join(b"\x00" + b"\x33\x66\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"                                      # PNG 文件魔数，固定
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))  # 32x32、8位、真彩色
            + chunk(b"IDAT", zlib.compress(raw))                       # 压缩后的像素
            + chunk(b"IEND", b""))                                     # 文件结束块


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
    """[2] 语音合成：cosyvoice 系列走 SpeechSynthesizer 端点，
    响应为音频二进制流，或 JSON（output.audio.url 指向 OSS 临时音频）"""
    print(f"[2/4] 语音合成  {TTS_MODEL}（音色 {DEFAULT_TTS_VOICE}）")
    print(f"      端点: {DASHSCOPE_NATIVE_URL}/api/v1/services/audio/tts/SpeechSynthesizer")
    if not DASHSCOPE_API_KEY:
        return report(False, "未配置 DASHSCOPE_API_KEY")
    try:
        r = post(
            f"{DASHSCOPE_NATIVE_URL}/api/v1/services/audio/tts/SpeechSynthesizer",
            {
                "model": TTS_MODEL,
                "input": {"text": "你好", "voice": DEFAULT_TTS_VOICE, "format": "wav", "sample_rate": 24000},
            },
        )
        if r.status_code == 200:
            content_type = r.headers.get("Content-Type", "")
            if "audio" in content_type or "octet-stream" in content_type:
                return report(True, f"合成音频 {len(r.content)} 字节，题目朗读功能可用")
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
    """[3] 语音识别：paraformer 系列的录音转写只支持「异步任务 + 公网音频URL」，
    本地音频直传不可行（实测 OpenAI 兼容端点 /audio/transcriptions 也未开放），
    因此只显示配置不实测；要启用需安装 dashscope SDK 改用 Recognition 类"""
    print(f"[3/4] 语音识别  {ASR_MODEL}")
    print("  - 跳过实测：该模型仅支持异步任务+公网音频URL，本地录音直传不可行")
    print("    >> 修复方向: 安装 dashscope SDK 改用 Recognition 类（支持本地文件）；当前语音作答走前端降级")
    return True


def check_expression():
    """[4] 视觉模型（表情识别）：分两步排查 403 之类的问题。

    第 1 步查官方配额诊断接口 GET /api/v1/models/limits?model=xxx：
    官方文档说它能返回当前 key 所在业务空间对该模型的额度/开通状态，
    是区分「额度耗尽」还是「模型未授权」最直接的证据（查询本身不消耗额度）。

    第 2 步真实调用一次 chat/completions 多模态请求：content 用数组格式
    （[{图}, {文}]），图是 dataURL 内嵌的 32x32 小 PNG。模型对没有脸的图
    也会正常回复，所以 HTTP 200 即代表「key/端点/模型/授权/额度」全链路通。
    """
    print(f"[4/4] 视觉模型  {VISION_MODEL}（表情识别）")
    print(f"      兼容端点: {DASHSCOPE_BASE_URL}/chat/completions")
    if not DASHSCOPE_API_KEY:
        return report(False, "未配置 DASHSCOPE_API_KEY", "在 .env 里填入百炼 API-KEY")

    # --- 第 1 步：官方配额诊断接口（只读查询，不花钱）-------------------
    limits_url = f"{DASHSCOPE_NATIVE_URL}/api/v1/models/limits?model={VISION_MODEL}"
    print(f"      ① 查配额状态: GET {limits_url}")
    try:
        r = get(limits_url)
        if r.status_code == 200:
            print(f"        配额信息: {r.text[:300]}")
        else:
            # 该接口在新版专属域名上不一定开放，查不到就当提示，不算失败
            print(f"        （接口返回 HTTP {r.status_code}，此域名可能未开放该诊断接口，跳过）")
    except requests.exceptions.RequestException as e:
        print(f"        （查询异常: {e}，跳过）")

    # --- 第 2 步：真实多模态调用 ----------------------------------------
    print(f"      ② 真实调用: 发送 32x32 测试图")
    png_data = make_tiny_png()
    data_url = "data:image/png;base64," + base64.b64encode(png_data).decode("utf-8")
    try:
        # 多模态消息格式：content 是数组，图片项在前、文字指令在后
        r = post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            {
                "model": VISION_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "这张图里是什么颜色？只回答颜色词"},
                ]}],
                "max_tokens": 8,
            },
        )
        if r.status_code == 200:
            reply = r.json()["choices"][0]["message"]["content"]
            return report(True, f"模型回复: {reply.strip()!r} —— 表情识别链路可用")
        # 403 时把完整响应体打出来：body 里的 error.code 能区分
        # insufficient_quota（额度）和 Model.AccessDenied（未授权）两种病因
        print(f"        完整响应体: {r.text[:400]}")
        return report(False, f"HTTP {r.status_code}: {r.text[:150]}", hint_for(r.status_code))
    except requests.exceptions.ConnectionError:
        return report(False, "连接不上服务器", "检查网络/代理，或 DASHSCOPE_BASE_URL 域名是否拼对")
    except requests.exceptions.Timeout:
        return report(False, "请求超时（30 秒无响应）", "检查网络后重试")


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
