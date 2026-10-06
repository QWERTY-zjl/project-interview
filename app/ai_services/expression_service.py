"""
表情分析服务模块
================
负责分析面试摄像头抓拍画面中候选人的表情/情绪。

【2026-10-06 重写：改用 qwen3-vl-flash 多模态模型】
原先调用的 face-expression-detection 是企业版遗留的虚构模型（百炼上不存在，
调用必 404）。现在改用百炼真实存在的最便宜视觉模型 qwen3-vl-flash
（输入 0.15 元/百万 token，与文本模型 qwen-flash 同价），把抓拍图片发给
大模型，让它按固定 JSON 格式返回表情和情绪判断。

成本：一张 640x480 抓拍图约几百 token，单次分析不到 0.001 元；
按每 5 秒抓拍一次算，一场 15 分钟面试约 0.1~0.2 元。

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

import base64
import json
import logging
import os

from openai import OpenAI

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, VISION_MODEL

logger = logging.getLogger(__name__)

# 模型客户端单例：OpenAI SDK 会维护底层 HTTP 连接池，每个进程建一次即可
# （与 question_service 的 _get_client 同款做法）
_client = None


def _get_client():
    """获取（并惰性创建）OpenAI 兼容客户端，指向百炼的兼容端点"""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY"),
            base_url=DASHSCOPE_BASE_URL,
        )
    return _client


# 让模型返回固定 JSON 的提示词：
# 表情名用通用英文标签（happy/sad/neutral/angry/surprised/fearful/disgusted），
# 情绪状态三档（积极/中性/消极）与 interview_expression_records 表、报告聚合逻辑对齐，
# emotion_score 是"情绪状态分"（0=非常消极，100=非常积极），供前端进度条显示
_ANALYSIS_PROMPT = """你是面试表情分析师。分析这张面试摄像头抓拍画面中人物的面部表情。
只输出一个 JSON 对象，不要输出任何其他文字，格式如下：
{"expression": "表情英文标签", "expression_cn": "表情中文名", "emotion_status": "积极|中性|消极", "emotion_score": 0到100的整数}
说明：
- expression 从 happy/sad/neutral/angry/surprised/fearful/disgusted 中选择
- expression_cn 是 expression 对应的中文（开心/难过/平静/生气/惊讶/恐惧/厌恶）
- emotion_status 只能是 积极、中性、消极 三者之一
- emotion_score 反映整体情绪倾向：非常消极=0，平静=50，非常积极=100
- 如果画面中没有清晰人脸，输出 {"no_face": true}"""


def analyze_face_expression(image_data):
    """
    分析面部表情（qwen3-vl-flash 多模态版）

    Args:
        image_data: 图像二进制数据（前端 canvas.toDataURL 去 dataURL 前缀后的原始字节）

    Returns:
        (分析结果, 错误信息)，成功时错误信息为None
        成功时返回 faces 列表（保持与旧版返回结构兼容：
        expression_api 取 faces[0] 的 expression/expression_cn/emotion_status/
        emotion_score 字段，所以这里按同样的键组装）；
        画面中没有人脸时返回空列表 []（expression_api 据此返回 400"未检测到人脸"）
    """
    # 快速失败：没配密钥就不发请求（与出题/报告的检查逻辑一致）
    if not (os.getenv("DASHSCOPE_API_KEY") or DASHSCOPE_API_KEY):
        return None, "未配置 DASHSCOPE_API_KEY"

    try:
        print(f"[FACE] 开始表情分析（qwen3-vl-flash），图像大小: {len(image_data)} 字节")

        # 图像转 base64，用 dataURL 形式直接嵌进消息体（OpenAI 视觉消息标准格式）
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        data_url = f"data:image/jpeg;base64,{image_base64}"

        # 多模态消息格式：content 是一个数组，图文混排
        # （纯文本消息 content 是字符串，视觉消息 content 是 [{image_url}, {text}] 列表）
        messages = [
            {"role": "system", "content": _ANALYSIS_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": "请分析画面中人物的表情"}
            ]}
        ]

        response = _get_client().chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            max_tokens=200,       # 只需要一小段 JSON，限制输出省 token
            temperature=0.1,      # 判断类任务要稳定，不要发散
            # response_format 不用 json_object：VL 模型对图像+JSON 的组合
            # 兼容性不稳定，靠提示词约束 + 解析兜底更可靠
        )
        content = (response.choices[0].message.content or "").strip()
        print(f"[FACE] 模型返回: {content[:200]}")

        # 解析模型返回：先直接按 JSON 解析，失败则剥掉 ```json 围栏再试一次
        # （与 question_service/report_service 的兜底策略相同）
        data = None
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            if content:
                import re
                stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
        if not isinstance(data, dict):
            return None, "表情分析失败: 模型返回不是合法 JSON"

        # 画面里没有人脸：返回空列表，调用方（expression_api）转成 400"未检测到人脸"
        if data.get("no_face"):
            print("[FACE] 画面中未检测到清晰人脸")
            return [], None

        # 组装与旧接口兼容的结构：quality_score/final_score 是企业版遗留字段，
        # 新链路没有真实来源，固定 0（不做假数据）
        face = {
            "expression": data.get("expression", ""),
            "expression_cn": data.get("expression_cn", ""),
            "confidence": 1.0,
            "emotion_status": data.get("emotion_status", ""),
            "emotion_score": data.get("emotion_score", 0),
            "quality_score": 0,
            "final_score": 0,
            "suggestions": [],
        }
        print(f"[FACE] 分析完成: {face['expression_cn']} / {face['emotion_status']} / {face['emotion_score']}分")
        return [face], None

    except Exception as e:
        print(f"[FACE] 异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, str(e)
