"""
简历解析模块
====================
负责把上传的简历文件解析成文本（Markdown/纯文本）：
- PDF：用 pypdf 提取纯文本
- DOCX：用 python-docx 提取段落与表格文本
- 其他（TXT/MD 等）：按纯文本解码（utf-8 → gbk 回退）
- 完全失败则返回空字符串，由上层处理

对外只暴露一个函数：extract_resume_text(file_bytes, filename)
（parse_resume_to_markdown 为 PDF 分支的内部实现入口）
"""

import os
import re
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# python-docx 缺失时仅 DOCX 链路不可用，不影响 PDF/TXT 链路
try:
    import docx as docx_lib
    DOCX_SUPPORT = True
    logger.info("[ResumeParser] 导入 python-docx 库成功")
except ImportError:
    DOCX_SUPPORT = False
    logger.warning("[ResumeParser] 缺少 python-docx 库，DOCX 简历将无法解析（可 pip install python-docx）")

# 输出文本最大长度（防止超长简历撑爆 prompt），可用环境变量 RESUME_MAX_CHARS 覆盖
MAX_TEXT_CHARS = int(os.getenv("RESUME_MAX_CHARS", "8000"))

# Markdown 图片引用，如 ![alt](images/xxx.jpg) —— 对出题无价值，清洗掉
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _parse_by_pypdf(pdf_bytes):
    """用 pypdf 提取 PDF 纯文本，失败返回空字符串"""
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

    直接用 pypdf 提取文本，清洗截断后返回；
    完全失败时返回空字符串，由上层决定如何响应。
    """
    if not pdf_bytes:
        logger.warning("[ResumeParser] 收到空的 PDF 内容")
        return ""

    logger.info(f"[ResumeParser] 开始解析简历: {filename or '未命名'}，大小: {len(pdf_bytes)} 字节")

    md = _parse_by_pypdf(pdf_bytes)
    return _clean_text(md) if md else ""


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
    - %PDF-    → PDF 链路（pypdf 提取纯文本）
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
