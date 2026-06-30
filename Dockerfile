# Back de processamento (FastAPI) — imagem para Cloud Run.
# Cloud Run injeta $PORT (default 8080); o container precisa escutar nele.
FROM python:3.12-slim

WORKDIR /app

# deps primeiro (cache de camada)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PORT=8080
# shell form para expandir ${PORT} em runtime
CMD exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT}
