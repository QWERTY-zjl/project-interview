"""
表情分析服务模块
================
本模块负责面部表情分析功能
"""

import base64
import json
import requests
from app.config.config import DASHSCOPE_API_KEY


def analyze_face_expression(image_data):
    """
    分析面部表情
    
    参数:
        image_data: 图像二进制数据
    
    返回:
        (分析结果, 错误信息)，成功时错误信息为None
    """
    try:
        print(f"[FACE] 开始表情分析，图像大小: {len(image_data)} 字节")
        
        # 获取API密钥
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            print("[FACE] 错误: API Key 为空!")
            return None, "未配置 DASHSCOPE_API_KEY"
        
        # 构建API请求
        url = "https://dashscope.aliyuncs.com/api/v1/services/vision/face/expression"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 将图像转换为base64编码
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # 构建请求参数
        data = {
            "model": "face-expression-detection",
            "input": {
                "image": image_base64
            },
            "parameters": {
                "return_face_data": True
            }
        }
        
        # 发送API请求
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()  # 自动处理HTTP错误
        
        print(f"[FACE] API 响应状态: {response.status_code}")
        
        result = response.json()
        # 解析响应结果
        if result.get("output") and result["output"].get("faces"):
            faces = result["output"]["faces"]
            print(f"[FACE] 检测到 {len(faces)} 张人脸")
            return faces, None
        else:
            return None, "表情分析失败: 响应格式错误"
        
    except requests.RequestException as e:
        print(f"[FACE] API请求失败: {e}")
        return None, f"表情分析失败: {str(e)}"
    except ImportError as e:
        print(f"[FACE] 缺少依赖: {e}")
        return None, f"缺少requests库, 请运行: pip install requests"
    except Exception as e:
        print(f"[FACE] 异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, str(e)
