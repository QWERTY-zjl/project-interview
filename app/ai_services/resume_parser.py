"""
简历解析模块
====================
负责把上传的简历文件解析成文本（Markdown/纯文本）：
- PDF：主路径调用本地 MinerU CLI（GPU 加速，输出 Markdown，保留表格/公式），
  降级路径用 pypdf 提取纯文本（MinerU 不可用 / 超时 / 失败 / 输出为空时自动切换）
- DOCX：用 python-docx 提取段落与表格文本
- 其他（TXT/MD 等）：按纯文本解码（utf-8 → gbk 回退）
- 完全失败则返回空字符串，由上层处理

对外只暴露一个函数：extract_resume_text(file_bytes, filename)
（parse_resume_to_markdown 为 PDF 分支的内部实现入口）
"""

import os
import re
import sys
import uuid
import shutil
import logging
import subprocess
from io import BytesIO

from app.config.config import TEMP_DIR

logger = logging.getLogger(__name__)

# python-docx 缺失时仅 DOCX 链路不可用，不影响 PDF/TXT 链路
try:
    import docx as docx_lib
    DOCX_SUPPORT = True
    logger.info("[ResumeParser] 导入 python-docx 库成功")
except ImportError:
    DOCX_SUPPORT = False
    logger.warning("[ResumeParser] 缺少 python-docx 库，DOCX 简历将无法解析（可 pip install python-docx）")

# MinerU CLI 与当前 Python 解释器同目录（即 app\venv\Scripts\mineru.exe）
MINERU_CLI = os.path.join(os.path.dirname(sys.executable), "mineru.exe")

# 解析超时（秒），可用环境变量 MINERU_TIMEOUT 覆盖
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "300"))

# 输出文本最大长度（防止超长简历撑爆 prompt），可用 MINERU_MAX_CHARS 覆盖
MAX_TEXT_CHARS = int(os.getenv("MINERU_MAX_CHARS", "8000"))

# Markdown 图片引用，如 ![alt](images/xxx.jpg) —— 对出题无价值，清洗掉
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _parse_by_mineru(pdf_bytes, work_dir):
    """用 MinerU CLI 解析 PDF，返回 markdown 文本
    （work_dir 为本次解析的工作目录，输入输出都放在这里，用后整体删除）"""
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


def _parse_by_pypdf(pdf_bytes):
    """降级方案：用 pypdf 提取 PDF 纯文本（丢失排版，但保证链路可用），失败返回空字符串"""
    try:
        from io import BytesIO
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                pages.append(text)
        text = "\n".join(pages)
        logger.info(f"[ResumeParser] pypdf 降级解析完成，文本长度: {len(text)} 字符")
        return text
    except Exception as e:
        logger.error(f"[ResumeParser] pypdf 降级解析也失败: {e}")
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

    MinerU 主路径失败/输出为空时用 pypdf 降级，清洗截断后返回；
    完全失败时返回空字符串，由上层决定如何响应。
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
            logger.warning("[ResumeParser] MinerU 未产出有效内容，使用 pypdf 降级")
            md = _parse_by_pypdf(pdf_bytes)

        # 3. 清洗并返回（彻底失败时为空字符串，由上层决定如何响应）
        return _clean_text(md) if md else ""

    finally:
        # 无论成功失败都清理临时目录
        shutil.rmtree(work_dir, ignore_errors=True)


def _parse_by_docx(file_bytes):
    """
    解析 DOCX 简历为纯文本（python-docx）。

    提取顺序：先正文段落（保留换行，正则分析依赖段落结构），
    再表格（单元格用 " | " 拼接成一行，模拟简历里的表格排版）。
    """
    if not DOCX_SUPPORT:
        raise RuntimeError("python-docx 库未安装，无法解析 DOCX 文件")

    try:
        document = docx_lib.Document(BytesIO(file_bytes))
    except Exception as e:
        # 文件头是 PK 但不是合法 docx（比如改名的 zip/pptx）会在这里抛出
        raise RuntimeError(f"DOCX 文件打开失败: {e}")

    parts = []

    # 1. 正文段落：跳过空行
    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    # 2. 表格：每行拼成 "单元格 | 单元格"（简历的教育/技能常用表格排版）
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    text = "\n".join(parts)
    logger.info(f"[ResumeParser] DOCX 解析成功，提取文本长度: {len(text)} 字符")
    return text


def _decode_text(file_bytes):
    """
    把纯文本类文件（TXT/MD 等）的字节解码成字符串。

    编码探测顺序：utf-8（最常见）→ gbk（Windows 记事本中文默认）→
    utf-8 replace 模式（保底，坏字节替换，不中断流程）。
    """
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("gbk")
        except UnicodeDecodeError:
            logger.warning("[ResumeParser] 文本解码 utf-8/gbk 均失败，使用 replace 模式保底")
            return file_bytes.decode("utf-8", errors="replace")


def extract_resume_text(file_bytes, filename=""):
    """
    解析任意支持的简历文件为文本（对外统一入口）。

    按文件头（magic bytes）自动识别类型，不信任扩展名——改名的文件
    也能被正确分流：
    - %PDF-    → PDF 链路（MinerU 主路径 + pypdf 降级）
    - PK\x03\x04 → DOCX 链路（python-docx；docx 本质是 zip 容器）
    - 其他     → 纯文本解码（TXT/MD 等）

    返回已清洗、截断到 MAX_TEXT_CHARS 的文本；
    完全解析失败时返回空字符串，由上层决定如何响应。
    """
    if not file_bytes:
        logger.warning("[ResumeParser] 收到空的文件内容: %s", filename or "未命名")
        return ""

    logger.info(f"[ResumeParser] 开始解析简历: {filename or '未命名'}，大小: {len(file_bytes)} 字节")

    # 1. PDF：%PDF- 魔数
    if file_bytes.startswith(b"%PDF-"):
        return parse_resume_to_markdown(file_bytes, filename)

    # 2. DOCX：zip 容器的 PK 魔数（docx/xlsx/pptx 都是 PK 开头，
    #    打开时若不是合法 docx 会抛错，捕获后返回空串走上层报错）
    if file_bytes.startswith(b"PK\x03\x04"):
        if not DOCX_SUPPORT:
            logger.error("[ResumeParser] 收到 DOCX 文件但 python-docx 未安装: %s", filename)
            return ""
        try:
            text = _parse_by_docx(file_bytes)
        except Exception as e:
            logger.warning(f"[ResumeParser] DOCX 解析失败: {e}")
            return ""
        return _clean_text(text) if text else ""

    # 3. 其他：按纯文本解码（TXT/MD 等）
    text = _decode_text(file_bytes)
    if not text.strip():
        logger.warning("[ResumeParser] 文本解码后内容为空: %s", filename)
        return ""
    logger.info(f"[ResumeParser] 纯文本解码完成，长度: {len(text)} 字符")
    return _clean_text(text)
