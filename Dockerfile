FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10001 bma && mkdir /data && chown bma /data
USER bma
VOLUME /data
EXPOSE 8000
# Genau ein Prozess: der Zustand der Anlagen wird im Prozess gegen gleichzeitige Änderungen geschützt.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
