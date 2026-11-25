FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 NEON_GATEWAY_HOST=0.0.0.0 NEON_AUTO_TUNNEL=0 BOT_WEB_PORT=8080
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8765
CMD ["python", "neon_gateway.py"]
