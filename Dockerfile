# Образ для деплоя на Railway (или любой хост с Docker).
# Railway передаёт PORT в env; приложение читает его из config.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# PORT задаётся на Railway; по умолчанию 8000 для локального docker run
ENV PORT=8000
EXPOSE $PORT

CMD ["python", "-m", "app.main"]
