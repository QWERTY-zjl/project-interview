"""
简历解析模块
====================
负责把上传的简历 PDF 解析成文本（Markdown）：
- 主路径：调用本地 MinerU CLI（GPU 加速，输出 Markdown，保留表格/公式）
- 降级路径：MinerU 不可用 / 超时 / 失败 / 输出为空时，自动降级 PyPDF2 提取纯文本
- 仍失败则返回空字符串，由上层处理

对外只暴露一个函数：parse_resume_to_markdown(pdf_bytes, filename)
"""

import os
import re
import sys
import uuid
import shutil
import logging
import subprocess

from app.config.config import TEMP_DIR

logger = logging.getLogger(__name__)

# MinerU CLI 与当前 Python 解释器同目录（即 app\venv\Scripts\mineru.exe）
MINERU_CLI = os.path.join(os.path.dirname(sys.executable), "mineru.exe")

# 解析超时（秒），可用环境变量 MINERU_TIMEOUT 覆盖
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "300"))

# 输出文本最大长度（防止超长简历撑爆 prompt），可用 MINERU_MAX_CHARS 覆盖
MAX_TEXT_CHARS = int(os.getenv("MINERU_MAX_CHARS", "8000"))

# Markdown 图片引用，如 ![alt](images/xxx.jpg) —— 对出题无价值，清洗掉
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _parse_by_mineru(pdf_bytes, work_dir):
    """
    用 MinerU CLI 解析 PDF，返回 markdown 文本。

    Args:
        pdf_bytes: PDF 文件的字节内容
        work_dir: 本次解析用的工作目录（输入输出都放在这里，用后整体删除）

    Returns:
        str: MinerU 输出的 markdown 文本

    Raises:
        FileNotFoundError: mineru.exe 不存在
        subprocess.TimeoutExpired: 解析超时
        RuntimeError: 进程非零退出 / 输出目录中没有 markdown 文件
    """
    if not os.path.isfile(MINERU_CLI):
        raise FileNotFoundError(f"未找到 MinerU CLI: {MINERU_CLI}")

    input_pdf = os.path.join(work_dir, "resume.pdf")
    output_dir = os.path.join(work_dir, "out")
    os.makedirs(output_dir, exist_ok=True)
    with open(input_pdf, "wb") as f:
        f.write(pdf_bytes)

    cmd = [MINERU_CLI, "-p", input_pdf, "-o", output_dir, "-b", "pipeline"]
    logger.info(f"[ResumeParser] 调用 MinerU: {' '.join(cmd)}")

    # 继承当前环境变量；未显式指定模型源时默认走 modelscope（国内直连）
    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=MINERU_TIMEOUT,
        env=env,
    )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:]
        raise RuntimeError(f"MinerU 退出码 {result.returncode}: {stderr_tail}")

    # MinerU 输出目录结构：<output_dir>/<pdf名>/<method>/*.md，直接全目录搜 .md
    for root, _, files in os.walk(output_dir):
        for name in sorted(files):
            if name.endswith(".md"):
                with open(os.path.join(root, name), "r", encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    logger.info(f"[ResumeParser] MinerU 解析成功，markdown 长度: {len(content)} 字符")
                    return content

    raise RuntimeError("MinerU 执行成功但未产出非空 markdown 文件")


def _parse_by_pypdf2(pdf_bytes):
    """
    降级方案：用 PyPDF2 提取 PDF 纯文本（丢失排版，但保证链路可用）。

    Args:
        pdf_bytes: PDF 文件的字节内容

    Returns:
        str: 提取的文本，失败返回空字符串
    """
    try:
        from io import BytesIO
        from PyPDF2 import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                pages.append(text)
        text = "\n".join(pages)
        logger.info(f"[ResumeParser] PyPDF2 降级解析完成，文本长度: {len(text)} 字符")
        return text
    except Exception as e:
        logger.error(f"[ResumeParser] PyPDF2 降级解析也失败: {e}")
        return ""


def _clean_text(text):
    """
    清洗解析结果：剥离图片引用、收敛连续空行、截断到最大长度。
    保留 HTML 表格与 LaTeX 公式（对出题有价值）。
    """
    text = _IMAGE_REF_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > MAX_TEXT_CHARS:
        logger.info(f"[ResumeParser] 文本超长（{len(text)} 字符），截断到 {MAX_TEXT_CHARS}")
        text = text[:MAX_TEXT_CHARS]
    return text


def parse_resume_to_markdown(pdf_bytes, filename=""):
    """
    解析简历 PDF 为文本（对外入口）。

    Args:
        pdf_bytes: PDF 文件的字节内容
        filename: 原始文件名（仅用于日志，不再参与实际路径）

    Returns:
        str: 解析出的 markdown / 纯文本；完全失败时返回空字符串
    """
    if not pdf_bytes:
        logger.warning("[ResumeParser] 收到空的 PDF 内容")
        return ""

    # 用 uuid 作为工作目录主名，规避中文文件名/路径带来的编码问题
    work_dir = os.path.join(TEMP_DIR, f"mineru_{uuid.uuid4().hex}")

    logger.info(f"[ResumeParser] 开始解析简历: {filename or '未命名'}，大小: {len(pdf_bytes)} 字节")

    md = ""
    try:
        os.makedirs(work_dir, exist_ok=True)

        # 1. 主路径：MinerU
        try:
            md = _parse_by_mineru(pdf_bytes, work_dir)
        except FileNotFoundError as e:
            logger.warning(f"[ResumeParser] {e}，降级 PyPDF2")
        except subprocess.TimeoutExpired:
            logger.warning(f"[ResumeParser] MinerU 解析超时（>{MINERU_TIMEOUT}s），降级 PyPDF2")
        except Exception as e:
            logger.warning(f"[ResumeParser] MinerU 解析失败: {e}，降级 PyPDF2")

        # 2. 降级路径：MinerU 不可用或输出为空时，用 PyPDF2 兜底
        if not md or not md.strip():
            logger.warning("[ResumeParser] MinerU 未产出有效内容，使用 PyPDF2 降级")
            md = _parse_by_pypdf2(pdf_bytes)

        # 3. 清洗并返回（彻底失败时为空字符串，由上层决定如何响应）
        return _clean_text(md) if md else ""

    finally:
        # 无论成功失败都清理临时目录
        shutil.rmtree(work_dir, ignore_errors=True)
