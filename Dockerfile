# Container image for the Quant Trader web dashboard (AWS App Runner / any
# container host).  The trading engines read their state from DynamoDB / S3
# when STATE_TABLE / TRADES_TABLE / CACHE_BUCKET are set in the environment,
# so the image itself ships no state — see aws/deploy_web.sh.

FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source (data/cache, local state, and git history are excluded via
# .dockerignore so the image stays small)
COPY . .

# App Runner sends traffic to this port by default
EXPOSE 8080

# Production WSGI server — never the Flask dev server.
# 2 workers handle concurrent dashboard requests; the long timeout covers
# heavier /api/backtest calls that fetch and crunch historical data.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "web:create_app()"]
