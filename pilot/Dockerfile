FROM python:3.12-slim
WORKDIR /app
COPY pilot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pilot/ .
USER 65534:65534
CMD ["python", "server.py"]
