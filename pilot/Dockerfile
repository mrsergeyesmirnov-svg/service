FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY pilot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=65534:65534 pilot/ .
USER 65534:65534
CMD ["python", "server.py"]
