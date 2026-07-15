FROM python:3.11-slim
WORKDIR /app
ENV JARVIS_CLOUD=1
ENV PYTHONUNBUFFERED=1

COPY tg_bot_bg.py ./

CMD ["python", "tg_bot_bg.py"]
