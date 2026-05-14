FROM python:3.11-slim

# Установка системных зависимостей 
RUN apt-get update && \
	pip install --upgrade pip &&\
	rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "githubbot_send_OpenCTI.py"]
