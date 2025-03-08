# Dockerfile

FROM python:3.11-slim

# 安装必要的包
RUN apt-get update && apt-get install -y inotify-tools && \
    pip install --no-cache-dir watchdog pyyaml

# 创建应用目录
WORKDIR /app

# 复制应用文件
COPY app/ /app/

# 创建日志和缓存目录
RUN mkdir -p /app/logs /app/cache

# 设置目录权限（确保所有用户都可读写）
RUN chmod -R 777 /app/logs /app/cache

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动脚本
CMD ["python", "sync.py"]