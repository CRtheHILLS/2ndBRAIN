FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY brain ./brain
COPY api ./api
COPY sync ./sync
RUN pip install --no-cache-dir .
ENV DATA_DIR=/data PORT=8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
