FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

ENV PYTHONPATH=/app/package

COPY package package

COPY server server

COPY worker_main.py .

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
