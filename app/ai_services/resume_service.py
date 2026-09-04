"""
简历分析服务模块
"""

import json
import logging
import os
import re
from io import BytesIO

logger = logging.getLogger(__name__)


# 导入必要的库
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
    logger.info("[Resume] 导入 PyPDF2 库成功")
except ImportError:
    PDF_SUPPORT = False
    logger.warning("[Resume] 缺少 PyPDF2 库，无法解析PDF文件")


def analyze_resume(resume_content, work_experience, target_position):
    """
    分析简历内容
    
    参数:
        resume_content: 简历内容（字节或字符串）
        work_experience: 工作经验
        target_position: 目标岗位
    
    返回:
        分析结果
    """
    logger.info("[Resume] 开始分析简历")
    
    try:
        # 处理简历内容
        if isinstance(resume_content, bytes):
            try:
                resume_text = resume_content.decode('utf-8')
            except UnicodeDecodeError:
                # 尝试其他编码
                try:
                    resume_text = resume_content.decode('gbk')
                except UnicodeDecodeError:
                    # 如果仍然失败，使用replace模式
                    resume_text = resume_content.decode('utf-8', errors='replace')
        else:
            resume_text = str(resume_content)
        
        logger.info(f"[Resume] 简历文本长度: {len(resume_text)} 字符")
        
        # 提取基本信息
        basic_info = extract_basic_info(resume_text)
        logger.info(f"[Resume] 基本信息: {basic_info}")
        
        # 提取教育背景
        education = extract_education(resume_text)
        logger.info(f"[Resume] 教育背景: {education}")
        
        # 提取工作经验
        work_exp = extract_work_experience(resume_text)
        logger.info(f"[Resume] 工作经验: {work_exp}")
        
        # 提取技能
        skills = extract_skills(resume_text)
        logger.info(f"[Resume] 技能: {skills}")
        
        # 提取项目经验
        projects = extract_projects(resume_text)
        logger.info(f"[Resume] 项目经验: {projects}")
        
        # 提取证书
        certificates = extract_certificates(resume_text)
        logger.info(f"[Resume] 证书: {certificates}")
        
        # 分析与目标岗位的匹配度
        match_score = calculate_match_score(resume_text, target_position, skills)
        logger.info(f"[Resume] 与目标岗位的匹配度: {match_score}")
        
        # 生成分析结果
        analysis_result = {
            "basic_info": basic_info,
            "education": education,
            "work_experience": work_exp,
            "skills": skills,
            "projects": projects,
            "certificates": certificates,
            "match_score": match_score,
            "work_experience_years": work_experience,
            "target_position": target_position
        }
        
        logger.info("[Resume] 简历分析完成")
        return analysis_result
        
    except Exception as e:
        logger.error(f"[Resume] 分析简历失败: {e}")
        import traceback
        traceback.print_exc()
        # 返回默认分析结果
        return {
            "basic_info": {},
            "education": [],
            "work_experience": [],
            "skills": [],
            "projects": [],
            "certificates": [],
            "match_score": 50,
            "work_experience_years": work_experience,
            "target_position": target_position
        }


def extract_basic_info(text):
    """
    提取基本信息
    """
    basic_info = {}
    
    # 提取姓名
    name_pattern = r'^(?:姓名|Name)[：:]?\s*([\u4e00-\u9fa5a-zA-Z\s]+)'  # 支持中文和英文姓名
    name_match = re.search(name_pattern, text, re.MULTILINE)
    if name_match:
        basic_info['name'] = name_match.group(1).strip()
    
    # 提取电话
    phone_pattern = r'^(?:电话|Phone|手机|Mobile)[：:]?\s*([0-9\-\+\s]+)'  # 支持带区号和分隔符的电话
    phone_match = re.search(phone_pattern, text, re.MULTILINE)
    if phone_match:
        basic_info['phone'] = phone_match.group(1).strip()
    
    # 提取邮箱
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    email_match = re.search(email_pattern, text)
    if email_match:
        basic_info['email'] = email_match.group(0)
    
    # 提取地址
    address_pattern = r'^(?:地址|Address)[：:]?\s*([\u4e00-\u9fa5a-zA-Z0-9\s\-\,]+)'  # 支持中文和英文地址
    address_match = re.search(address_pattern, text, re.MULTILINE)
    if address_match:
        basic_info['address'] = address_match.group(1).strip()
    
    # 提取性别
    gender_pattern = r'^(?:性别|Gender)[：:]?\s*([\u4e00-\u9fa5a-zA-Z]+)'  # 支持中文和英文性别
    gender_match = re.search(gender_pattern, text, re.MULTILINE)
    if gender_match:
        basic_info['gender'] = gender_match.group(1).strip()
    
    # 提取年龄
    age_pattern = r'^(?:年龄|Age)[：:]?\s*(\d+)'  # 提取年龄数字
    age_match = re.search(age_pattern, text, re.MULTILINE)
    if age_match:
        basic_info['age'] = age_match.group(1).strip()
    
    return basic_info


def extract_education(text):
    """
    提取教育背景
    """
    education = []
    
    # 查找教育部分
    education_pattern = r'教育(?:背景|经历|学历)|Education(?: Background| Experience| Qualification)'
    education_match = re.search(education_pattern, text, re.IGNORECASE)
    
    if education_match:
        # 提取教育部分的文本
        start_pos = education_match.end()
        # 查找下一个主要部分的开始
        next_section_pattern = r'(工作|实习|项目|技能|证书|获奖|自我评价|Work|Internship|Project|Skill|Certificate|Award|Self-evaluation)'
        next_section_match = re.search(next_section_pattern, text[start_pos:], re.IGNORECASE)
        
        if next_section_match:
            end_pos = start_pos + next_section_match.start()
        else:
            end_pos = len(text)
        
        education_text = text[start_pos:end_pos]
        
        # 提取教育条目
        # 匹配包含时间范围和学校名称的条目
        edu_item_pattern = r'(\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*[-~至]\s*\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?|\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*至今|Present)(.*?)(?=(?:\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*[-~至]|\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*至今|Present|$))'
        edu_items = re.findall(edu_item_pattern, education_text, re.DOTALL)
        
        for item in edu_items:
            period = item[0].strip()
            details = item[1].strip()
            
            if details:
                # 提取学校名称
                school_pattern = r'^\s*(.+?)\s*(?:大学|学院|University|College|Institute)'
                school_match = re.search(school_pattern, details)
                school = school_match.group(0).strip() if school_match else ""
                
                # 提取专业
                major_pattern = r'(?:专业|Major)[：:]?\s*(.+?)\s*(?=\n|$)'
                major_match = re.search(major_pattern, details)
                major = major_match.group(1).strip() if major_match else ""
                
                # 提取学位
                degree_pattern = r'(?:学位|Degree)[：:]?\s*(.+?)\s*(?=\n|$)'
                degree_match = re.search(degree_pattern, details)
                degree = degree_match.group(1).strip() if degree_match else ""
                
                education.append({
                    "period": period,
                    "school": school,
                    "major": major,
                    "degree": degree
                })
    
    return education


def extract_work_experience(text):
    """
    提取工作经验
    """
    work_experience = []
    
    # 查找工作经验部分
    work_pattern = r'工作(?:经验|经历)|Work(?: Experience| History)'
    work_match = re.search(work_pattern, text, re.IGNORECASE)
    
    if work_match:
        # 提取工作经验部分的文本
        start_pos = work_match.end()
        # 查找下一个主要部分的开始
        next_section_pattern = r'(教育|实习|项目|技能|证书|获奖|自我评价|Education|Internship|Project|Skill|Certificate|Award|Self-evaluation)'
        next_section_match = re.search(next_section_pattern, text[start_pos:], re.IGNORECASE)
        
        if next_section_match:
            end_pos = start_pos + next_section_match.start()
        else:
            end_pos = len(text)
        
        work_text = text[start_pos:end_pos]
        
        # 提取工作条目
        # 匹配包含时间范围和公司名称的条目
        work_item_pattern = r'(\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*[-~至]\s*\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?|\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*至今|Present)(.*?)(?=(?:\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*[-~至]|\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*至今|Present|$))'
        work_items = re.findall(work_item_pattern, work_text, re.DOTALL)
        
        for item in work_items:
            period = item[0].strip()
            details = item[1].strip()
            
            if details:
                # 提取公司名称
                company_pattern = r'^\s*(.+?)\s*(?:公司|企业|集团|Co\.|Inc\.|Ltd\.)'
                company_match = re.search(company_pattern, details)
                company = company_match.group(1).strip() if company_match else ""
                
                # 提取职位
                position_pattern = r'(?:职位|职位名称|Position)[：:]?\s*(.+?)\s*(?=\n|$)'
                position_match = re.search(position_pattern, details)
                position = position_match.group(1).strip() if position_match else ""
                
                # 提取职责
                responsibility_pattern = r'(?:职责|工作内容|Responsibilities|Job Description)[：:]?(.*?)(?=(?:职位|职位名称|Position|$))'
                responsibility_match = re.search(responsibility_pattern, details, re.DOTALL)
                responsibilities = responsibility_match.group(1).strip() if responsibility_match else ""
                
                work_experience.append({
                    "period": period,
                    "company": company,
                    "position": position,
                    "responsibilities": responsibilities
                })
    
    return work_experience


def extract_skills(text):
    """
    提取技能
    """
    skills = []
    
    # 查找技能部分
    skill_pattern = r'技能|Skills|专业技能|Technical Skills'
    skill_match = re.search(skill_pattern, text, re.IGNORECASE)
    
    if skill_match:
        # 提取技能部分的文本
        start_pos = skill_match.end()
        # 查找下一个主要部分的开始
        next_section_pattern = r'(教育|工作|实习|项目|证书|获奖|自我评价|Education|Work|Internship|Project|Certificate|Award|Self-evaluation)'
        next_section_match = re.search(next_section_pattern, text[start_pos:], re.IGNORECASE)
        
        if next_section_match:
            end_pos = start_pos + next_section_match.start()
        else:
            end_pos = len(text)
        
        skill_text = text[start_pos:end_pos]
        
        # 提取技能条目
        # 匹配技能列表
        skill_item_pattern = r'[\u4e00-\u9fa5a-zA-Z0-9+#-]+(?:\s*[,，]\s*[\u4e00-\u9fa5a-zA-Z0-9+#-]+)*'
        skill_items = re.findall(skill_item_pattern, skill_text)
        
        for item in skill_items:
            # 分割技能
            item_skills = re.split(r'[,，]\s*', item)
            for skill in item_skills:
                skill = skill.strip()
                if skill:
                    skills.append(skill)
    
    # 如果没有找到技能部分，尝试从整个文本中提取常见技能
    if not skills:
        # 常见技能列表
        common_skills = [
            'Python', 'Java', 'C++', 'JavaScript', 'HTML', 'CSS', 'React', 'Vue', 'Angular',
            'Node.js', 'Flask', 'Django', 'FastAPI', 'MySQL', 'PostgreSQL', 'MongoDB',
            'Git', 'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP', 'Linux', 'Windows',
            '数据结构', '算法', '操作系统', '计算机网络', '数据库', '机器学习', '深度学习',
            '人工智能', '自然语言处理', '计算机视觉', '大数据', '云计算', 'DevOps', '前端开发',
            '后端开发', '全栈开发', '移动开发', 'iOS', 'Android', 'Unity', '游戏开发',
            'UI设计', 'UX设计', '产品经理', '项目管理', '敏捷开发', 'Scrum', 'Kanban'
        ]
        
        for skill in common_skills:
            if skill.lower() in text.lower():
                skills.append(skill)
    
    # 去重
    skills = list(set(skills))
    
    return skills


def extract_projects(text):
    """
    提取项目经验
    """
    projects = []
    
    # 查找项目经验部分
    project_pattern = r'项目(?:经验|经历)|Projects|Project Experience'
    project_match = re.search(project_pattern, text, re.IGNORECASE)
    
    if project_match:
        # 提取项目经验部分的文本
        start_pos = project_match.end()
        # 查找下一个主要部分的开始
        next_section_pattern = r'(教育|工作|实习|技能|证书|获奖|自我评价|Education|Work|Internship|Skill|Certificate|Award|Self-evaluation)'
        next_section_match = re.search(next_section_pattern, text[start_pos:], re.IGNORECASE)
        
        if next_section_match:
            end_pos = start_pos + next_section_match.start()
        else:
            end_pos = len(text)
        
        project_text = text[start_pos:end_pos]
        
        # 提取项目条目
        # 匹配包含项目名称的条目
        project_item_pattern = r'([^\n]+?)(?:\n|\r\n)(.*?)(?=(?:[^\n]+?\n|$))'
        project_items = re.findall(project_item_pattern, project_text, re.DOTALL)
        
        for item in project_items:
            project_name = item[0].strip()
            details = item[1].strip()
            
            if project_name:
                # 提取项目时间
                time_pattern = r'(\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*[-~至]\s*\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?|\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?\s*至今|Present)'
                time_match = re.search(time_pattern, details)
                project_time = time_match.group(0).strip() if time_match else ""
                
                # 提取项目描述
                description_pattern = r'(?:描述|简介|Description)[：:]?(.*?)(?=(?:技术栈|使用技术|Technologies|$))'
                description_match = re.search(description_pattern, details, re.DOTALL)
                description = description_match.group(1).strip() if description_match else ""
                
                # 提取技术栈
                tech_pattern = r'(?:技术栈|使用技术|Technologies)[：:]?(.*?)(?=(?:描述|简介|Description|$))'
                tech_match = re.search(tech_pattern, details, re.DOTALL)
                technologies = tech_match.group(1).strip() if tech_match else ""
                
                projects.append({
                    "name": project_name,
                    "time": project_time,
                    "description": description,
                    "technologies": technologies
                })
    
    return projects


def extract_certificates(text):
    """
    提取证书
    """
    certificates = []
    
    # 查找证书部分
    cert_pattern = r'证书|Certificates|资格证书|Certifications'
    cert_match = re.search(cert_pattern, text, re.IGNORECASE)
    
    if cert_match:
        # 提取证书部分的文本
        start_pos = cert_match.end()
        # 查找下一个主要部分的开始
        next_section_pattern = r'(教育|工作|实习|项目|技能|获奖|自我评价|Education|Work|Internship|Project|Skill|Award|Self-evaluation)'
        next_section_match = re.search(next_section_pattern, text[start_pos:], re.IGNORECASE)
        
        if next_section_match:
            end_pos = start_pos + next_section_match.start()
        else:
            end_pos = len(text)
        
        cert_text = text[start_pos:end_pos]
        
        # 提取证书条目
        # 匹配证书列表
        cert_item_pattern = r'([^\n]+?)(?:\n|\r\n)(.*?)(?=(?:[^\n]+?\n|$))'
        cert_items = re.findall(cert_item_pattern, cert_text, re.DOTALL)
        
        for item in cert_items:
            cert_name = item[0].strip()
            details = item[1].strip()
            
            if cert_name:
                # 提取证书时间
                time_pattern = r'(\d{4}[-/]?\d{1,2}[-/]?\d{0,2}?)'
                time_match = re.search(time_pattern, details)
                cert_time = time_match.group(0).strip() if time_match else ""
                
                certificates.append({
                    "name": cert_name,
                    "time": cert_time
                })
    
    return certificates


def calculate_match_score(text, target_position, skills):
    """
    计算与目标岗位的匹配度
    """
    score = 50  # 基础分数
    
    # 目标岗位关键词
    position_keywords = {
        "前端开发": ["前端", "前端开发", "HTML", "CSS", "JavaScript", "React", "Vue", "Angular", "前端框架"],
        "后端开发": ["后端", "后端开发", "Python", "Java", "C++", "Node.js", "Flask", "Django", "FastAPI"],
        "全栈开发": ["全栈", "全栈开发", "前端", "后端", "HTML", "CSS", "JavaScript", "Python", "Java"],
        "移动开发": ["移动开发", "iOS", "Android", "React Native", "Flutter", "移动端"],
        "数据科学": ["数据科学", "数据分析", "机器学习", "深度学习", "Python", "R", "数据挖掘"],
        "人工智能": ["人工智能", "机器学习", "深度学习", "自然语言处理", "计算机视觉", "AI"],
        "产品经理": ["产品经理", "产品", "PM", "产品设计", "用户体验", "UX"],
        "UI设计": ["UI设计", "界面设计", "视觉设计", "设计", "Photoshop", "Sketch"],
        "DevOps": ["DevOps", "运维", "CI/CD", "Docker", "Kubernetes", "自动化"],
        "测试工程师": ["测试", "测试工程师", "QA", "质量保证", "自动化测试", "功能测试"]
    }
    
    # 获取目标岗位的关键词
    keywords = position_keywords.get(target_position, [])
    
    # 计算关键词匹配度
    for keyword in keywords:
        if keyword.lower() in text.lower():
            score += 5
    
    # 计算技能匹配度
    relevant_skills = {
        "前端开发": ["HTML", "CSS", "JavaScript", "React", "Vue", "Angular"],
        "后端开发": ["Python", "Java", "C++", "Node.js", "Flask", "Django"],
        "全栈开发": ["HTML", "CSS", "JavaScript", "Python", "Java", "React"],
        "移动开发": ["iOS", "Android", "React Native", "Flutter"],
        "数据科学": ["Python", "R", "SQL", "机器学习", "数据分析"],
        "人工智能": ["Python", "机器学习", "深度学习", "TensorFlow", "PyTorch"],
        "产品经理": ["产品设计", "用户体验", "市场分析", "项目管理"],
        "UI设计": ["Photoshop", "Sketch", "Figma", "UI设计", "视觉设计"],
        "DevOps": ["Docker", "Kubernetes", "CI/CD", "Linux", "AWS"],
        "测试工程师": ["测试", "自动化测试", "功能测试", "性能测试", "QA"]
    }
    
    # 获取目标岗位的相关技能
    rel_skills = relevant_skills.get(target_position, [])
    
    # 计算技能匹配度
    for skill in skills:
        if skill in rel_skills:
            score += 10
    
    # 确保分数在0-100之间
    score = min(score, 100)
    score = max(score, 0)
    
    return score


def parse_pdf(resume_content):
    """
    解析PDF文件
    
    参数:
        resume_content: PDF文件内容（字节）
    
    返回:
        解析后的文本
    """
    if not PDF_SUPPORT:
        logger.error("[Resume] 错误: PyPDF2 库未安装，无法解析PDF文件")
        return ""
    
    try:
        pdf_file = BytesIO(resume_content)
        reader = PdfReader(pdf_file)
        
        text = ""
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        logger.info(f"[Resume] PDF解析成功，提取文本长度: {len(text)} 字符")
        return text
    except Exception as e:
        logger.error(f"[Resume] 错误: PDF解析失败: {e}")
        import traceback
        traceback.print_exc()
        return ""
