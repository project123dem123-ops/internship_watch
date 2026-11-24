# Internship Watch -- Punjab and federal internships, checked on a timer.
# The web app and its background worker run in this one process (serve.py).
# Open http://<host>:8700/. Data (SQLite) lives in /data.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INTERNSHIPS_DATA_DIR=/data \
    INTERNSHIPS_PORT=8700

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY static ./static

RUN useradd --uid 1001 --create-home app && mkdir -p /data && chown app:app /data
USER 1001
VOLUME ["/data"]
EXPOSE 8700

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8700/health', timeout=4); sys.exit(0)"

CMD ["python", "serve.py"]
