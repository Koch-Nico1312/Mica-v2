FROM python:3.12-alpine
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app.py /app/app.py
CMD ["uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8094"]
