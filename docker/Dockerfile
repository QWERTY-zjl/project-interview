# ============================================================
# app 容器的镜像配方（学习注解版）
# 目录布局：容器里的 /srv 相当于本机的仓库根，/srv/app 相当于本机的 app/
# ============================================================

# FROM：基于官方「Python 3.10 最小 Linux」镜像搭建（本地有缓存时不会重复下载）
FROM python:3.10-slim

# RUN：在镜像里执行 shell 命令。装系统级依赖：
#   ffmpeg                  —— 语音处理
#   libpango / libgdk-pixbuf —— weasyprint（生成 PDF 面试报告）需要的系统库，缺了运行时报错
# 装完删除 apt 索引缓存，减小镜像体积
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# WORKDIR：设置后续指令的工作目录（不存在会自动创建）
# 定在 /srv：之后 python -m app.server 能在这里找到 app 包（同本机仓库根执行 start_server.bat）
WORKDIR /srv

# 先只复制依赖清单并安装 —— 利用 Docker 层缓存：
# requirements.txt 没变时，改代码后重新构建会直接跳过这层耗时的 pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再复制代码。COPY 的路径相对「构建上下文」（compose 里 context: .. = 仓库根）；
# venv/.env/数据库文件已被仓库根的 .dockerignore 挡在上下文外
COPY app/ ./app/

# EXPOSE：声明容器监听的端口（文档性声明，不生效；真正对外映射由 compose 的 ports 决定）
EXPOSE 10009

# CMD：容器启动时执行的命令 = 本机 start_server.bat 里的 python -m app.main
# uvicorn 启动 FastAPI 应用且 host=0.0.0.0，nginx 容器才能通过服务名 app 访问到它
CMD ["python", "-m", "app.main"]
