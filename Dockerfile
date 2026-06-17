FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY market_watch/ market_watch/
COPY web/ web/

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn market_watch.api.app:app --host 0.0.0.0 --port ${PORT}"]
