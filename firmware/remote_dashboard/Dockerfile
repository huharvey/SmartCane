FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system smartcane \
    && useradd --system --gid smartcane --home-dir /app --no-create-home smartcane
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=smartcane:smartcane . .

ENV WEB_HOST=0.0.0.0 WEB_PORT=8080
EXPOSE 8080
USER smartcane
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=3).read()"]
CMD ["python", "app.py"]
